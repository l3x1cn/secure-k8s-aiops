# Ruch Locust (T18) na działającym klastrze: przez ostatnią godzinę
# service:http_requests:rate1m{service="frontend"} oscyluje z okresem ok. 30 min
# (LoadTestShape w deploy/base/locust/locustfile.py).
# Test potrzebuje godziny historii od startu Locusta; przy młodszym podzie jest pomijany.
# W tej godzinie nie może być skoku ruchu S6 (fault-runner spike --users 50): psuje dopasowanie.
# Zapytania idą do Prometheusa przez proxy API serwera (kubectl get --raw), bez port-forwardu.
# Uruchomienie: uv run --locked pytest tests/observability/test_traffic.py
# (kubectl z mise.toml w PATH). Kontekst: zmienna KUBE_CONTEXT, domyślnie
# kind-secure-k8s-aiops, jak w Makefile.
import json
import os
import shutil
import subprocess
import time
import urllib.parse
from datetime import datetime

import numpy as np
import pytest

pytestmark = pytest.mark.observability

KUBE_CONTEXT = os.environ.get("KUBE_CONTEXT", "kind-secure-k8s-aiops")
PROMETHEUS_PROXY = (
    "/api/v1/namespaces/monitoring/services/prometheus-operated:9090/proxy"
)
RATE = 'service:http_requests:rate1m{namespace="shop", service="frontend"}'
WINDOW_SECONDS = 60 * 60
STEP_SECONDS = 30
# Okno reguły (1 min) i krok jej liczenia (30 s) po starcie Locusta: wcześniejsze próbki nie mają ruchu.
WARMUP_SECONDS = 5 * 60
EXPECTED_PERIOD_MINUTES = 30
PERIOD_TOLERANCE_MINUTES = 5
# Okresy kandydujące: od 10 min do długości okna.
CANDIDATE_PERIODS_MINUTES = range(10, 61)
# Sinusoida 10 ± 8 użytkowników daje amplitudę ok. 0,8 średniej; szum i obcięcie do 2–18 ją zmniejszają.
MIN_RELATIVE_AMPLITUDE = 0.3
MIN_R_SQUARED = 0.5


def kubectl(*args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["kubectl", "--context", KUBE_CONTEXT, *args],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        command = " ".join(args)
        pytest.fail(f"kubectl {command}: kod {result.returncode}, {result.stderr}")
    return result


def query_range(expr: str, start: float, end: float) -> list[tuple[float, float]]:
    """Próbki (czas unix, wartość) jedynej serii wyniku."""
    params = {"query": expr, "start": start, "end": end, "step": STEP_SECONDS}
    path = f"{PROMETHEUS_PROXY}/api/v1/query_range?" + urllib.parse.urlencode(params)
    body = json.loads(kubectl("get", "--raw", path).stdout)
    assert body["status"] == "success", body
    result = body["data"]["result"]
    assert len(result) == 1, f"{expr}: oczekiwana jedna seria, jest {result}"
    return [(float(t), float(v)) for t, v in result[0]["values"]]


def locust_started_at() -> float:
    """Start kontenera locust (czas unix); restart zaczyna sinusoidę od nowa."""
    pods = json.loads(
        kubectl(
            "get",
            "pods",
            "-n",
            "loadgen",
            "-l",
            "app.kubernetes.io/name=locust",
            "--field-selector=status.phase=Running",
            "-o",
            "json",
        ).stdout
    )["items"]
    assert len(pods) == 1, f"oczekiwany jeden działający pod locust, są {len(pods)}"
    started = pods[0]["status"]["containerStatuses"][0]["state"]["running"]["startedAt"]
    return datetime.fromisoformat(started).timestamp()


def fit_sine(
    times: np.ndarray, values: np.ndarray, period_seconds: float
) -> tuple[float, float, float]:
    """Średnia, amplituda i R² dopasowania a + b·sin + c·cos (najmniejsze kwadraty)."""
    phase = 2 * np.pi * times / period_seconds
    design = np.column_stack([np.ones_like(times), np.sin(phase), np.cos(phase)])
    coefficients, *_ = np.linalg.lstsq(design, values, rcond=None)
    residuals = values - design @ coefficients
    total = np.sum((values - values.mean()) ** 2)
    r_squared = 1 - np.sum(residuals**2) / total
    return coefficients[0], float(np.hypot(coefficients[1], coefficients[2])), r_squared


@pytest.fixture(scope="module", autouse=True)
def cluster() -> None:
    if shutil.which("kubectl") is None:
        pytest.fail("Brak kubectl w PATH: aktywuj mise albo użyj `mise exec --`.")
    kubectl(
        "wait",
        "-n",
        "loadgen",
        "--for=condition=Available",
        "deployment/locust",
        "--timeout=30s",
    )


def test_frontend_rate_oscillates_with_30_minute_period():
    end = time.time()
    start = end - WINDOW_SECONDS
    started = locust_started_at()
    if started + WARMUP_SECONDS > start:
        ready_in = (started + WARMUP_SECONDS - start) / 60
        pytest.skip(
            f"Locust działa za krótko: godzina ruchu będzie za {ready_in:.0f} min"
        )

    samples = query_range(RATE, start, end)
    # Luka w danych (np. restart Prometheusa) zaniżyłaby dopasowanie bez związku z Locustem.
    assert len(samples) >= 0.9 * WINDOW_SECONDS / STEP_SECONDS, (
        f"za mało próbek {RATE}: {len(samples)}"
    )
    times = np.array([t for t, _ in samples]) - start
    values = np.array([v for _, v in samples])

    fits = {
        minutes: fit_sine(times, values, minutes * 60)
        for minutes in CANDIDATE_PERIODS_MINUTES
    }
    best = max(fits, key=lambda minutes: fits[minutes][2])
    mean, amplitude, r_squared = fits[best]
    summary = (
        f"najlepszy okres {best} min: średnia {mean:.2f}/s, "
        f"amplituda {amplitude:.2f}/s, R² {r_squared:.2f} "
        "(skok ruchu S6 w ostatniej godzinie też daje ten błąd)"
    )
    assert abs(best - EXPECTED_PERIOD_MINUTES) <= PERIOD_TOLERANCE_MINUTES, summary
    assert amplitude >= MIN_RELATIVE_AMPLITUDE * mean, summary
    assert r_squared >= MIN_R_SQUARED, summary
