# T12 · NetworkPolicy: default-deny, dozwolone przepływy, test niedozwolonego połączenia (issue #12)

## Context

Issue #12 (T12, R2 Bezpieczeństwo, Sprint 2). Cel: połączenia spoza dozwolonych ścieżek są odrzucane, co udowadnia test i widać w Hubble. Zakres:
- NetworkPolicy (tylko `networking.k8s.io/v1`) według sekcji „Przepływy sieciowe” w `docs/architektura.md`: default-deny ingress i egress w shop, loadgen i aiops oraz reguły allow, w tym DNS do kube-dns;
- Deployment `intruder` w namespace intruder: `curlimages/curl` przypięty po digest, non-root, `sleep infinity`;
- `tests/security/test_network_policies.py` z timeoutem 5 s:
  - dozwolone: frontend → orders (`POST /order`), fault-runner → orders `/healthz`, fault-runner → frontend;
  - odrzucane: intruder → orders, orders → frontend, orders/frontend/fault-runner → 1.1.1.1:443;
- `hubble observe --verdict DROPPED --from-namespace intruder` zawiera `POLICY_DENIED`.

Kryteria akceptacji: (1) wszystkie przypadki z macierzy przechodzą; (2) zrzut Hubble UI z odrzuconym przepływem intruder → orders jest w `docs/img/`.

Stan docelowy:
- `deploy/base/intruder/` (Deployment);
- `deploy/base/networkpolicies/` (13 NetworkPolicy); overlay `local` daje 38 obiektów zamiast 24;
- `tests/security/test_network_policies.py` (13 testów, marker `security`) przechodzi na klastrze z `make up`, razem z RBAC: `87 passed`;
- kontrakt w `docs/architektura.md`, zrzut `docs/img/hubble-intruder-orders-dropped.png`.

### Ustalone fakty (sprawdzone 2026-11-09)

- Repozytorium:
  - bieżąca gałąź to `t11-rbac` (HEAD `3e7fc92`), czyli T11 w otwartym PR #51; `origin/main` = `40cdcbe` (T10);
  - T12 potrzebuje T11: konto `intruder/intruder` (`deploy/base/rbac/serviceaccounts.yaml`), `tests/security/test_rbac.py` i marker `security` w `pyproject.toml`;
  - w drzewie jest nieśledzony, nieaktualny szkic tego planu `docs/plans/2026-11-09-t12-networkpolicy.md`.
- Klaster `kind-secure-k8s-aiops` działa:
  - pody frontend, orders (shop) i fault-runner (loadgen); w aiops, intruder i monitoring nie ma podów;
  - jedyna NetworkPolicy to `kube-system/hubble-relay-ui-ingress`;
  - Cilium 1.20.3: `kube-proxy-replacement=false`, `routing-mode=tunnel`, `--allow-localhost='auto'`, log agenta „k8s mode: Allowing localhost to reach local endpoints”. Ruch z węzła do jego podów, w tym sondy kubeleta, omija więc polityki.
- Zachowanie polityk (spike w tymczasowych namespace'ach oraz odrzucenie przez istniejącą `hubble-relay-ui-ingress`):
  - Cilium egzekwuje politykę dla ruchu przez ClusterIP względem poda docelowego;
  - odrzucenie to porzucony SYN bez odpowiedzi: `socket.create_connection(..., timeout=5)` rzuca `TimeoutError` po 5,2 s, a `urllib` daje `URLError(TimeoutError('timed out'))`;
  - curl z `-m 5 -w '%{http_code} %{exitcode}'` wypisuje `000 28`;
  - `kubectl exec` działa pod default-deny.
- Hubble:
  - `kubectl -n kube-system port-forward svc/hubble-relay :80` wypisuje jako pierwszą linię `Forwarding from 127.0.0.1:<port> -> 4245`;
  - `hubble observe --server 127.0.0.1:<port> --verdict DROPPED --from-namespace <ns> --to-namespace <ns> --since 1m -o json` zwraca po jednym obiekcie JSON na linię z polem `flow`. Formatu `-o jsonl` nie ma;
  - przepływ odrzucony po stronie ingress ma `drop_reason_desc: POLICY_DENIED`, `traffic_direction: INGRESS`, `destination.namespace`, `destination.pod_name` i `destination.workloads: [{"name": "<deployment>", "kind": "Deployment"}]`. `source.workloads` bywa `null`. Każde odrzucenie pojawia się dwa razy (zdarzenie drop i policy verdict), oba razy z `POLICY_DENIED`;
  - bufor ma 4095 przepływów na węzeł (12 285 na 3 węzłach), co przy 14,6 przepływu/s daje ok. 14 minut.
- Hubble UI:
  - `cilium hubble ui --context kind-secure-k8s-aiops --open-browser=false` wystawia `http://localhost:12000`, a `make hubble-ui` bez tej flagi otwiera przeglądarkę;
  - adres `?namespace=<ns>&verdicts=2` pokazuje tylko odrzucone przepływy (dropdown „Dropped”); `verdict=dropped` nie działa;
  - tabela ma kolumny Source Identity, Destination Identity, Destination Port i Verdict (`dropped` na czerwono);
  - zrzut przeglądarki 1400×900 ma 1750×1125 px i ok. 166 KB w PNG.
- Obraz `docker.io/curlimages/curl:8.23.0`:
  - indeks wieloarchitekturowy `sha256:3fb7e13e5d179a845c97d78204f3f1064d1907037f26a3ebf91710571151fd93`, w dniu sprawdzenia równy `latest`;
  - Alpine 3.24.3 i BusyBox 1.37 (`ls`, `sleep infinity`), domyślny użytkownik `curl_user` (uid 100);
  - jako `--user 10001:10001 --read-only --cap-drop ALL` curl działa, a `ls /var/run/secrets/kubernetes.io/serviceaccount` kończy się `No such file or directory`;
  - `trivy image --severity HIGH,CRITICAL --ignore-unfixed`: 0 podatności.
- Pody aplikacji:
  - frontend, orders i fault-runner mają `python` w PATH (`/app/.venv/bin`), ale nie mają `curl`;
  - frontend słucha na `0.0.0.0:8080` (loopback działa) i woła orders pod adresem `http://orders:8080` (domyślne `ORDERS_URL`);
  - `POST /order` frontendu zwraca 201 tylko wtedy, gdy orders odpowie 201. Błąd httpx albo inny status daje 502, a nieznany produkt 404;
  - `fault-runner stop` wypisuje odpowiedź orders `{"stopped":null}`, gdy żadna awaria nie trwa.
- Etykiety podów:
  - prometheus-operator (`pkg/operator/kubernetes.go`: `ApplicationNameLabelKey = "app.kubernetes.io/name"`; `pkg/prometheus/server/operator.go`, `makeSelectorLabels`) nadaje podom Prometheusa `app.kubernetes.io/name: prometheus`;
  - chart Loki z `grafana-community/helm-charts` (21.0.0, `loki.selectorLabels`) nadaje `app.kubernetes.io/name: loki`;
  - CoreDNS w kind ma `k8s-app=kube-dns`;
  - obiekty z T11 mają etykietę `app.kubernetes.io/part-of: secure-k8s-aiops`.
- Prototyp na kopii `deploy/` poza repo (narzędzia z `mise.toml`), z dokładnie tymi manifestami co w Task 2 i 3:
  - `scripts/manifests.sh` → `Summary: 38 resources found parsing stdin - Valid: 38`, w tym 13 NetworkPolicy;
  - kustomize stosuje NetworkPolicy po Deploymentach;
  - `trivy config --severity HIGH,CRITICAL --exit-code 1 deploy/` → kod 0. Pliki NetworkPolicy mają 0 uwag, a intruder tylko KSV-0110 (LOW) i KSV-0125 (MEDIUM), tak jak pozostałe Deploymenty.
- Prototyp testu z Task 1:
  - `ruff check` i `ruff format --check` z konfiguracją repo przechodzą; pytest zbiera 13 testów;
  - helpery uruchomione na żywym klastrze dają `connected` i `timeout`, HTTP 200, a fixture port-forward i dopasowanie przepływu działają na odrzuceniu loadgen → hubble-relay.
- `pyproject.toml`:
  - `testpaths` nie obejmuje `tests/`, więc `make unit` testów klastrowych nie zbiera;
  - ruff ma `select = ["E4", "E7", "E9", "F"]` i `line-length = 88`; `make lint` to `ruff check` i `ruff format --check`, także dla bloków ```python w `.md`;
  - `tests/security/test_rbac.py` zbiera 74 testy.

## Warunek wstępny (główny agent, przed startem delivery)

W korzeniu repozytorium:

```bash
rm docs/plans/2026-11-09-t12-networkpolicy.md   # nieaktualny szkic tego planu, nieśledzony
git status --short                               # oczekiwane: pusto
gh pr view 51 --repo l3x1cn/secure-k8s-aiops --json state --jq .state
```

- `MERGED` → `git switch main && git pull --ff-only && git switch -c t12-networkpolicy`.
- `OPEN` → `git switch t11-rbac && git pull --ff-only && git switch -c t12-networkpolicy`. Gałąź stoi wtedy na T11 (stacked).

Verification i Task 4 wymagają:
- klastra `kind-secure-k8s-aiops`; `kind get clusters` go wypisuje, a jeśli nie, to `make up`;
- Dockera bez sudo i dostępu do Docker Hub (obraz intruder);
- wolnych portów 8080 i 12000 na `127.0.0.1`.

## Approach

Task 1 to stos Python, Task 2–4 to stos „pozostałe” (YAML, Markdown, PNG). Kolejność 1 → 2 → 3 → 4:
- najpierw test, który bez polityk pada w 9 z 13 przypadków (krok 2 Verification);
- potem pod intruder, który nie zmienia ruchu, a jest źródłem ataku dla testu;
- potem polityki;
- na końcu kontrakt i zrzut z działającego klastra.

Taski 1–3 sprawdzają tylko to, co działa bez klastra: `make lint`, `make unit`, `make manifests`, Trivy. Przebiegi na klastrze są w Verification.

Decyzje wspólne:
- Polityki leżą w `deploy/base/networkpolicies/` z jawnym `namespace` w każdym obiekcie, bez transformatora namespace (wzór `deploy/base/rbac`).
- Jedna polityka to jeden workload i jeden kierunek (`<workload>-ingress`, `<workload>-egress`), do tego `default-deny` i `allow-dns` w każdym z trzech namespace'ów. Polityki Kubernetes się sumują, więc podział nie zmienia semantyki.
- Pod wskazuje `podSelector` z `app.kubernetes.io/name`. W `from` polityki orders fault-runnera wskazuje `role: fault-runner`, etykieta, którą T08 dodał z komentarzem „Selektor NetworkPolicy (T12)”. Namespace wskazuje `kubernetes.io/metadata.name`.
- Peer z namespaceSelector i podSelector w jednym elemencie listy oznacza oba warunki naraz. Rozbicie go na dwa elementy wpuściłoby każdy pod z tą etykietą w dowolnym namespace albo każdy pod z namespace'u.
- `allow-dns` wybiera wszystkie pody z `policyTypes: [Egress]`, więc sam izoluje egress każdego poda. `default-deny` dokłada izolację ingress podów bez własnej reguły (np. fault-runner) i jest jedyną ochroną aiops, gdzie do T24 nie ma podów.
- Reguły z tablicy dla workloadów, których jeszcze nie ma (locust, anomaly-detector), i dla Prometheusa i Lokiego powstają teraz. Do czasu wdrożenia wybierają zero podów.
- Namespace intruder nie dostaje polityk.

### Task 1: Test NetworkPolicy na klastrze
**Commit:** test(security): macierz przepływów NetworkPolicy i odrzucenie w Hubble (T12)

**Files:**
- Test: `tests/security/test_network_policies.py`
- Test: `tests/security/test_rbac.py`

1. Utwórz `tests/security/test_network_policies.py` z treścią poniżej (sformatowana ruffem 0.17.3; nie zmieniaj formatowania). Decyzje w tej treści:
   - Połączenia sprawdza `kubectl exec` w podzie źródłowym: `python -c` w frontend, orders i fault-runner, `curl` w intruder. Nie używa klienta Pythona dla Kubernetesa (wzór `test_rbac.py`).
   - Odrzucony przypadek musi dać przekroczenie czasu: `timeout` w sondzie TCP albo `("000", 28)` z curl. Inny błąd (odmowa połączenia, DNS) oznacza, że cel nie działa, i oblewa test.
   - frontend → orders: exec w podzie frontend i `POST http://127.0.0.1:8080/order`. Loopback nie przechodzi przez politykę, więc 201 dowodzi tylko przepływu frontend → orders. Adres `frontend.shop.svc` z wnętrza frontendu odrzuciłaby `frontend-egress`.
   - Dwa przypadki ponad macierz issue:
     - `test_intruder_reaches_frontend`: wiersz „dowolne → shop/frontend” w architekturze wymienia intruder;
     - `test_namespace_has_default_deny`: jedyny dowód default-deny dla aiops.
   - Przypadki z 1.1.1.1:443 zależą od fixture `internet`. Gdy intruder (bez polityk) nie łączy się z `https://1.1.1.1/`, fixture je pomija. Brak kubectl, hubble albo klastra to błąd, nie pominięcie (wzór `test_rbac.py`).
   - Hubble:
     - fixture otwiera `kubectl port-forward svc/hubble-relay :80` na losowym porcie, więc działające `make hubble-relay` na 4245 nie przeszkadza;
     - test najpierw wywołuje świeże odrzucenie, potem do 15 s czyta `hubble observe --since 1m` i szuka `POLICY_DENIED` z celem `{"name": "orders", "kind": "Deployment"}` w `destination.workloads`.
   - Kontrakt dla Task 2 i 3:
     - Deploymenty `shop/frontend`, `shop/orders`, `loadgen/fault-runner`, `intruder/intruder`;
     - usługi `orders.shop.svc:8080` i `frontend.shop.svc:8080`;
     - w shop, loadgen i aiops polityka z `podSelector: {}`, `policyTypes` Ingress i Egress, bez reguł.

```python
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
```

2. `tests/security/test_rbac.py`, `DEPLOYED_WORKLOADS` (linie 30–35): dodaj `("intruder", "intruder")`, a komentarz nad zbiorem zmień na `# Wdrożone workloady; locust i anomaly-detector dochodzą w T18 i T24.`. Wtedy `test_own_deployments_use_their_service_account` i `test_own_pods_have_no_service_account_token` wymagają poda intruder, a nie tylko go tolerują. Liczba testów RBAC zostaje 74.
3. Sprawdź:
   - `make lint` przechodzi;
   - `mise exec -- uv run --locked pytest --collect-only -q tests/security/test_network_policies.py` daje `13 tests collected`, bez ostrzeżenia o nieznanym markerze;
   - `make unit` zbiera tyle testów co przed zmianą.

   Testu nie uruchamiaj na klastrze: manifesty z Task 2 i 3 jeszcze nie istnieją, a przebieg jest w Verification.

### Task 2: Deployment intruder
**Commit:** feat(deploy): pod intruder do testu niedozwolonego połączenia (T12)

**Files:**
- Create: `deploy/base/intruder/kustomization.yaml`
- Create: `deploy/base/intruder/deployment.yaml`
- Modify: `deploy/base/kustomization.yaml`
- Modify: `deploy/base/rbac/serviceaccounts.yaml`

1. `deploy/base/intruder/kustomization.yaml` (wzór `deploy/base/fault-runner/kustomization.yaml`):

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: intruder
resources:
  - deployment.yaml
```

2. `deploy/base/intruder/deployment.yaml`:
   - bez sond, bo kontener tylko śpi;
   - bez `ports`, bo nic nie słucha;
   - bez wolumenów, bo curl pisze do `/dev/null`;
   - obrazu nie dopisuj do `images:` w overlayu ani do `make images`. Patch overlayu `local` dokłada `imagePullPolicy: IfNotPresent` każdemu Deploymentowi, także temu.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: intruder
  labels:
    app.kubernetes.io/name: intruder
    app.kubernetes.io/part-of: secure-k8s-aiops
spec:
  replicas: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: intruder
  template:
    metadata:
      labels:
        app.kubernetes.io/name: intruder
        app.kubernetes.io/part-of: secure-k8s-aiops
    spec:
      # Własne konto bez uprawnień RBAC (T11, deploy/base/rbac); pod nie dostaje tokenu API.
      serviceAccountName: intruder
      automountServiceAccountToken: false
      securityContext:
        runAsNonRoot: true
        # Obraz działa jako curl_user (uid 100); 10001 jak w pozostałych workloadach (Trivy KSV-0020, KSV-0021).
        runAsUser: 10001
        runAsGroup: 10001
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: intruder
          # Atakujący z wnętrza klastra (T12): namespace intruder nie ma NetworkPolicy, a test
          # (tests/security/test_network_policies.py) i demo uruchamiają curl przez `kubectl exec`.
          # Obraz zewnętrzny przypięty tagiem i digestem indeksu (wszystkie architektury); overlay go nie zmienia.
          # Podbicie: digest z `docker buildx imagetools inspect docker.io/curlimages/curl:<wersja>`,
          # potem `trivy image --severity HIGH,CRITICAL --ignore-unfixed <obraz>` bez wyników.
          image: docker.io/curlimages/curl:8.23.0@sha256:3fb7e13e5d179a845c97d78204f3f1064d1907037f26a3ebf91710571151fd93
          command: [sleep, infinity]
          resources:
            requests:
              cpu: 10m
              memory: 16Mi
            limits:
              cpu: 100m
              memory: 32Mi
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: [ALL]
```

3. `deploy/base/kustomization.yaml`: w `resources` dopisz `- intruder` zaraz po `- fault-runner`.
4. `deploy/base/rbac/serviceaccounts.yaml`, linia 4: zmień komentarz na `# locust (T18) i anomaly-detector (T24) mają konto przed swoimi Deploymentami.`. Konto intruder już istnieje i się nie zmienia.
5. Sprawdź:
   - `make manifests` → `Summary: 25 resources found parsing stdin - Valid: 25`;
   - `mise exec -- trivy config --skip-version-check --severity HIGH,CRITICAL --exit-code 1 deploy/` → kod 0.

### Task 3: NetworkPolicy w deploy/base/networkpolicies
**Commit:** feat(deploy): NetworkPolicy default-deny i dozwolone przepływy w shop, loadgen i aiops (T12)

**Files:**
- Create: `deploy/base/networkpolicies/kustomization.yaml`
- Create: `deploy/base/networkpolicies/default-deny.yaml`
- Create: `deploy/base/networkpolicies/dns.yaml`
- Create: `deploy/base/networkpolicies/shop.yaml`
- Create: `deploy/base/networkpolicies/loadgen.yaml`
- Create: `deploy/base/networkpolicies/aiops.yaml`
- Modify: `deploy/base/kustomization.yaml`

Nazwy polityk i selektory poniżej realizują tablicę „Przepływy sieciowe”. Nie łącz osobnych elementów `from`/`to` w jeden ani nie rozbijaj peerów z dwoma selektorami.

1. `deploy/base/kustomization.yaml`: w `resources` dopisz `- networkpolicies` zaraz po `- rbac`.
2. `deploy/base/networkpolicies/kustomization.yaml`:

```yaml
# NetworkPolicy (T12, docs/architektura.md „Przepływy sieciowe”): default-deny w shop, loadgen i aiops
# oraz jawnie dozwolone przepływy. Bez pola namespace: polityki leżą w trzech namespace'ach,
# więc każdy obiekt podaje swój jawnie (jak deploy/base/rbac).
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - default-deny.yaml
  - dns.yaml
  - shop.yaml
  - loadgen.yaml
  - aiops.yaml
```

3. `deploy/base/networkpolicies/default-deny.yaml`:

```yaml
# Bazowa polityka (T12): pod w shop, loadgen albo aiops bez reguły allow nie przyjmuje ani nie wysyła ruchu.
# Reguły allow są w dns.yaml i w plikach namespace'ów; polityki się sumują.
# Trzy kopie różnią się tylko namespace'em: zmieniaj razem (test_namespace_has_default_deny).
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny
  namespace: shop
  labels:
    app.kubernetes.io/part-of: secure-k8s-aiops
spec:
  podSelector: {}
  policyTypes: [Ingress, Egress]
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny
  namespace: loadgen
  labels:
    app.kubernetes.io/part-of: secure-k8s-aiops
spec:
  podSelector: {}
  policyTypes: [Ingress, Egress]
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny
  namespace: aiops
  labels:
    app.kubernetes.io/part-of: secure-k8s-aiops
spec:
  podSelector: {}
  policyTypes: [Ingress, Egress]
```

4. `deploy/base/networkpolicies/dns.yaml`:

```yaml
# DNS (T12): każdy pod w shop, loadgen i aiops rozwiązuje nazwy przez kube-dns (CoreDNS w kube-system).
# Trzy kopie różnią się tylko namespace'em: zmieniaj razem.
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns
  namespace: shop
  labels:
    app.kubernetes.io/part-of: secure-k8s-aiops
spec:
  podSelector: {}
  policyTypes: [Egress]
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns
  namespace: loadgen
  labels:
    app.kubernetes.io/part-of: secure-k8s-aiops
spec:
  podSelector: {}
  policyTypes: [Egress]
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns
  namespace: aiops
  labels:
    app.kubernetes.io/part-of: secure-k8s-aiops
spec:
  podSelector: {}
  policyTypes: [Egress]
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
```

5. `deploy/base/networkpolicies/shop.yaml`:

```yaml
# Przepływy w shop (T12, docs/architektura.md „Przepływy sieciowe”). Peer z namespaceSelector i podSelector
# w jednym elemencie listy `from`/`to` wymaga obu warunków naraz; osobne elementy listy to alternatywa.
# orders nie ma reguły egress poza DNS (dns.yaml), więc orders → frontend i orders → internet są odrzucane.
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: frontend-ingress
  namespace: shop
  labels:
    app.kubernetes.io/part-of: secure-k8s-aiops
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: frontend
  policyTypes: [Ingress]
  ingress:
    # Publiczna usługa: dowolne źródło (NodePort, Locust, fault-runner, intruder, Prometheus), tylko port 8080.
    - ports:
        - protocol: TCP
          port: 8080
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: frontend-egress
  namespace: shop
  labels:
    app.kubernetes.io/part-of: secure-k8s-aiops
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: frontend
  policyTypes: [Egress]
  egress:
    - to:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: orders
      ports:
        - protocol: TCP
          port: 8080
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: orders-ingress
  namespace: shop
  labels:
    app.kubernetes.io/part-of: secure-k8s-aiops
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: orders
  policyTypes: [Ingress]
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: frontend
        # Etykieta z T08: tylko fault-runner może wołać /faults/*.
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: loadgen
          podSelector:
            matchLabels:
              role: fault-runner
        # Prometheus (T16): prometheus-operator nadaje podom app.kubernetes.io/name=prometheus.
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: monitoring
          podSelector:
            matchLabels:
              app.kubernetes.io/name: prometheus
      ports:
        - protocol: TCP
          port: 8080
```

6. `deploy/base/networkpolicies/loadgen.yaml`:

```yaml
# Przepływy z loadgen (T12): fault-runner i locust wołają tylko usługi w shop na porcie 8080.
# Do podów loadgen nikt się nie łączy (fault-runner czeka na `kubectl exec`), więc ingress odcina default-deny.
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: fault-runner-egress
  namespace: loadgen
  labels:
    app.kubernetes.io/part-of: secure-k8s-aiops
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: fault-runner
  policyTypes: [Egress]
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: shop
          podSelector:
            matchLabels:
              app.kubernetes.io/name: orders
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: shop
          podSelector:
            matchLabels:
              app.kubernetes.io/name: frontend
      ports:
        - protocol: TCP
          port: 8080
---
# Locust (T18): Deployment nadaje podowi app.kubernetes.io/name=locust.
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: locust-egress
  namespace: loadgen
  labels:
    app.kubernetes.io/part-of: secure-k8s-aiops
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: locust
  policyTypes: [Egress]
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: shop
          podSelector:
            matchLabels:
              app.kubernetes.io/name: frontend
      ports:
        - protocol: TCP
          port: 8080
```

7. `deploy/base/networkpolicies/aiops.yaml`:

```yaml
# Przepływy anomaly-detector (T24): Prometheus pobiera /metrics, a detektor czyta cechy z Prometheusa
# i zdarzenia z Lokiego. Etykiety: prometheus-operator nadaje app.kubernetes.io/name=prometheus (T16),
# chart Loki app.kubernetes.io/name=loki (T17).
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: anomaly-detector-ingress
  namespace: aiops
  labels:
    app.kubernetes.io/part-of: secure-k8s-aiops
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: anomaly-detector
  policyTypes: [Ingress]
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: monitoring
          podSelector:
            matchLabels:
              app.kubernetes.io/name: prometheus
      ports:
        - protocol: TCP
          port: 8080
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: anomaly-detector-egress
  namespace: aiops
  labels:
    app.kubernetes.io/part-of: secure-k8s-aiops
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: anomaly-detector
  policyTypes: [Egress]
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: monitoring
          podSelector:
            matchLabels:
              app.kubernetes.io/name: prometheus
      ports:
        - protocol: TCP
          port: 9090
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: monitoring
          podSelector:
            matchLabels:
              app.kubernetes.io/name: loki
      ports:
        - protocol: TCP
          port: 3100
```

8. Sprawdź:
   - `make manifests` → `Summary: 38 resources found parsing stdin - Valid: 38`;
   - `mise exec -- kustomize build deploy/overlays/local | grep -c '^kind: NetworkPolicy'` → `13`;
   - `mise exec -- trivy config --skip-version-check --severity HIGH,CRITICAL --exit-code 1 deploy/` → kod 0.

### Task 4: Kontrakt sieci w architekturze, README i zrzut Hubble UI
**Commit:** docs: kontrakt NetworkPolicy, test i zrzut Hubble UI (T12)

**Files:**
- Modify: `docs/architektura.md`
- Modify: `README.md`
- Create: `docs/img/hubble-intruder-orders-dropped.png`

1. `docs/architektura.md`, tabela „Komponenty i wersje”: wiersz intruder (linia 19) zamień na:
   `| intruder (`docker.io/curlimages/curl`) | 8.23.0, przypięta po digest w `deploy/base/intruder/deployment.yaml` | intruder | T12 |`
2. `docs/architektura.md`, linia 23: pierwsze zdanie („Wersje oznaczone „przypięta” wybiera się w dniu realizacji zadania (najnowsza stabilna) i wpisuje do `platform/versions.env`.”) zamień na zdanie poniżej. Reszta akapitu zostaje.
   „Wersje oznaczone „przypięta” wybiera się w dniu realizacji zadania (najnowsza stabilna) i wpisuje do `platform/versions.env`, gdy czyta je Makefile; obraz zewnętrzny używany tylko w manifeście z `deploy/` (intruder) przypina się tagiem i digestem w tym manifeście.”
3. `docs/architektura.md`, sekcja „Przepływy sieciowe”: listę od „Testy (T12) sprawdzają, że te przepływy są odrzucane:” do „- fault-runner → internet” (linie 119–124) zastąp treścią poniżej. Zdanie o `networking.k8s.io/v1` i akapit o kube-system zostają.

```markdown
Manifesty są w `deploy/base/networkpolicies/` (T12); każdy obiekt podaje swój namespace:
- `default-deny.yaml`: polityka `default-deny` w shop, loadgen i aiops (wszystkie pody, Ingress i Egress, bez reguł);
- `dns.yaml`: polityka `allow-dns` w tych samych namespace'ach (wszystkie pody → kube-dns, 53 UDP/TCP);
- `shop.yaml`, `loadgen.yaml`, `aiops.yaml`: reguły allow z tablicy, po jednej polityce na workload i kierunek (`<workload>-ingress`, `<workload>-egress`).

Polityki się sumują: pod przyjmuje i wysyła tylko ruch dopuszczony przez którąś z nich. Namespace intruder nie ma polityk: pod `intruder` (`curlimages/curl`, czeka na `kubectl exec`) gra atakującego z wnętrza klastra, a jego ruch do orders odrzuca polityka `orders-ingress`. Cilium wpuszcza do poda ruch z jego węzła niezależnie od polityk (`allow-localhost`), więc sondy kubeleta działają.

Reguły wskazują pody etykietami, a namespace'y etykietą `kubernetes.io/metadata.name`. Zmiana etykiety albo portu workloadu wymaga zmiany reguły:

| Etykieta poda | Namespace | Nadaje ją |
|---|---|---|
| `app.kubernetes.io/name`: `frontend`, `orders`, `fault-runner`, `locust`, `anomaly-detector` | shop, loadgen, aiops | Deploymenty (T05, T08, T18, T24) |
| `role: fault-runner` | loadgen | Deployment fault-runner (T08); jedyny klient `/faults/*` w orders |
| `app.kubernetes.io/name: prometheus` | monitoring | prometheus-operator (T16) |
| `app.kubernetes.io/name: loki` | monitoring | chart Loki (T17) |

Nowy workload w shop, loadgen albo aiops dopisuje wiersz w tablicy przepływów i reguły w `deploy/base/networkpolicies/`; bez nich ma tylko DNS.

Test: `tests/security/test_network_policies.py` (marker `security`). Sonda w podzie źródłowym trwa najwyżej 5 s; Cilium porzuca odrzucony pakiet bez odpowiedzi, więc odrzucenie to przekroczenie czasu. Test sprawdza:
- dozwolone: frontend → orders (`POST /order` frontendu), fault-runner → orders `/healthz`, fault-runner → frontend, intruder → frontend;
- odrzucane: intruder → orders, orders → frontend, orders → internet, frontend → internet, fault-runner → internet (1.1.1.1:443; bez wyjścia klastra do internetu te trzy przypadki są pomijane);
- politykę default-deny w shop, loadgen i aiops;
- odrzucenie intruder → orders z powodem `POLICY_DENIED` w Hubble.

Ręcznie: `make hubble-relay`, w drugim terminalu `hubble observe --verdict DROPPED --from-namespace intruder`. Bufor Hubble ma 4095 przepływów na węzeł (w spokojnym klastrze kilkanaście minut), więc przepływ trzeba wywołać tuż przed odczytem. W Hubble UI (`make hubble-ui`) adres `http://localhost:12000/?namespace=intruder&verdicts=2` pokazuje tylko odrzucone przepływy:

![Hubble UI: przepływ intruder → orders odrzucony przez NetworkPolicy](img/hubble-intruder-orders-dropped.png)
```

4. `README.md`:
   - linia 65: „(kubectl z mise w PATH; …)” zmień na „(kubectl i hubble z mise w PATH; …)”;
   - linia 68: komentarz po `uv run --locked pytest tests/security` zmień na `# RBAC (T11) i NetworkPolicy (T12): konta usług, role zespołu, dozwolone i odrzucane przepływy`;
   - linia 81: pierwsze zdanie zmień na „Manifesty są w `deploy/base/{frontend,orders,fault-runner,intruder}`, konta usług i role zespołu (RBAC) w `deploy/base/rbac`, a NetworkPolicy w `deploy/base/networkpolicies`; tag obrazów budowanych w projekcie ustawia overlay.”. Zdanie o `make images` zostaje.
5. Zrzut `docs/img/hubble-intruder-orders-dropped.png` z działającego klastra. Skrót: `K="mise exec -- kubectl --context kind-secure-k8s-aiops"`.
   1. Wdróż Task 2 i 3: `make deploy`, potem `sleep 10`.
   2. Wywołaj odrzucenia: `$K -n intruder exec deploy/intruder -- sh -c 'for i in 1 2 3 4 5 6 7 8 9 10; do curl -s -m 2 -o /dev/null http://orders.shop.svc:8080/healthz; done'`. Kończy się po ok. 20 s kodem 28. Zrzut zrób w ciągu kilku minut, bo bufor Hubble jest krótki.
   3. W tle uruchom `mise exec -- cilium hubble ui --context kind-secure-k8s-aiops --open-browser=false` (to samo co `make hubble-ui`, ale bez otwierania przeglądarki) i poczekaj, aż port 12000 słucha.
   4. W przeglądarce narzędzia eval otwórz kartę z `url="http://localhost:12000/?namespace=intruder&verdicts=2"` i `viewport` 1400×900, poczekaj na tekst `orders`, potem jeszcze 4 s.
   5. Sprawdź, że:
      - przełącznik werdyktu pokazuje „Dropped”;
      - w tabeli są wiersze z Source Identity `intruder` (intruder), Destination Identity `orders` (shop), Destination Port `8080` i Verdict `dropped`;
      - nie ma wierszy `forwarded`.
   6. `tab.screenshot(format="png")` zwraca ścieżkę pliku PNG. Skopiuj ten plik do `docs/img/hubble-intruder-orders-dropped.png`, otwórz go (`read`) i potwierdź to samo na obrazie. W kadrze nie może być tokenów ani sekretów, a plik ma mieć mniej niż 500 KB (próba dała ok. 166 KB).
   7. Zamknij kartę i zatrzymaj proces `cilium hubble ui`.
6. `make lint` przechodzi (ruff sprawdza też Markdown).

## Critical files & anchors

- `deploy/base/fault-runner/deployment.yaml`: wzór Deploymentu intruder (securityContext poda i kontenera); etykieta `role: fault-runner` w `spec.template.metadata.labels`, której używa `orders-ingress`.
- `deploy/overlays/local/kustomization.yaml`: patch `imagePullPolicy` dla `containers/0` każdego Deploymentu obejmuje intruder; `images:` zawiera tylko obrazy budowane w projekcie i tak zostaje.
- `deploy/base/rbac/kustomization.yaml`: wzór kustomization bez pola `namespace` dla obiektów w kilku namespace'ach.
- `tests/security/test_rbac.py`: `DEPLOYED_WORKLOADS` (linie 30–35); styl helperów `kubectl()` i fixture `cluster`.
- `docs/architektura.md`: linie 19, 23 i 119–124 (sekcje „Komponenty i wersje” i „Przepływy sieciowe”).

## Verification

Korzeń repozytorium, gałąź `t12-networkpolicy` z Taskami 1–4, klaster `kind-secure-k8s-aiops`. Skrót: `K="mise exec -- kubectl --context kind-secure-k8s-aiops"`. `sleep 10` po każdej zmianie polityk daje Cilium czas na zastosowanie zmiany i wygasza połączenia keep-alive frontendu do orders (5 s).

1. Bez klastra:
   - `make lint && make unit && make manifests` → zielone; `manifests` daje `Valid: 38`;
   - `mise exec -- trivy config --skip-version-check --severity HIGH,CRITICAL --exit-code 1 deploy/` → kod 0.
2. Test wykrywa brak polityk:

   ```bash
   make deploy
   for ns in shop loadgen aiops; do $K -n $ns delete networkpolicy --all; done
   sleep 10
   mise exec -- uv run --locked pytest tests/security/test_network_policies.py -v
   ```

   - Oczekiwane `9 failed, 4 passed`.
   - Padają: `test_intruder_to_orders_is_denied`, `test_orders_to_frontend_is_denied`, trzy `test_egress_to_internet_is_denied[...]`, trzy `test_namespace_has_default_deny[...]` i `test_hubble_shows_policy_denied_intruder_to_orders`.
   - Przechodzą trzy `test_allowed_flow[...]` i `test_intruder_reaches_frontend`.
   - Bez internetu: `6 failed, 4 passed, 3 skipped`.
   - Jeśli któryś z 9 przechodzi, zatrzymaj się: test niczego nie dowodzi.
3. Polityki działają:

   ```bash
   make deploy && sleep 10
   $K get networkpolicy -A
   mise exec -- uv run --locked pytest tests/security -v
   ```

   - 13 polityk w shop, loadgen i aiops oraz `hubble-relay-ui-ingress` w kube-system.
   - `87 passed` (74 RBAC + 13 NetworkPolicy); bez internetu `84 passed, 3 skipped`.
   - `$K get pods -A -l app.kubernetes.io/part-of=secure-k8s-aiops` pokazuje 4 pody `1/1 Running`. Po 2 minutach `RESTARTS` się nie zmienia, czyli sondy kubeleta przechodzą.
4. Ścieżki spoza testu:
   - `curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8080/` → `200` (NodePort z hosta do frontendu);
   - `curl -s -o /dev/null -w '%{http_code}\n' -X POST http://localhost:8080/order -H 'Content-Type: application/json' -d '{"product_id": "kubek", "quantity": 1}'` → `201`;
   - `$K -n loadgen exec deploy/fault-runner -- fault-runner stop` → `{"stopped":null}`, kod 0 (fault-runner → orders `/faults/*` z tokenem).
5. Mutacje (każda kończy się przywróceniem):
   - Brak reguł allow do orders: `$K -n shop delete networkpolicy orders-ingress && sleep 10`, potem pytest jak w kroku 2.
     - Oczekiwane `2 failed, 11 passed`.
     - Padają `test_allowed_flow[frontend->orders]` (`'502' == '201'`) i `test_allowed_flow[fault-runner->orders]` (`error URLError(TimeoutError('timed out'))`).
     - Przywróć: `make deploy && sleep 10`.
   - Zbyt szeroka reguła:
     ```bash
     $K -n shop patch networkpolicy orders-ingress --type=json -p '[{"op":"add","path":"/spec/ingress/0/from/-","value":{"namespaceSelector":{}}}]' && sleep 10
     ```
     - Pytest jak w kroku 2 → `2 failed, 11 passed`.
     - Padają `test_intruder_to_orders_is_denied` i `test_hubble_shows_policy_denied_intruder_to_orders` (`('200', 0) == ('000', 28)`).
     - Przywróć: `$K -n shop delete networkpolicy orders-ingress && make deploy && sleep 10`, potem pytest → `13 passed`.
   - Bez internetu każda mutacja daje `2 failed, 8 passed, 3 skipped`.
6. Hubble CLI (sprawdzenie z issue):
   - `make hubble-relay` w osobnym terminalu albo jako proces w tle;
   - `$K -n intruder exec deploy/intruder -- curl -sS -m 3 -o /dev/null http://orders.shop.svc:8080/healthz` → `curl: (28) …`;
   - `mise exec -- hubble observe --verdict DROPPED --from-namespace intruder --last 5` → wiersze `intruder/intruder-…:<port> (ID:…) <> shop/orders-…:8080 (ID:…) Policy denied DROPPED (TCP Flags: SYN)`;
   - `mise exec -- hubble observe --verdict DROPPED --from-namespace intruder --last 1 -o json | jq -r .flow.drop_reason_desc` → `POLICY_DENIED`;
   - wynik zachowaj do komentarza w issue.
7. Od zera (definicja ukończenia):
   - `make down && make up` → kod 0, a rollout czeka też na `intruder`;
   - `mise exec -- uv run --locked pytest tests/security` → `87 passed`.
8. Zrzut:
   - `file docs/img/hubble-intruder-orders-dropped.png` → `PNG image data` (wymiary zależą od skali ekranu przeglądarki; próba dała 1750 x 1125);
   - `git ls-files docs/img` wypisuje plik;
   - obraz pokazuje odrzucone przepływy intruder → orders:8080.

## Po dostarczeniu (GitHub)

1. PR z gałęzi `t12-networkpolicy`, tytuł „T12 · NetworkPolicy: default-deny, dozwolone przepływy, test niedozwolonego połączenia”, w treści `Closes #12`.
   - Baza `main`, jeśli #51 jest scalony. W przeciwnym razie baza `t11-rbac`, a po scaleniu #51 `git fetch origin && git rebase --onto origin/main $(git merge-base t12-networkpolicy t11-rbac) t12-networkpolicy` (lokalne `t11-rbac`, bo zdalna gałąź może zniknąć po scaleniu), `git push --force-with-lease` i `gh pr edit <N> --base main`.
   - Opis podaje:
     - wynik „przed” (`9 failed, 4 passed`) i „po” (`87 passed`);
     - wyniki obu mutacji;
     - wiersze `hubble observe`;
     - zrzut.
2. Komentarz w #12: odhaczone kryteria z dowodem (pytest, `hubble observe`, link do `docs/img/hubble-intruder-orders-dropped.png`).
3. Komentarze w zadaniach zależnych (`gh issue comment <N> --repo l3x1cn/secure-k8s-aiops --body "<treść>"`):
   - #16: „T12: `orders-ingress` (shop) i `anomaly-detector-ingress` (aiops) wpuszczają na 8080 tylko pody z `app.kubernetes.io/name=prometheus` w monitoring (etykieta prometheus-operatora); frontend przyjmuje każde źródło. Po instalacji sprawdź `up == 1` dla targetów shop; inna etykieta Prometheusa wymaga zmiany `deploy/base/networkpolicies/{shop,aiops}.yaml`.”
   - #17: „T12: `anomaly-detector-egress` (aiops) dopuszcza Lokiego tylko z etykietą `app.kubernetes.io/name=loki` w monitoring, port 3100 (domyślna etykieta chartu Loki).”
   - #18: „T12: loadgen ma default-deny. Deployment locust musi mieć etykietę `app.kubernetes.io/name: locust`; polityka `locust-egress` dopuszcza tylko shop/frontend:8080 i DNS. Locust master/worker albo inny cel ruchu wymaga reguł w `deploy/base/networkpolicies/loadgen.yaml`.”
   - #24: „T12: aiops ma default-deny. Pod anomaly-detector (`app.kubernetes.io/name: anomaly-detector`, port 8080) przyjmuje ruch tylko od Prometheusa, a wysyła do Prometheusa :9090, Lokiego :3100 i DNS (`deploy/base/networkpolicies/aiops.yaml`).”

## Assumptions & contingencies

Założenia (właściciel może je zmienić):
- Polityki dla locust, anomaly-detector, Prometheusa i Lokiego powstają w T12 według tablicy z architektury, choć tych podów jeszcze nie ma. Etykiety pochodzą z konwencji projektu i ze źródeł prometheus-operatora i chartu Loki. Alternatywa: zostawić je T16, T17, T18 i T24.
- Namespace intruder nie ma polityk; zakres issue wymienia default-deny tylko w shop, loadgen i aiops.
- Test ma dwa przypadki ponad macierz issue: intruder → frontend i obiekt default-deny w każdym z trzech namespace'ów.
- frontend → orders sprawdza `POST /order` wysłany do frontendu przez loopback z wnętrza poda frontend.
- Przypadki z internetem są pomijane, gdy klaster nie ma wyjścia do 1.1.1.1:443. T03 dopuszczało pominięcie testów wymagających internetu.
- Pin obrazu intruder jest w manifeście, nie w `platform/versions.env`. versions.env obejmuje to, co czyta Makefile, jak w T04; zdanie w architekturze zmienia Task 4.
- Gdy #51 nie jest scalony, T12 powstaje na gałęzi `t11-rbac` (stacked).

Plan awaryjny:
- **Pod intruder w `ErrImagePull` albo `ImagePullBackOff`:** sprawdź `docker pull docker.io/curlimages/curl:8.23.0@sha256:3fb7e13e5d179a845c97d78204f3f1064d1907037f26a3ebf91710571151fd93` na hoście. Docker Hub nieosiągalny albo limit pobrań: zatrzymaj się i zgłoś. Nie zmieniaj obrazu ani rejestru.
- **Dozwolony przypadek pada po wdrożeniu polityk:** uruchom `mise exec -- hubble observe --verdict DROPPED --namespace shop --last 20` przy `make hubble-relay`.
  - `EGRESS` z frontend oznacza `frontend-egress` albo `allow-dns`;
  - `INGRESS` do orders oznacza peer w `orders-ingress`.
  Popraw regułę allow według tablicy. Nie usuwaj ani nie luzuj `default-deny`.
- **Sonda zwraca `error gaierror(...)` (DNS):** `$K -n kube-system get pods -l k8s-app=kube-dns` powinno pokazać 2 pody. Inny wynik: zatrzymaj się i zgłoś etykiety CoreDNS.
- **Pody tracą gotowość albo restartują po politykach:** zatrzymaj się i zgłoś `describe pod` oraz `hubble observe --verdict DROPPED --namespace <ns> --last 20`. Nie dopisuj reguł dla węzłów ani `ipBlock`.
- **`localhost:8080` przestaje odpowiadać:** `frontend-ingress` nie może mieć `from`; popraw tylko to.
- **Odrzucany przypadek daje `error …` albo kod curl inny niż 28:** cel nie działa (`$K -n shop get endpoints`). Napraw środowisko, nie osłabiaj asercji.
- **Test Hubble nie widzi przepływu przez 15 s:** z port-forwardem `make hubble-relay` sprawdź `mise exec -- hubble status`, który powinien pokazać `Connected Nodes: 3/3`, i `hubble observe --from-namespace intruder --last 20`. Gdy relay jest zdrowy, a przepływu nie ma, zatrzymaj się i zgłoś wynik.
- **Krok 2 Verification daje inne liczby niż `9 failed, 4 passed` (z internetem):** porównaj linie `FAILED` z listą. Przypadek, który przechodzi bez polityk, to błąd testu: popraw go w Task 1 i powtórz kroki 2–3.
- **Trivy zgłasza HIGH albo CRITICAL w nowym pliku:** popraw według komunikatu bez osłabiania `securityContext`. KSV-0110 i KSV-0125 to znane uwagi LOW i MEDIUM.
- **Przeglądarka niedostępna w agencie Task 4:** zgłoś to; zrzut wykona główny agent według kroku 5 Task 4 i doda go commitem Task 4.
- **Port 8080 albo 12000 zajęty:** zwolnij go i powtórz. Nie zmieniaj mapowań kind ani portu Hubble UI w dokumentacji.
