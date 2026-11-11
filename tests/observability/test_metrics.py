# Metryki (T16) na działającym klastrze: cele aplikacji, metryki Hubble i reguły nagrywające service:*
# (docs/architektura.md, sekcja „Kontrakt metryk i logów”; reguły w deploy/observability/recording-rules.yaml).
# Zapytania idą do Prometheusa przez proxy API serwera (kubectl get --raw), bez port-forwardu.
# Ruch HTTP dla reguł http_* daje `fault-runner spike` (frontend → orders) na czas testu reguł.
# Uruchomienie: uv run --locked pytest tests/observability/test_metrics.py
# (kubectl z mise.toml w PATH). Kontekst: zmienna KUBE_CONTEXT, domyślnie
# kind-secure-k8s-aiops, jak w Makefile.
import json
import math
import os
import shutil
import subprocess
import time
import urllib.parse
from collections.abc import Callable, Iterator

import pytest

pytestmark = pytest.mark.observability

KUBE_CONTEXT = os.environ.get("KUBE_CONTEXT", "kind-secure-k8s-aiops")
# prometheus-operated tworzy prometheus-operator niezależnie od nazwy release'u (jak make prometheus).
PROMETHEUS_PROXY = (
    "/api/v1/namespaces/monitoring/services/prometheus-operated:9090/proxy"
)
SERVICES = {"frontend", "orders"}
# Reguły z kontraktu, nie z pliku reguł: test łapie regułę usuniętą albo przemianowaną.
RECORDING_RULES = [
    "service:cpu_usage_ratio_of_limit",
    "service:memory_working_set_ratio_of_limit",
    "service:network_rx_bytes:rate1m",
    "service:network_tx_bytes:rate1m",
    "service:http_requests:rate1m",
    "service:http_errors_ratio:rate1m",
    "service:http_latency_p95_seconds:1m",
    "service:restarts:increase5m",
    "service:policy_drops:rate1m",
]
# Ruch trwa dłużej niż czekanie na reguły: scrape 15 s + okno 1 min + krok reguł 30 s. Zakończenie kubectl exec
# nie zatrzymuje procesu w podzie, więc spike kończy się sam po TRAFFIC_SECONDS.
TRAFFIC_SECONDS = 240
WAIT_SECONDS = 180


def kubectl(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["kubectl", "--context", KUBE_CONTEXT, *args],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if check and result.returncode != 0:
        command = " ".join(args)
        pytest.fail(f"kubectl {command}: kod {result.returncode}, {result.stderr}")
    return result


def query(expr: str) -> list[dict]:
    """Wynik zapytania natychmiastowego: lista serii z kluczami metric i value."""
    path = f"{PROMETHEUS_PROXY}/api/v1/query?" + urllib.parse.urlencode({"query": expr})
    body = json.loads(kubectl("get", "--raw", path).stdout)
    assert body["status"] == "success", body
    return body["data"]["result"]


def values_by_service(expr: str) -> dict[str, float]:
    return {
        series["metric"].get("service", ""): float(series["value"][1])
        for series in query(expr)
    }


@pytest.fixture(scope="module", autouse=True)
def cluster() -> None:
    if shutil.which("kubectl") is None:
        pytest.fail("Brak kubectl w PATH: aktywuj mise albo użyj `mise exec --`.")
    result = kubectl("get", "--raw", "/readyz", check=False)
    if result.returncode != 0:
        pytest.fail(f"Klaster {KUBE_CONTEXT} niedostępny (make up): {result.stderr}")
    kubectl(
        "wait",
        "-n",
        "monitoring",
        "--for=condition=Ready",
        "pod",
        "-l",
        "app.kubernetes.io/name=prometheus",
        "--timeout=60s",
    )
    # Źródło ruchu dla reguł http_*.
    kubectl(
        "wait",
        "-n",
        "loadgen",
        "--for=condition=Available",
        "deployment/fault-runner",
        "--timeout=30s",
    )


def wait_for_services(
    expr: str, accept: Callable[[float], bool], spike: subprocess.Popen | None = None
) -> None:
    """Czeka, aż expr ma dla każdej usługi wartość spełniającą accept."""
    deadline = time.monotonic() + WAIT_SECONDS
    values: dict[str, float] = {}
    while time.monotonic() < deadline:
        values = values_by_service(expr)
        if SERVICES <= values.keys() and all(
            accept(values[service]) for service in SERVICES
        ):
            return
        time.sleep(5)
    message = f"{expr}: po {WAIT_SECONDS} s serie {values}, oczekiwane {SERVICES}"
    if spike is not None and spike.poll() is not None:
        message += f"; fault-runner spike zakończony kodem {spike.returncode}: {spike.stderr.read()}"
    pytest.fail(message)


@pytest.fixture(scope="module")
def traffic() -> Iterator[subprocess.Popen]:
    spike = subprocess.Popen(
        [
            "kubectl",
            "--context",
            KUBE_CONTEXT,
            "exec",
            "-n",
            "loadgen",
            "deploy/fault-runner",
            "--",
            "fault-runner",
            "spike",
            "--users",
            "2",
            "--seconds",
            str(TRAFFIC_SECONDS),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        yield spike
    finally:
        spike.terminate()
        try:
            spike.wait(timeout=10)
        except subprocess.TimeoutExpired:
            spike.kill()


# Po make up Prometheus potrzebuje chwili na przeładowanie konfiguracji z nowymi ServiceMonitorami.
def test_app_targets_are_up():
    wait_for_services('up{namespace="shop"}', lambda value: value == 1.0)


def test_hubble_metrics_are_scraped():
    assert query("hubble_flows_processed_total"), "brak hubble_flows_processed_total"


@pytest.mark.parametrize("rule", RECORDING_RULES)
def test_recording_rule_has_finite_series_for_each_service(
    rule: str, traffic: subprocess.Popen
):
    wait_for_services(f'{rule}{{namespace="shop"}}', math.isfinite, traffic)
