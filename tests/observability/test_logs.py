# Logi i zdarzenia (T17) na działającym klastrze: Alloy wysyła do Lokiego logi podów
# z /var/log/pods i zdarzenia Kubernetes z shop, loadgen, aiops i intruder, a Grafana ma
# źródło Loki (docs/architektura.md, sekcja „Kontrakt metryk i logów”; wartości chartów
# w deploy/observability/values/). Zapytania idą do Lokiego przez proxy API serwera
# (kubectl get --raw), bez port-forwardu; Grafanę test pyta pod http://localhost:3000
# (NodePort 30300) kontem z Secretu grafana-admin.
# Awarie wywołuje fault-runner: errors (logi ERROR w orders) i dwa razy crash (zdarzenie
# BackOff). Crash restartuje orders jak S5, więc alert PodRestarts wysyła e-mail.
# Uruchomienie: uv run --locked pytest tests/observability/test_logs.py
# (kubectl z mise.toml w PATH). Kontekst: zmienna KUBE_CONTEXT, domyślnie
# kind-secure-k8s-aiops, jak w Makefile.
import base64
import json
import os
import shutil
import subprocess
import time
import urllib.parse
import urllib.request

import pytest

pytestmark = pytest.mark.observability

KUBE_CONTEXT = os.environ.get("KUBE_CONTEXT", "kind-secure-k8s-aiops")
# Usługa loki z chartu Loki w trybie Monolithic (release loki, bez gatewaya).
LOKI_PROXY = "/api/v1/namespaces/monitoring/services/loki:3100/proxy"
LOKI_URL = "http://loki.monitoring.svc:3100"
GRAFANA_URL = "http://localhost:3000"
FAULT_RUNNER = ("exec", "-n", "loadgen", "deploy/fault-runner", "--", "fault-runner")
# Zapytania z kryteriów akceptacji T17.
ERROR_LOGS = '{namespace="shop", container="orders"} | json | level="ERROR"'
BACKOFF_EVENTS = (
    '{job="loki.source.kubernetes_events", namespace="shop"}'
    ' | json | reason="BackOff" | name=~"orders-.*"'
)
WAIT_SECONDS = 120
# Kolejne crashe w ciągu 10 min podwajają back-off kubeleta (10 s, 20 s, 40 s …),
# więc orders wraca później przy powtórzonym przebiegu testu.
RESTART_WAIT_SECONDS = 180


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


def fault_runner(*args: str) -> None:
    """Polecenie fault-runner w podzie loadgen/fault-runner, do 5 prób."""
    for _ in range(5):
        result = kubectl(*FAULT_RUNNER, *args, check=False)
        if result.returncode == 0:
            return
        # Po restarcie orders usługa dostaje endpoint chwilę po gotowości kontenera.
        time.sleep(2)
    pytest.fail(
        f"fault-runner {' '.join(args)}: kod {result.returncode}, {result.stderr}"
    )


def query_range(query: str, start_ns: int) -> list[tuple[dict, str]]:
    """Wpisy z Lokiego od start_ns do teraz: pary (etykiety strumienia, linia)."""
    params = urllib.parse.urlencode(
        {"query": query, "start": start_ns, "end": time.time_ns(), "limit": 100}
    )
    path = f"{LOKI_PROXY}/loki/api/v1/query_range?{params}"
    body = json.loads(kubectl("get", "--raw", path).stdout)
    assert body["status"] == "success", body
    return [
        (stream["stream"], value[1])
        for stream in body["data"]["result"]
        for value in stream["values"]
    ]


def wait_for_entries(query: str, start_ns: int) -> list[tuple[dict, str]]:
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        entries = query_range(query, start_ns)
        if entries:
            return entries
        time.sleep(5)
    pytest.fail(f"{query}: brak wpisów w Lokim po {WAIT_SECONDS} s")


def orders_status() -> tuple[int, bool]:
    """Liczba restartów i gotowość kontenera orders (jedyny pod Deploymentu)."""
    pods = json.loads(
        kubectl(
            "get",
            "pods",
            "-n",
            "shop",
            "-l",
            "app.kubernetes.io/name=orders",
            "-o",
            "json",
        ).stdout
    )["items"]
    running = [pod for pod in pods if "deletionTimestamp" not in pod["metadata"]]
    assert len(running) == 1, [pod["metadata"]["name"] for pod in running]
    status = running[0]["status"].get("containerStatuses", [{}])[0]
    return status.get("restartCount", 0), status.get("ready", False)


def wait_for_orders(restarts: int) -> None:
    """Czeka, aż kontener orders ma co najmniej `restarts` restartów i jest gotowy."""
    deadline = time.monotonic() + RESTART_WAIT_SECONDS
    current = orders_status()
    while time.monotonic() < deadline:
        current = orders_status()
        if current[0] >= restarts and current[1]:
            return
        time.sleep(2)
    pytest.fail(
        f"orders: (restarty, gotowy) = {current}, oczekiwane ({restarts}, True) "
        f"po {RESTART_WAIT_SECONDS} s"
    )


def grafana_get(path: str) -> dict:
    """Odpowiedź JSON API Grafany; konto admina z Secretu grafana-admin."""
    data = json.loads(
        kubectl(
            "get", "secret", "grafana-admin", "-n", "monitoring", "-o", "json"
        ).stdout
    )["data"]
    user, password = (
        base64.b64decode(data[key]).decode() for key in ("admin-user", "admin-password")
    )
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    request = urllib.request.Request(
        f"{GRAFANA_URL}{path}", headers={"Authorization": f"Basic {token}"}
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


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
        "app.kubernetes.io/name=loki",
        "--timeout=45s",
    )
    kubectl("rollout", "status", "-n", "monitoring", "daemonset/alloy", "--timeout=45s")
    kubectl(
        "wait",
        "-n",
        "loadgen",
        "--for=condition=Available",
        "deployment/fault-runner",
        "--timeout=30s",
    )


def test_grafana_has_loki_datasource():
    source = grafana_get("/api/datasources/uid/loki")
    assert (source["type"], source["url"]) == ("loki", LOKI_URL), source
    # Grafana sprawdza połączenie zapytaniem do Lokiego.
    health = grafana_get("/api/datasources/uid/loki/health")
    assert health["status"] == "OK", health


def test_orders_errors_fault_gives_error_logs():
    # Sekunda zapasu na różnicę zegarów i zaokrąglenia znaczników czasu.
    start_ns = time.time_ns() - 1_000_000_000
    fault_runner("fault", "errors", "--seconds", "30", "--param", "ratio=1")
    try:
        # POST /order frontendu woła POST /orders, a ten w czasie awarii zwraca 500.
        fault_runner("spike", "--users", "1", "--seconds", "15")
        entries = wait_for_entries(ERROR_LOGS, start_ns)
    finally:
        fault_runner("stop")
    assert all(labels["pod"].startswith("orders-") for labels, _ in entries), entries
    logged = [json.loads(line) for _, line in entries]
    assert any(
        entry["status"] == 500 and entry["route"] == "/orders" for entry in logged
    ), logged[:5]
    # level to też etykieta strumienia (stage.labels w Alloy), nie tylko pole z | json.
    selector = '{namespace="shop", container="orders", level="ERROR"}'
    assert query_range(selector, start_ns), f"{selector}: brak wpisów"


def test_backoff_event_after_repeated_crash():
    start_ns = time.time_ns() - 1_000_000_000
    restarts, _ = orders_status()
    wait_for_orders(restarts)
    crashes = 0
    try:
        # Pierwszy crash kubelet restartuje od razu. Drugi w ciągu 10 min trafia w okno
        # back-off (10 s), więc kubelet zapisuje zdarzenie BackOff.
        fault_runner("fault", "crash")
        crashes += 1
        wait_for_orders(restarts + crashes)
        fault_runner("fault", "crash")
        crashes += 1
        entries = wait_for_entries(BACKOFF_EVENTS, start_ns)
    finally:
        # Następne testy potrzebują działającego orders.
        wait_for_orders(restarts + crashes)
    event = json.loads(entries[0][1])
    assert (event["kind"], event["type"]) == ("Pod", "Warning"), event
    assert "Back-off restarting failed container orders" in event["msg"], event
