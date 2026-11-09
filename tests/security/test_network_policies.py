# NetworkPolicy (T12) na działającym klastrze: dozwolone i odrzucane przepływy
# (docs/architektura.md, sekcja „Przepływy sieciowe”; manifesty w deploy/base/networkpolicies).
# Sondy uruchamia `kubectl exec` w podzie źródłowym: python w frontend, orders i fault-runner,
# curl w intruder. Cilium porzuca odrzucony pakiet SYN bez odpowiedzi, więc odrzucenie to
# przekroczenie czasu sondy (5 s); odmowa połączenia znaczy, że cel nie działa.
# Uruchomienie: uv run --locked pytest tests/security/test_network_policies.py
# (kubectl i hubble z mise.toml w PATH). Kontekst: zmienna KUBE_CONTEXT, domyślnie
# kind-secure-k8s-aiops, jak w Makefile.
import json
import os
import re
import shutil
import subprocess
import time
from collections.abc import Iterator

import pytest

pytestmark = pytest.mark.security

KUBE_CONTEXT = os.environ.get("KUBE_CONTEXT", "kind-secure-k8s-aiops")
PROBE_SECONDS = 5
HUBBLE_WAIT_SECONDS = 15

FRONTEND = ("shop", "frontend")
ORDERS = ("shop", "orders")
FAULT_RUNNER = ("loadgen", "fault-runner")
INTRUDER = ("intruder", "intruder")
DEFAULT_DENY_NAMESPACES = ["shop", "loadgen", "aiops"]

ORDERS_URL = "http://orders.shop.svc:8080"
FRONTEND_URL = "http://frontend.shop.svc:8080"
INTERNET = ("1.1.1.1", 443)

# stdout: "connected", "timeout" albo "error <wyjątek>".
TCP_PROBE = """
import socket, sys
try:
    socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=float(sys.argv[3])).close()
    print("connected")
except TimeoutError:
    print("timeout")
except OSError as exc:
    print(f"error {exc!r}")
"""

# stdout: kod HTTP albo "error <wyjątek>".
HTTP_PROBE = """
import sys, urllib.error, urllib.request
method, url, body, timeout = sys.argv[1:5]
request = urllib.request.Request(
    url, data=body.encode() or None, method=method,
    headers={"Content-Type": "application/json"},
)
try:
    print(urllib.request.urlopen(request, timeout=float(timeout)).status)
except urllib.error.HTTPError as exc:
    print(exc.code)
except OSError as exc:
    print(f"error {exc!r}")
"""

# (źródło, metoda, URL, treść, oczekiwany kod). frontend woła własne /order przez
# loopback, którego polityki nie obejmują, więc 201 dowodzi przepływu frontend → orders:
# frontend odpowiada 201 tylko po przyjęciu zamówienia przez orders, inaczej 502.
ALLOWED = [
    pytest.param(
        FRONTEND,
        "POST",
        "http://127.0.0.1:8080/order",
        '{"product_id": "kubek", "quantity": 1}',
        "201",
        id="frontend->orders",
    ),
    pytest.param(
        FAULT_RUNNER,
        "GET",
        f"{ORDERS_URL}/healthz",
        "",
        "200",
        id="fault-runner->orders",
    ),
    pytest.param(
        FAULT_RUNNER,
        "GET",
        f"{FRONTEND_URL}/healthz",
        "",
        "200",
        id="fault-runner->frontend",
    ),
]
INTERNET_SOURCES = [
    pytest.param(ORDERS, id="orders->internet"),
    pytest.param(FRONTEND, id="frontend->internet"),
    pytest.param(FAULT_RUNNER, id="fault-runner->internet"),
]


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


def run_in(
    workload: tuple[str, str], *command: str
) -> subprocess.CompletedProcess[str]:
    namespace, name = workload
    return kubectl(
        "exec", "-n", namespace, f"deploy/{name}", "--", *command, check=False
    )


def python_probe(workload: tuple[str, str], script: str, *args: str) -> str:
    result = run_in(workload, "python", "-c", script, *args)
    if result.returncode != 0:
        pytest.fail(f"sonda w {'/'.join(workload)}: {result.stderr}")
    return result.stdout.strip()


def tcp_connect(workload: tuple[str, str], host: str, port: int) -> str:
    return python_probe(workload, TCP_PROBE, host, str(port), str(PROBE_SECONDS))


def http_status(workload: tuple[str, str], method: str, url: str, body: str) -> str:
    return python_probe(workload, HTTP_PROBE, method, url, body, str(PROBE_SECONDS))


def intruder_curl(url: str) -> tuple[str, int]:
    """Kod HTTP i kod wyjścia curl w podzie intruder; ("000", 28) to przekroczony czas."""
    write_out = "%{http_code} %{exitcode}"
    result = run_in(
        INTRUDER,
        "curl",
        "-sS",
        "-o",
        "/dev/null",
        "-m",
        str(PROBE_SECONDS),
        "-w",
        write_out,
        url,
    )
    fields = result.stdout.split()
    if len(fields) != 2:
        pytest.fail(f"curl {url} w intruder: {result.stdout!r} {result.stderr}")
    return fields[0], int(fields[1])


def hubble_drops(server: str, from_namespace: str, to_namespace: str) -> list[dict]:
    """Odrzucone przepływy z ostatniej minuty (pole `flow` z `hubble observe -o json`)."""
    result = subprocess.run(
        [
            "hubble",
            "observe",
            "--server",
            server,
            "--verdict",
            "DROPPED",
            "--from-namespace",
            from_namespace,
            "--to-namespace",
            to_namespace,
            "--since",
            "1m",
            "--output",
            "json",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        pytest.fail(f"hubble observe: {result.stderr}")
    events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    return [event["flow"] for event in events if "flow" in event]


@pytest.fixture(scope="module", autouse=True)
def cluster() -> None:
    if shutil.which("kubectl") is None:
        pytest.fail("Brak kubectl w PATH: aktywuj mise albo użyj `mise exec --`.")
    result = kubectl("get", "--raw", "/readyz", check=False)
    if result.returncode != 0:
        pytest.fail(f"Klaster {KUBE_CONTEXT} niedostępny (make up): {result.stderr}")
    for namespace, name in (FRONTEND, ORDERS, FAULT_RUNNER, INTRUDER):
        kubectl(
            "wait",
            "-n",
            namespace,
            "--for=condition=Available",
            f"deployment/{name}",
            "--timeout=30s",
        )


@pytest.fixture(scope="module")
def internet() -> None:
    # Odrzucenie ruchu do internetu czegoś dowodzi tylko wtedy, gdy bez polityki ruch
    # wychodzi z klastra; intruder nie ma polityk, więc sprawdza to jego połączenie.
    _, exitcode = intruder_curl(f"https://{INTERNET[0]}/")
    if exitcode != 0:
        pytest.skip(
            f"brak internetu w klastrze: curl https://1.1.1.1 w intruder, kod {exitcode}"
        )


@pytest.fixture(scope="module")
def hubble_server() -> Iterator[str]:
    if shutil.which("hubble") is None:
        pytest.fail("Brak hubble w PATH: aktywuj mise albo użyj `mise exec --`.")
    # Losowy port lokalny, więc działające `make hubble-relay` (localhost:4245) nie przeszkadza.
    forward = subprocess.Popen(
        [
            "kubectl",
            "--context",
            KUBE_CONTEXT,
            "-n",
            "kube-system",
            "port-forward",
            "svc/hubble-relay",
            ":80",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert forward.stdout is not None and forward.stderr is not None
        # Pierwsza linia: "Forwarding from 127.0.0.1:<port> -> 4245".
        line = forward.stdout.readline()
        match = re.match(r"Forwarding from 127\.0\.0\.1:(\d+) ", line)
        if match is None:
            forward.kill()
            pytest.fail(f"port-forward do hubble-relay: {line}{forward.stderr.read()}")
        yield f"127.0.0.1:{match.group(1)}"
    finally:
        forward.terminate()
        forward.wait(timeout=10)


@pytest.mark.parametrize(("source", "method", "url", "body", "expected"), ALLOWED)
def test_allowed_flow(source, method, url, body, expected):
    assert http_status(source, method, url, body) == expected


def test_intruder_reaches_frontend():
    # Wiersz „dowolne → shop/frontend” z tablicy przepływów obejmuje też intruder.
    assert intruder_curl(f"{FRONTEND_URL}/healthz") == ("200", 0)


def test_intruder_to_orders_is_denied():
    assert intruder_curl(f"{ORDERS_URL}/healthz") == ("000", 28)


def test_orders_to_frontend_is_denied():
    assert tcp_connect(ORDERS, "frontend.shop.svc", 8080) == "timeout"


@pytest.mark.usefixtures("internet")
@pytest.mark.parametrize("source", INTERNET_SOURCES)
def test_egress_to_internet_is_denied(source):
    assert tcp_connect(source, *INTERNET) == "timeout"


@pytest.mark.parametrize("namespace", DEFAULT_DENY_NAMESPACES)
def test_namespace_has_default_deny(namespace):
    # Jedyny dowód dla aiops, który do T24 nie ma podów; w shop i loadgen chroni
    # pody bez własnej reguły (fault-runner nie ma polityki ingress).
    result = kubectl("get", "networkpolicies", "-n", namespace, "-o", "json")
    deny_all = [
        policy["metadata"]["name"]
        for policy in json.loads(result.stdout)["items"]
        if policy["spec"]["podSelector"] == {}
        and sorted(policy["spec"].get("policyTypes", [])) == ["Egress", "Ingress"]
        and not policy["spec"].get("ingress")
        and not policy["spec"].get("egress")
    ]
    assert deny_all, f"{namespace}: brak NetworkPolicy odcinającej cały ruch podów"


def test_hubble_shows_policy_denied_intruder_to_orders(hubble_server):
    # Świeży przepływ: `--since 1m` w hubble_drops pomija wpisy z wcześniejszych przebiegów.
    assert intruder_curl(f"{ORDERS_URL}/healthz") == ("000", 28)
    orders = {"name": "orders", "kind": "Deployment"}
    deadline = time.monotonic() + HUBBLE_WAIT_SECONDS
    while True:
        flows = hubble_drops(hubble_server, "intruder", "shop")
        if any(
            flow.get("drop_reason_desc") == "POLICY_DENIED"
            and orders in flow.get("destination", {}).get("workloads", [])
            for flow in flows
        ):
            return
        if time.monotonic() > deadline:
            pytest.fail(
                f"brak POLICY_DENIED intruder → shop/orders w Hubble: {flows[-3:]}"
            )
        time.sleep(1)
