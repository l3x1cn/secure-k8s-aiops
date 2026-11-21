# T26 · Pakiet testów bezpieczeństwa i test mutacyjny polityk (issue #26)

## Context

Issue #26 (T26, R2 Bezpieczeństwo, Sprint 3; zależności T11–T14 są scalone). Cel: jedna komenda dowodzi wymogów bezpieczeństwa, a testy naprawdę wykrywają regresję. Zakres z issue:
- `make test-security`: testy z T11–T14 (marker `security`), wyniki w `reports/junit-security.xml` i `reports/security.html` (pytest-html);
- `tests/security/mutation_check.sh`: usuwa `default-deny` w shop, uruchamia testy sieciowe (oczekiwany błąd), przywraca politykę.

Kryteria akceptacji:
1. Na świeżym klastrze `make test-security` przechodzi.
2. Test mutacyjny pokazuje, że bez default-deny testy odmowy połączenia nie przechodzą.

Komentarz w #26 (T14): `tests/security/test_secrets.py` (marker `security`) nie wymaga klastra, potrzebuje `kustomize` w PATH (cel make ma go z `mise bin-paths`) i uruchamia `make gitleaks`.

Decyzje właściciela (2026-11-21, odpowiedzi w planowaniu):
1. Dziś usunięcie `shop/default-deny` nie łamie żadnego testu połączenia (fakty niżej). Dlatego dochodzi test z tymczasowym podem bez własnej reguły, parametryzowany po shop, loadgen i aiops (`DEFAULT_DENY_NAMESPACES`).
2. Test mutacyjny uruchamia się tylko skryptem `bash tests/security/mutation_check.sh`, bez celu make. `make test-security` nie zmienia klastra.

Stan docelowy:
- `make test-security` uruchamia `pytest -m security tests` z JUnit i HTML w `reports/`; na klastrze 104 testy;
- `pytest-html` w grupie `dev`, `--strict-markers` w `addopts`;
- `tests/security/test_network_policies.py` ma fixture `unlisted_pod` i test `test_intruder_to_unlisted_pod_is_denied[shop|loadgen|aiops]` (19 testów w module);
- `tests/security/mutation_check.sh` usuwa `shop/default-deny` i wymaga porażki dokładnie dwóch testów, potem przywraca politykę i wymaga zielonego przebiegu;
- README, `docs/architektura.md` i macierz w `docs/bezpieczenstwo.md` opisują cel, nowy test i test mutacyjny; wiersz mutacji ma stan „działa”.

### Ustalone fakty (sprawdzone 2026-11-21)

- **Repozytorium:**
  - lokalnie gałąź `t15-trivy` (= `origin/t15-trivy`), drzewo czyste; `origin/main` = `fb2b883`, `t15-trivy` ma 11 commitów ponad nim;
  - PR #61 (T15) jest `OPEN`, `REVIEW_REQUIRED`, `MERGEABLE`. T15 zmienia linię `.PHONY` w `Makefile` i wiersz W3 (`docs/bezpieczenstwo.md:73`), który sąsiaduje z wierszem W4 (`:74`) zmienianym w T26. Gałąź z `main` dałaby więc konflikt przy scaleniu drugiego PR;
  - numery linii w planie pochodzą z `t15-trivy`.
- **Testy z markerem `security`:** `pytest -m security tests --collect-only` → `101/113 tests collected (12 deselected)`; odznaczone to `tests/observability` (`pytestmark = pytest.mark.observability`). `test_network_policies.py` ma 16 testów, `make unit` zbiera 96. Moduły nie mają `conftest.py`. Markery w repo to `parametrize`, `usefixtures`, `security`, `observability`; z `--strict-markers` zbieranie daje te same liczby.
- **Polityki w shop (w klastrze tak samo jak w repo):** `default-deny`, `allow-dns` (`podSelector: {}`, tylko Egress), `frontend-ingress`, `frontend-egress`, `orders-ingress`. `kubectl get networkpolicy -A` → 14 polityk: aiops 4, kube-system 1 (`hubble-relay-ui-ingress`), loadgen 4, shop 5.
- **Mutacja z issue dziś nie łamie żadnego testu połączenia.** Bez `shop/default-deny`:
  - orders dalej izoluje `orders-ingress`, a frontend `frontend-ingress` (`docs/architektura.md:154`: „ruch do orders odrzuca polityka `orders-ingress`”);
  - egress każdego poda w shop dalej izoluje `allow-dns` (`docs/plans/2026-11-09-t12-networkpolicy.md:106`);
  - pada tylko `test_namespace_has_default_deny[shop]`, który sprawdza obiekt w API, a nie połączenie.
  default-deny w shop chroni tylko pod bez własnej reguły ingress, a takiego poda dziś w shop nie ma.
- **Pod próbny bez reguły (prototyp bez zmian w klastrze):**
  - `kubectl create --dry-run=server` poda `t26-unlisted` z manifestem z Task 2 przechodzi PSA `restricted` w shop, loadgen i aiops;
  - obrazy `frontend:dev`, `orders:dev` i `fault-runner:dev` są w containerd wszystkich trzech węzłów (`crictl images`); Deploymenty mają `imagePullPolicy: IfNotPresent`, a `shop/orders` ma obraz `ghcr.io/l3x1cn/secure-k8s-aiops/orders:dev`;
  - w obrazie orders `python` to `/app/.venv/bin/python` 3.13.16 z `http.server`; katalog roboczy `/`, `id` → `uid=10001 gid=10001`;
  - Cilium wpuszcza ruch z węzła do poda mimo polityk (`docs/architektura.md:154`), więc `readinessProbe` `tcpSocket` działa pod default-deny;
  - reguła `service:policy_drops:rate1m` liczy tylko `destination_workload=~"frontend|orders"` w shop (`deploy/observability/recording-rules.yaml:117-137`), więc odrzucenia do poda próbnego nie zmieniają alertu `PolicyDeniedConnections` ani cech ML.
- **Przywracanie polityki:** `kustomize build deploy/overlays/local` daje trzy obiekty `default-deny` identyczne z `deploy/base/networkpolicies/default-deny.yaml` (porównanie YAML), bo overlay łata tylko Deploymenty i Service'y.
- **pytest-html:** nie ma go w `uv.lock`. Najnowsza wersja 4.2.0 (PyPI, 2026-01-19) wymaga `pytest>=7`, `jinja2>=3` i `pytest-metadata>=2` (najnowsze 3.1.1). W `uv.lock` są `pytest` 9.2.0, `jinja2` 3.1.6 i `markupsafe` 3.0.4. Zgodność 4.2.0 z pytest 9.2.0 nie jest sprawdzona; potwierdza ją Task 1.
- **Podsumowanie `-rfE` w pytest 9.2.0** (próba na pliku poza repo): linie `FAILED <nodeid> - <komunikat>` i `ERROR <nodeid> - <komunikat>`; dalsze linie komunikatu nie zaczynają się od tych słów; kod wyjścia 1 przy porażkach i błędach.
- **Makefile:** `KUBE_CONTEXT := kind-$(CLUSTER_NAME)` (linia 14) nadpisuje zmienną środowiska. `PATH` (linia 8) bierze z `mise bin-paths` kubectl, kustomize, hubble, gitleaks i uv. `MAKEFLAGS += --no-print-directory`, więc `make gitleaks` z testu pod `make test-security` działa jak w T14.
- **CI:** job `secrets` robi checkout z `fetch-depth: 0` (`.github/workflows/ci.yml:63`); klastra w CI nie ma do T28.
- **Narzędzia:** `shellcheck` 0.11.0 jest w mise globalnie (poza `mise.toml`): `mise exec shellcheck@0.11.0 -- shellcheck`. Prototyp skryptu z Task 4 przechodzi `bash -n` i shellcheck bez uwag. Łata z Task 2 przechodzi `git apply --check`, `ruff format --diff` (bez zmian) i `ruff check` z konfiguracją repo.
- **Konwencje repo:**
  - `reports/` jest w `.gitignore`; stare wyniki usuwa się przed nowym przebiegiem (`scripts/trivy.sh:85-86`);
  - skrypt uruchamiany poza make sam dokłada `mise bin-paths` do PATH (`scripts/trivy.sh:21-23`); skrypty w `scripts/` mają tryb `100755`;
  - obiekty próbne testów mają prefiks zadania (`t13-privileged`, `t11-developer`);
  - `docs/bezpieczenstwo.md:124`: wiersz ze stanem „Tnn” zmienia się na „działa” w PR, który dodaje test;
  - gałąź `txx-krotki-opis`, PR z `Closes #N`; plan trafia do `docs/plans/<data>-<slug>.md` commitem „docs: add delivery plan <slug>”.

## Warunek wstępny (główny agent, przed startem delivery)

W korzeniu repozytorium:

```bash
git status --short   # pusto
gh pr view 61 --repo l3x1cn/secure-k8s-aiops --json state --jq .state
```

- `MERGED` albo `CLOSED` → `git switch main && git pull --ff-only && git switch -c t26-testy-bezpieczenstwa`.
- `OPEN` → `git switch t15-trivy && git pull --ff-only && git switch -c t26-testy-bezpieczenstwa`. Gałąź stoi wtedy na T15 (stacked).

Potem:
- `kind get clusters` wypisuje `secure-k8s-aiops`, a `mise exec -- kubectl --context kind-secure-k8s-aiops get --raw /readyz` daje `ok`. Inaczej `make up`.
- `make deploy`: manifesty klastra są takie jak na gałęzi; T26 nie zmienia `deploy/`.
- Task 1 potrzebuje sieci (PyPI).

Ten plan trafia do `docs/plans/2026-11-21-t26-testy-bezpieczenstwa.md` commitem `docs: add delivery plan t26-testy-bezpieczenstwa`.

Jeśli baza ma nowsze commity w `Makefile`, `pyproject.toml`, `uv.lock`, `tests/security/test_network_policies.py`, `README.md`, `docs/architektura.md` albo `docs/bezpieczenstwo.md`, przeczytaj te pliki ponownie i przenieś zmiany planu na nowe numery linii. Treść zmian się nie zmienia. Edycje są opisane treścią, nie samymi numerami, więc pasują też do bazy bez T15 (wtedy `.PHONY` nie ma `trivy-config`).

## Approach

Task 1 i 2 to stos Python, Taski 3–5 to stos „pozostałe” (Makefile, bash, Markdown). Kolejność 1 → 2 → 3 → 4 → 5:
- Task 3 wymaga pytest-html z Task 1;
- Task 4 wymaga testu z Task 2, bo jego identyfikator jest na liście oczekiwanych porażek;
- Task 5 opisuje nazwy z Tasków 1–4.

Decyzje wspólne:
- `make test-security` wybiera testy markerem (`pytest -m security tests`), więc obejmuje każdy test z markerem w `tests/`, także przyszły spoza `tests/security`. `--strict-markers` zmienia literówkę w markerze w błąd zbierania. Bez tego test byłby po cichu pominięty przez `-m security` (przegląd T11, CQ-005, odłożył to do T26).
- Pod próbny to goły Pod tworzony przez fixture na czas jednego testu. Nie ma etykiety `app.kubernetes.io/part-of`, więc nie obejmują go `test_own_containers_are_hardened`, `test_own_pods_have_no_service_account_token` ani rollout w `make deploy`. Etykieta `app.kubernetes.io/name: t26-unlisted` nie pasuje do żadnego selektora w `deploy/base/networkpolicies/`, więc pod wybierają tylko `default-deny` i `allow-dns`.
- Mutacja obejmuje tylko `shop/default-deny` (zakres issue). Zbiór oczekiwanych porażek jest dokładny: `test_intruder_to_unlisted_pod_is_denied[shop]` i `test_namespace_has_default_deny[shop]`. Każda inna porażka albo błąd to wynik nieoczekiwany (kod 1).
- Politykę przywraca `kubectl apply -f deploy/base/networkpolicies/default-deny.yaml`, a nie `make deploy`: skrypt testowy nie wdraża reszty drzewa roboczego, a obiekt jest identyczny z wynikiem overlayu.
- Bez zmian: CI, `mise.toml`, `deploy/`, `scripts/`, pozostałe moduły `tests/`.

### Task 1: pytest-html i --strict-markers
**Commit:** build(deps): pytest-html w grupie dev i --strict-markers dla wyboru markerem (T26)

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`

1. `pyproject.toml`, `[dependency-groups]` → `dev`: po linii `    "pytest>=9.1.1",` wstaw `    "pytest-html>=4.2.0",`.
2. `pyproject.toml`, `[tool.pytest.ini_options]`: linie 44–47

```toml
# Usługi mają osobne katalogi tests/ z plikami o tych samych nazwach.
addopts = ["--import-mode=importlib"]
# Testy na klastrze: bezpieczeństwa (tests/security, T11–T14; `-m security`, make test-security w T26)
# i obserwowalności (tests/observability, T16, T27; `-m observability`).
```

   zastąp:

```toml
# Usługi mają osobne katalogi tests/ z plikami o tych samych nazwach (--import-mode=importlib).
# --strict-markers: literówka w markerze to błąd zbierania, a nie test po cichu pominięty przez `-m security`.
addopts = ["--import-mode=importlib", "--strict-markers"]
# Testy na klastrze: bezpieczeństwa (tests/security, T11–T14, T26; `make test-security` wybiera je `-m security`)
# i obserwowalności (tests/observability, T16, T27; `-m observability`).
```

   Linie 41–42 i `markers` się nie zmieniają.
3. `mise exec -- uv lock`, potem `mise exec -- uv sync`. `git diff uv.lock` dodaje tylko pakiety `pytest-html` (4.2.0 albo nowszy) i `pytest-metadata` (3.1.1 albo nowszy) oraz wpis `pytest-html` w grupie `dev` korzenia (`[package.dev-dependencies]` i `[package.metadata.requires-dev]`). Żaden inny pakiet nie zmienia wersji.
4. Sprawdzenie:
   - `mise exec -- uv lock --check` → kod 0;
   - `make unit` → `96 passed`;
   - `mise exec -- uv run --locked pytest -m security tests --collect-only -q | tail -n 1` → `101/113 tests collected (12 deselected) …`;
   - pytest-html z pytest 9.2.0, bez klastra:

```bash
mise exec -- uv run --locked pytest tests/security/test_secrets.py --html=reports/t26-html-probe.html --self-contained-html
grep -c test_history_has_no_leaks reports/t26-html-probe.html   # co najmniej 1
rm reports/t26-html-probe.html
```

     Oczekiwane `3 passed` i linia `Generated html report: file://…/reports/t26-html-probe.html`.

### Task 2: Pod bez własnej reguły nie przyjmuje połączeń
**Commit:** test(security): pod bez własnej reguły w shop, loadgen i aiops nie przyjmuje połączeń (T26)

**Files:**
- Test: `tests/security/test_network_policies.py`

1. Zastosuj łatę poniżej (`git apply` albo ręcznie; wynik musi być identyczny). Jest sformatowana ruffem 0.17.3; nie zmieniaj formatowania. Decyzje zawarte w łacie:
   - `kubectl()` dostaje parametr `stdin`, jak `kubectl()` w `tests/security/test_pod_security.py:33-46`. Dotychczasowe wywołania się nie zmieniają.
   - Obraz poda pochodzi z działającego `shop/orders`, a nie ze stałej. Overlay ustawia tag, a `make images` ładuje obraz do każdego węzła.
   - Serwer to `python -m http.server 8080 --bind 0.0.0.0`; `GET /` zwraca 200. `--bind 0.0.0.0`, bo domyślnie serwer może wybrać IPv6 `::`.
   - `readinessProbe` `tcpSocket`: `Ready` znaczy, że serwer słucha, więc przekroczenie czasu wynika z polityki, a nie z braku serwera.
   - securityContext jak w kontrakcie T13 (PSA restricted), `automountServiceAccountToken: false`, `restartPolicy: Never`. `terminationGracePeriodSeconds: 1`, bo Python jako PID 1 ignoruje SIGTERM; ten sam problem opisuje komentarz w `deploy/base/intruder/deployment.yaml:37-38`.
   - Fixture najpierw usuwa pozostałość po przerwanym przebiegu, a w `finally` usuwa pod. `--timeout=45s` mieści się w 60-sekundowym limicie `subprocess.run` w `kubectl()`.
   - Asercja `("000", 28)` (przekroczenie czasu curl), jak w `test_intruder_to_orders_is_denied`. Bez default-deny pod odpowiada `("200", 0)`.
   - Kontrakt dla Task 4: identyfikatory `tests/security/test_network_policies.py::test_intruder_to_unlisted_pod_is_denied[shop]` i `tests/security/test_network_policies.py::test_namespace_has_default_deny[shop]`.

```diff
--- a/tests/security/test_network_policies.py
+++ b/tests/security/test_network_policies.py
@@ -3,6 +3,9 @@
 # Sondy uruchamia `kubectl exec` w podzie źródłowym: python w frontend, orders, fault-runner i locust,
 # curl w intruder. Cilium porzuca odrzucony pakiet SYN bez odpowiedzi, więc odrzucenie to
 # przekroczenie czasu sondy (5 s); odmowa połączenia znaczy, że cel nie działa.
+# Skutek default-deny (T26) sprawdza pod t26-unlisted bez własnej reguły, tworzony na czas
+# testu w shop, loadgen i aiops; tests/security/mutation_check.sh usuwa shop/default-deny
+# i wymaga, żeby ten test padł.
 # Uruchomienie: uv run --locked pytest tests/security/test_network_policies.py
 # (kubectl i hubble z mise.toml w PATH). Kontekst: zmienna KUBE_CONTEXT, domyślnie
 # kind-secure-k8s-aiops, jak w Makefile.
@@ -28,6 +31,9 @@
 LOCUST = ("loadgen", "locust")
 INTRUDER = ("intruder", "intruder")
 DEFAULT_DENY_NAMESPACES = ["shop", "loadgen", "aiops"]
+# Etykieta spoza tablicy etykiet w architekturze, więc pod wybierają tylko default-deny
+# i allow-dns; nie ma app.kubernetes.io/part-of, więc testy własnych podów go pomijają.
+UNLISTED_POD = "t26-unlisted"
 
 ORDERS_URL = "http://orders.shop.svc:8080"
 FRONTEND_URL = "http://frontend.shop.svc:8080"
@@ -106,9 +112,12 @@
 ]
 
 
-def kubectl(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
+def kubectl(
+    *args: str, stdin: str | None = None, check: bool = True
+) -> subprocess.CompletedProcess[str]:
     result = subprocess.run(
         ["kubectl", "--context", KUBE_CONTEXT, *args],
+        input=stdin,
         capture_output=True,
         text=True,
         timeout=60,
@@ -164,6 +173,60 @@
     return fields[0], int(fields[1])
 
 
+def unlisted_pod_manifest(namespace: str, image: str) -> str:
+    # securityContext z kontraktu T13, więc PSA restricted przyjmuje pod. Python jako PID 1
+    # ignoruje SIGTERM, więc terminationGracePeriodSeconds 1 skraca usuwanie poda.
+    return json.dumps(
+        {
+            "apiVersion": "v1",
+            "kind": "Pod",
+            "metadata": {
+                "name": UNLISTED_POD,
+                "namespace": namespace,
+                "labels": {"app.kubernetes.io/name": UNLISTED_POD},
+            },
+            "spec": {
+                "automountServiceAccountToken": False,
+                "restartPolicy": "Never",
+                "terminationGracePeriodSeconds": 1,
+                "securityContext": {
+                    "runAsNonRoot": True,
+                    "runAsUser": 10001,
+                    "runAsGroup": 10001,
+                    "seccompProfile": {"type": "RuntimeDefault"},
+                },
+                "containers": [
+                    {
+                        "name": "http",
+                        "image": image,
+                        "imagePullPolicy": "IfNotPresent",
+                        "command": [
+                            "python",
+                            "-m",
+                            "http.server",
+                            "8080",
+                            "--bind",
+                            "0.0.0.0",
+                        ],
+                        "ports": [{"name": "http", "containerPort": 8080}],
+                        # Sonda kubeleta przechodzi mimo default-deny (allow-localhost
+                        # w Cilium), więc Ready znaczy, że serwer już słucha.
+                        "readinessProbe": {
+                            "tcpSocket": {"port": 8080},
+                            "periodSeconds": 1,
+                        },
+                        "securityContext": {
+                            "allowPrivilegeEscalation": False,
+                            "readOnlyRootFilesystem": True,
+                            "capabilities": {"drop": ["ALL"]},
+                        },
+                    }
+                ],
+            },
+        }
+    )
+
+
 def hubble_drops(server: str, from_namespace: str, to_namespace: str) -> list[dict]:
     """Odrzucone przepływy z ostatniej minuty (pole `flow` z `hubble observe -o json`)."""
     result = subprocess.run(
@@ -256,6 +319,30 @@
         forward.wait(timeout=10)
 
 
+@pytest.fixture
+def unlisted_pod(request: pytest.FixtureRequest) -> Iterator[str]:
+    """IP poda UNLISTED_POD w namespace'ie request.param; po teście pod znika."""
+    target = ["-n", request.param, f"pod/{UNLISTED_POD}"]
+    # Obraz projektu z działającego Deploymentu: jest w każdym węźle (make images).
+    image = kubectl(
+        "get",
+        "deployment",
+        "orders",
+        "-n",
+        "shop",
+        "-o",
+        "jsonpath={.spec.template.spec.containers[0].image}",
+    ).stdout
+    # Pozostałość po przerwanym przebiegu.
+    kubectl("delete", *target, "--ignore-not-found", "--timeout=45s")
+    kubectl("create", "-f", "-", stdin=unlisted_pod_manifest(request.param, image))
+    try:
+        kubectl("wait", *target, "--for=condition=Ready", "--timeout=45s")
+        yield kubectl("get", *target, "-o", "jsonpath={.status.podIP}").stdout
+    finally:
+        kubectl("delete", *target, "--ignore-not-found", "--timeout=45s")
+
+
 @pytest.mark.parametrize(("source", "method", "url", "body", "expected"), ALLOWED)
 def test_allowed_flow(source, method, url, body, expected):
     assert http_status(source, method, url, body) == expected
@@ -287,8 +374,8 @@
 
 @pytest.mark.parametrize("namespace", DEFAULT_DENY_NAMESPACES)
 def test_namespace_has_default_deny(namespace):
-    # Jedyny dowód dla aiops, który do T24 nie ma podów; w shop i loadgen chroni
-    # pody bez własnej reguły (fault-runner nie ma polityki ingress).
+    # Obiekt polityki. Jej skutek dla poda bez własnej reguły (w loadgen taki jest
+    # fault-runner bez polityki ingress) sprawdza test_intruder_to_unlisted_pod_is_denied.
     result = kubectl("get", "networkpolicies", "-n", namespace, "-o", "json")
     deny_all = [
         policy["metadata"]["name"]
@@ -301,6 +388,13 @@
     assert deny_all, f"{namespace}: brak NetworkPolicy odcinającej cały ruch podów"
 
 
+@pytest.mark.parametrize("unlisted_pod", DEFAULT_DENY_NAMESPACES, indirect=True)
+def test_intruder_to_unlisted_pod_is_denied(unlisted_pod):
+    # Pod bez własnej reguły ingress odcina tylko default-deny: bez tej polityki
+    # serwer HTTP poda odpowiada intruderowi ("200", 0).
+    assert intruder_curl(f"http://{unlisted_pod}:8080/") == ("000", 28)
+
+
 def test_hubble_shows_policy_denied_intruder_to_orders(hubble_server):
     # Świeży przepływ: `--since 1m` w hubble_drops pomija wpisy z wcześniejszych przebiegów.
     assert intruder_curl(f"{ORDERS_URL}/healthz") == ("000", 28)
```

2. Sprawdzenie:
   - `make lint` → zielone;
   - `mise exec -- uv run --locked pytest tests/security/test_network_policies.py --collect-only -q` → 19 testów, w tym `test_intruder_to_unlisted_pod_is_denied[shop]`, `[loadgen]` i `[aiops]`;
   - na klastrze: `mise exec -- uv run --locked pytest tests/security/test_network_policies.py -v -k unlisted` → `3 passed`, potem `mise exec -- kubectl --context kind-secure-k8s-aiops get pods -A -l app.kubernetes.io/name=t26-unlisted` → `No resources found`.

### Task 3: Cel make test-security
**Commit:** feat(make): make test-security z raportami JUnit i HTML w reports/ (T26)

**Files:**
- Modify: `Makefile`

1. Linia 24 (`.PHONY`): wstaw `test-security` między `deploy` a `status`. Reszta linii bez zmian.
2. Wstaw poniższy blok po celu `deploy`, czyli po linii 132 (`	done`) i pustej linii za nią, przed komentarzem `# Stan platformy: węzły, release'y Helm i pody we wszystkich namespace'ach.`. Za blokiem zostaw jedną pustą linię. Linie poleceń zaczynają się tabulatorem, kontynuacja dwoma.

```make
# Testy bezpieczeństwa (T26) na klastrze z make up: każdy test z markerem security w tests/ (RBAC T11,
# NetworkPolicy T12 i T26, Pod Security T13, sekrety T14; test_secrets.py działa też bez klastra), z tym samym
# kontekstem kubectl co pozostałe cele. Wyniki: reports/junit-security.xml i reports/security.html (pytest-html,
# jeden plik ze stylami); stare wyniki znikają przed przebiegiem. Test mutacyjny jest osobno: bash tests/security/mutation_check.sh.
test-security:
	@mkdir -p reports && rm -f reports/junit-security.xml reports/security.html
	KUBE_CONTEXT='$(KUBE_CONTEXT)' uv run --locked pytest -m security tests \
		--junitxml=reports/junit-security.xml --html=reports/security.html --self-contained-html
```

3. Sprawdzenie: `make -n test-security` wypisuje `mkdir -p reports && rm -f reports/junit-security.xml reports/security.html` i polecenie pytest zaczynające się od `KUBE_CONTEXT='kind-secure-k8s-aiops' uv run --locked pytest -m security tests \`. Przebieg na klastrze sprawdza krok 2 Verification.

### Task 4: Skrypt testu mutacyjnego
**Commit:** test(security): test mutacyjny bez shop/default-deny w tests/security/mutation_check.sh (T26)

**Files:**
- Create: `tests/security/mutation_check.sh`

1. Utwórz `tests/security/mutation_check.sh` z treścią poniżej (wcięcia tabulatorem, jak `scripts/trivy.sh`) i nadaj mu tryb wykonywalny (`chmod +x`; w git `100755`, jak skrypty w `scripts/`). Decyzje zawarte w treści:
   - Kolejność: sprawdzenie, że `shop/default-deny` istnieje, potem usunięcie, `sleep 10`, przebieg z oczekiwanymi porażkami, przywrócenie, `sleep 10` i przebieg, który musi być zielony.
   - Wynik ocenia kod pytest i zbiór identyfikatorów z linii `FAILED`/`ERROR` podsumowania `-rfE`:
     - kod 0 → „mutacja przeżyła”;
     - kod różny od 1 albo inny zbiór niż `EXPECTED_FAILED` → „nieoczekiwany wynik”.
   - `mutated=true` ustawia się przed `kubectl delete`, więc pułapka `EXIT` przywraca politykę także po błędzie i przerwaniu w trakcie usuwania. `INT` i `TERM` kończą skrypt kodami 130 i 143 przez tę samą pułapkę.
   - `KUBE_CONTEXT` ma ten sam domyślny kontekst co Makefile. Skrypt eksportuje go, więc kubectl i pytest działają na tym samym klastrze.
   - Logi: `reports/mutation-check/mutated.txt` i `reports/mutation-check/restored.txt`; stare są usuwane przed przebiegiem.

```bash
#!/usr/bin/env bash
# Test mutacyjny NetworkPolicy (T26): bez polityki default-deny w shop musi paść test odmowy połączenia.
# Skrypt usuwa shop/default-deny, uruchamia tests/security/test_network_policies.py i wymaga, żeby padły
# dokładnie testy z EXPECTED_FAILED, a pozostałe przeszły. Potem przywraca politykę i wymaga zielonego przebiegu.
# Bez default-deny testy odmowy do frontend i orders nadal przechodzą: oba pody mają własne polityki ingress,
# a allow-dns izoluje egress każdego poda w shop. default-deny odcina pod bez własnej reguły, więc pada test
# z podem t26-unlisted i sprawdzenie samego obiektu polityki.
# Politykę przywraca kubectl apply pliku z deploy/base, także po błędzie i po Ctrl+C (pułapka EXIT). Overlay
# local nie zmienia NetworkPolicy, więc obiekt jest taki sam jak po make deploy.
# Logi obu przebiegów: reports/mutation-check/mutated.txt i reports/mutation-check/restored.txt.
# Kod 0: mutacja wykryta i polityka przywrócona; 1: mutacja przeżyła, inny wynik testów albo błąd;
# 130 i 143: przerwanie (Ctrl+C, SIGTERM), polityka przywrócona.
# Użycie: bash tests/security/mutation_check.sh (klaster z make up, ok. 3–4 min). Kontekst: zmienna
# KUBE_CONTEXT, domyślnie kind-secure-k8s-aiops, jak w Makefile i w testach.
# Zgodny z bash 3.2 (macOS).
set -euo pipefail

cd "$(dirname "$0")/../.."

# kubectl, hubble i uv w wersjach z mise.toml mają pierwszeństwo przed systemowymi, także bez make
# i bez aktywacji mise w powłoce (jak scripts/trivy.sh).
PATH="$(mise bin-paths 2>/dev/null | tr '\n' ':' || true)$PATH"

export KUBE_CONTEXT="${KUBE_CONTEXT:-kind-secure-k8s-aiops}"
POLICY=deploy/base/networkpolicies/default-deny.yaml
TESTS=tests/security/test_network_policies.py
# Identyfikatory z podsumowania pytest (-rfE), jeden w linii.
EXPECTED_FAILED="$TESTS::test_intruder_to_unlisted_pod_is_denied[shop]
$TESTS::test_namespace_has_default_deny[shop]"
# Cilium potrzebuje chwili na zmianę polityk (jak sleep 10 w weryfikacji T12).
SETTLE_SECONDS=10
out=reports/mutation-check

for tool in kubectl uv; do
	if ! command -v "$tool" >/dev/null; then
		echo "Brak $tool w PATH: zainstaluj narzędzia z mise.toml (mise install)." >&2
		exit 1
	fi
done

k() { kubectl --context "$KUBE_CONTEXT" "$@"; }

# Testy sieci z logiem w pliku $1; kod wyjścia to kod pytest (0: zielone, 1: porażki, inny: błąd przebiegu).
run_tests() {
	local status=0
	uv run --locked pytest "$TESTS" -q -rfE --color=no 2>&1 | tee "$1" || status=$?
	return "$status"
}

# Posortowane identyfikatory testów z porażką (FAILED) albo błędem (ERROR) z logu $1.
failed_ids() {
	grep -E '^(FAILED|ERROR) ' "$1" | cut -d ' ' -f 2 | LC_ALL=C sort -u || true
}

mutated=false
# Błąd kubectl kończy funkcję kodem 1 jawnie, bo w warunku `if ! restore` (on_exit) set -e nie działa.
restore() {
	[ "$mutated" = true ] || return 0
	echo "== Przywracam shop/default-deny: kubectl apply -f $POLICY"
	k apply -f "$POLICY" || return 1
	mutated=false
	sleep "$SETTLE_SECONDS"
}

on_exit() {
	local status=$?
	if ! restore; then
		echo "Polityka shop/default-deny NIE wróciła. Przywróć ją: kubectl --context $KUBE_CONTEXT apply -f $POLICY" >&2
		status=1
	fi
	exit "$status"
}
trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if ! k -n shop get networkpolicy default-deny >/dev/null; then
	echo "Brak polityki shop/default-deny albo klastra $KUBE_CONTEXT: najpierw make up (albo make deploy)." >&2
	exit 1
fi
mkdir -p "$out"
# Stary log z poprzedniego uruchomienia nie może udawać nowego.
rm -f "$out/mutated.txt" "$out/restored.txt"

echo "== Mutacja: usuwam shop/default-deny"
mutated=true
k -n shop delete networkpolicy default-deny
sleep "$SETTLE_SECONDS"

echo "== Testy bez shop/default-deny; muszą paść dokładnie:"
echo "$EXPECTED_FAILED"
status=0
run_tests "$out/mutated.txt" || status=$?
failed=$(failed_ids "$out/mutated.txt")
expected=$(echo "$EXPECTED_FAILED" | LC_ALL=C sort -u)
if [ "$status" -eq 0 ]; then
	echo "Mutacja przeżyła: bez shop/default-deny wszystkie testy przechodzą." >&2
	exit 1
fi
if [ "$status" -ne 1 ] || [ "$failed" != "$expected" ]; then
	echo "Nieoczekiwany wynik bez shop/default-deny (kod pytest $status). Porażki i błędy:" >&2
	echo "${failed:-(brak)}" >&2
	exit 1
fi

restore

echo "== Testy po przywróceniu shop/default-deny; muszą przejść"
status=0
run_tests "$out/restored.txt" || status=$?
if [ "$status" -ne 0 ]; then
	echo "Po przywróceniu shop/default-deny testy nie przechodzą (kod pytest $status)." >&2
	exit 1
fi
echo "Mutacja wykryta: bez shop/default-deny padają dokładnie oczekiwane testy, z polityką wszystkie przechodzą."
echo "Logi: $out/mutated.txt, $out/restored.txt."
```

2. Sprawdzenie bez zmiany klastra:
   - `bash -n tests/security/mutation_check.sh` → kod 0;
   - `mise exec shellcheck@0.11.0 -- shellcheck tests/security/mutation_check.sh` → brak uwag, kod 0;
   - `git ls-files -s tests/security/mutation_check.sh` po `git add` → tryb `100755`;
   - `KUBE_CONTEXT=kind-nie-ma bash tests/security/mutation_check.sh; echo "kod $?"` → `error: context "kind-nie-ma" does not exist`, potem `Brak polityki shop/default-deny albo klastra kind-nie-ma: najpierw make up (albo make deploy).` i `kod 1`; katalog `reports/mutation-check/` nie powstaje, jeśli go wcześniej nie było.

   Mutację na klastrze sprawdzają kroki 3–5 Verification.

### Task 5: Dokumentacja
**Commit:** docs: make test-security, pod bez reguły i test mutacyjny (T26) w README, architekturze i modelu zagrożeń

**Files:**
- Modify: `README.md`
- Modify: `docs/architektura.md`
- Modify: `docs/bezpieczenstwo.md`

1. `README.md`:
   - linię 72 zastąp: ``Testy na działającym klastrze (`make test-security` i `tests/security/mutation_check.sh` same biorą narzędzia z mise; `uv run … pytest` potrzebuje kubectl, kustomize i hubble z mise w PATH; `make test` dojdzie w T27); `tests/security/test_secrets.py` działa też bez klastra:``;
   - w bloku pod nią linię 75 (`uv run --locked pytest tests/security       # RBAC (T11), …`) zastąp trzema liniami poniżej. Linia z `tests/observability` zostaje. Znak `#` stoi w kolumnie 45, jak w obecnych liniach.

```bash
make test-security                          # testy z markerem security: RBAC (T11), NetworkPolicy (T12, T26), Pod Security (T13), sekrety (T14); wyniki w reports/junit-security.xml i reports/security.html
bash tests/security/mutation_check.sh       # test mutacyjny (T26, ok. 3–4 min): bez shop/default-deny musi paść test poda bez reguły; polityka wraca na końcu, logi w reports/mutation-check/
uv run --locked pytest tests/security       # te same testy bez raportów: konta usług, role zespołu, przepływy, pod bez reguły, odrzucenie poda uprzywilejowanego, securityContext podów, brak wartości sekretów w deploy/, gitleaks na historii HEAD
```

2. `docs/architektura.md`, sekcja „Przepływy sieciowe”:
   - linię 170 (`- politykę default-deny w shop, loadgen i aiops;`) zastąp: ``- politykę default-deny w shop, loadgen i aiops oraz jej skutek: pod bez własnej reguły (`t26-unlisted`, tworzony na czas testu z obrazem orders i `python -m http.server 8080`) nie przyjmuje połączenia od intrudera;``;
   - po linii 171 (`- odrzucenie intruder → orders z powodem `POLICY_DENIED` w Hubble.`) wstaw pustą linię i akapit: ``Bez `default-deny` w shop testy odmowy do frontend i orders dalej przechodzą: oba pody mają własne polityki ingress, a `allow-dns` izoluje egress każdego poda. Polityka chroni pod bez własnej reguły i pilnuje jej test mutacyjny `tests/security/mutation_check.sh` (T26). Skrypt usuwa `shop/default-deny` i wymaga porażki dokładnie `test_intruder_to_unlisted_pod_is_denied[shop]` i `test_namespace_has_default_deny[shop]`. Potem przywraca politykę i wymaga zielonego przebiegu. Wszystkie testy z markerem `security` uruchamia `make test-security` (wyniki w `reports/junit-security.xml` i `reports/security.html`).``. Pusta linia przed `Ręcznie: make hubble-relay…` zostaje.
3. `docs/architektura.md:285` (wiersz `Makefile` w „Strukturze repozytorium”): `grafana-password (T14); test, report (dalej)` zamień na `grafana-password (T14); test-security (T26); test, report (dalej)`.
4. `docs/bezpieczenstwo.md`:
   - linia 67: na końcu zdania `… ma kontrolę i nazwany test automatyczny.` dopisz: `` Wszystkie testy z markerem `security` (`tests/security`) uruchamia `make test-security` (T26), wyniki w `reports/junit-security.xml` i `reports/security.html`.``;
   - linię 74 (W4) zastąp: ``| W4 Test niedozwolonego połączenia | default-deny w shop, loadgen i aiops z jawną listą przepływów; odrzucenie widoczne w Hubble; alert `PolicyDeniedConnections` | T12, T19, T26 | `tests/security/test_network_policies.py::test_intruder_to_orders_is_denied`, `::test_intruder_to_unlisted_pod_is_denied`, `::test_hubble_shows_policy_denied_intruder_to_orders`; `tests/security/mutation_check.sh` | testy sieci i test mutacyjny działają; alert działa (T19: e-mail w Mailpit ok. 2 min po pierwszej próbie, test automatyczny w T27) |``;
   - linię 80 (Z1 Ruch boczny) zastąp: ``| Z1 Ruch boczny | default-deny dla ruchu przychodzącego i wychodzącego, tylko przepływy z [tablicy](architektura.md#przepływy-sieciowe) | T12, T18, T26 | `tests/security/test_network_policies.py::test_namespace_has_default_deny`, `::test_intruder_to_unlisted_pod_is_denied` (pod bez własnej reguły w shop, loadgen i aiops), `::test_intruder_to_orders_is_denied`, `::test_orders_to_frontend_is_denied`, `::test_locust_to_orders_is_denied`, `::test_allowed_flow` | działa |``;
   - linię 81 zastąp: ``| Z1 | test mutacyjny: bez `default-deny` w shop pada test odmowy połączenia do poda bez własnej reguły (frontend i orders mają własne polityki ingress, więc ich testy odmowy przechodzą) | T26 | `tests/security/mutation_check.sh`: padają dokładnie `::test_intruder_to_unlisted_pod_is_denied[shop]` i `::test_namespace_has_default_deny[shop]`, a po przywróceniu polityki wszystkie testy sieci przechodzą | działa |``.
   Linia 3 („Stan na …”) się nie zmienia; T14 i T15 też jej nie zmieniały.
5. Sprawdzenie: `make lint` → zielone; `git diff --stat` → tylko trzy pliki z tego Taska.

## Critical files & anchors

- `tests/security/test_network_policies.py`: `kubectl()` (109–119), `intruder_curl()` (146–164, wynik `("000", 28)`), fixture `hubble_server` (225–256, za nią nowa fixture) i `test_namespace_has_default_deny` (288–301, za nim nowy test).
- `deploy/base/networkpolicies/shop.yaml` i `dns.yaml`: dlaczego pody shop zostają izolowane bez `default-deny`. Etykieta poda próbnego nie może pasować do żadnego z tych selektorów.
- `Makefile`: `PATH` (8), `KUBE_CONTEXT` (14), `.PHONY` (24), `deploy:` (125–132); nowy cel stoi za `deploy`.
- `scripts/trivy.sh` (17–23, 85–86): wzór skryptu: `set -euo pipefail`, `cd` do korzenia, PATH z mise, usuwanie starych wyników.
- `tests/security/test_pod_security.py` (33–46): `kubectl()` ze `stdin`, wzór dla Task 2.

## Verification

Korzeń repozytorium, gałąź `t26-testy-bezpieczenstwa` z Taskami 1–5, klaster `kind-secure-k8s-aiops`. Skrót: `K="mise exec -- kubectl --context kind-secure-k8s-aiops"`. Liczby „bez internetu” dotyczą klastra, w którym intruder nie łączy się z `https://1.1.1.1/`; wtedy 4 przypadki `test_egress_to_internet_is_denied` są pomijane. Jeśli którakolwiek liczba albo linia się nie zgadza, zatrzymaj się i zgłoś wynik.

1. Bez klastra:
   - `make lint && make unit && make manifests` → zielone, `unit` → `96 passed`;
   - `make trivy-config` → kod 0 (tylko na bazie z T15);
   - `mise exec -- uv lock --check` → kod 0;
   - `mise exec -- uv run --locked pytest -m security tests --collect-only -q | tail -n 1` → `104/116 tests collected (12 deselected) …`.
2. `make test-security` na działającym klastrze:

   ```bash
   make deploy
   make test-security 2>&1 | tee reports/t26-test-security.txt
   grep -o '<testsuite [^>]*>' reports/junit-security.xml
   grep -c test_intruder_to_unlisted_pod_is_denied reports/security.html
   $K get pods -A -l app.kubernetes.io/name=t26-unlisted
   ```

   - linia podsumowania pytest `104 passed` (bez internetu `100 passed, 4 skipped`), kod make 0;
   - `<testsuite name="pytest" errors="0" failures="0" skipped="0" tests="104" …>` (bez internetu `skipped="4"`);
   - `grep -c` → co najmniej 1;
   - pody: `No resources found`.
3. Test mutacyjny (kryterium 2):

   ```bash
   bash tests/security/mutation_check.sh 2>&1 | tee reports/t26-mutacja.txt; echo "kod ${PIPESTATUS[0]}"
   $K get networkpolicy -A
   ```

   - `kod 0`;
   - przebieg bez polityki: `2 failed, 17 passed` (bez internetu `2 failed, 13 passed, 4 skipped`), a linie podsumowania to:
     - `FAILED tests/security/test_network_policies.py::test_intruder_to_unlisted_pod_is_denied[shop] - AssertionError: assert ('200', 0) == ('000', 28)`;
     - `FAILED tests/security/test_network_policies.py::test_namespace_has_default_deny[shop] - AssertionError: shop: brak NetworkPolicy odcinającej cały ruch podów`;
   - przywrócenie: `networkpolicy.networking.k8s.io/default-deny created` i dwa razy `… unchanged`;
   - przebieg z polityką: `19 passed` (bez internetu `15 passed, 4 skipped`);
   - ostatnie linie `Mutacja wykryta: …` i `Logi: reports/mutation-check/mutated.txt, reports/mutation-check/restored.txt.`;
   - `get networkpolicy -A`: 14 polityk jak w „Ustalonych faktach”, w tym `shop default-deny`.
4. Skrypt odrzuca inny zbiór porażek i przywraca politykę po błędzie (kontrola negatywna, kopia z inną listą oczekiwanych):

   ```bash
   sed 's/test_intruder_to_unlisted_pod_is_denied\[shop\]/test_intruder_to_orders_is_denied/' tests/security/mutation_check.sh > tests/security/t26-negatywna.sh
   bash tests/security/t26-negatywna.sh; echo "kod $?"
   rm tests/security/t26-negatywna.sh
   $K -n shop get networkpolicy default-deny
   git status --short
   ```

   - `kod 1`;
   - na stderr `Nieoczekiwany wynik bez shop/default-deny (kod pytest 1). Porażki i błędy:` i dwa prawdziwe identyfikatory z kroku 3, potem `== Przywracam shop/default-deny: …` i `default-deny created`;
   - polityka istnieje, `git status --short` jest pusty.
5. Przerwanie też przywraca politykę (`timeout` wysyła SIGINT do całej grupy procesów, jak Ctrl+C):

   ```bash
   timeout --preserve-status -s INT 30 bash tests/security/mutation_check.sh; echo "kod $?"
   $K -n shop get networkpolicy default-deny
   mise exec -- uv run --locked pytest tests/security/test_network_policies.py -q
   ```

   - `kod 130`, a w wyjściu `== Przywracam shop/default-deny: …`;
   - polityka istnieje;
   - pytest → `19 passed` (bez internetu `15 passed, 4 skipped`). Fixture usuwa pod `t26-unlisted`, jeśli przerwanie zostawiło go w klastrze.
6. Od zera (kryterium 1 i definicja ukończenia):

   ```bash
   make down && make up
   make test-security 2>&1 | tee reports/t26-swiezy.txt
   bash tests/security/mutation_check.sh 2>&1 | tee reports/t26-mutacja-swiezy.txt; echo "kod ${PIPESTATUS[0]}"
   ```

   - `make up` → kod 0;
   - `make test-security` → `104 passed` (bez internetu `100 passed, 4 skipped`);
   - skrypt → `kod 0` i te same linie co w kroku 3.

## Po dostarczeniu (GitHub)

Wykonuje główny agent po Verification i po code review bez CRITICAL/HIGH.

1. PR z gałęzi `t26-testy-bezpieczenstwa`, tytuł „T26 · Pakiet testów bezpieczeństwa i test mutacyjny polityk”, w treści `Closes #26`.
   - Baza `main`, jeśli #61 jest scalony albo zamknięty. W przeciwnym razie baza `t15-trivy`. Po scaleniu #61:
     - `git fetch origin && git rebase --onto origin/main $(git merge-base t26-testy-bezpieczenstwa t15-trivy) t26-testy-bezpieczenstwa`;
     - `git push --force-with-lease`;
     - `gh pr edit <N> --base main`.
   - Opis podaje:
     - dlaczego doszedł nowy test: usunięcie `shop/default-deny` nie łamie istniejących testów odmowy (`orders-ingress`, `frontend-ingress`, `allow-dns`); decyzja właściciela z 2026-11-21;
     - że test mutacyjny to sam skrypt bez celu make (decyzja właściciela);
     - wyniki z kroków 2, 3 i 6 Verification: liczby testów, dwie linie `FAILED` i końcowy komunikat skryptu.
2. Komentarz w #26: odhaczone kryteria z dowodem:
   - linia podsumowania z `reports/t26-swiezy.txt`;
   - linie `FAILED` i końcowy komunikat z `reports/t26-mutacja-swiezy.txt`.
3. Komentarz w #27: „T26: `make test-security` uruchamia `uv run --locked pytest -m security tests` z `--junitxml=reports/junit-security.xml --html=reports/security.html --self-contained-html`; `pytest-html` jest w grupie `dev`, a `addopts` ma `--strict-markers`. `make test` może wołać ten cel albo użyć tych samych opcji z innym markerem.”
4. Komentarz w #28: „T26: `make test-security` obejmuje `test_history_has_no_leaks` (`make gitleaks` na historii HEAD). Checkout w `e2e.yml` potrzebuje `fetch-depth: 0`, jak job `secrets`, inaczej test skanuje tylko ostatni commit. Test `test_intruder_to_unlisted_pod_is_denied` tworzy pod z obrazem `orders`, który `make up` ładuje do węzłów.”

## Assumptions & contingencies

- Decyzje właściciela z 2026-11-21: pod próbny w shop, loadgen i aiops; test mutacyjny tylko jako skrypt.
- `--strict-markers` trafia do `addopts` w `pyproject.toml`, a nie tylko do celu make, więc chroni też bezpośrednie `uv run pytest -m security`.
- Baza gałęzi zależy od stanu #61 w chwili startu (Warunek wstępny).

Plan awaryjny:
- **pytest-html 4.2.0 pada z pytest 9.2.0** (wyjątek przy starcie albo przy zapisie raportu w kroku 4 Task 1): zatrzymaj się i zgłoś traceback. Nie obniżaj pytest i nie zmieniaj wtyczki.
- **`git diff uv.lock` w Task 1 zmienia wersję innego pakietu:** zatrzymaj się i zgłoś diff.
- **`kubectl wait` na `t26-unlisted` przekracza czas:** `$K -n <ns> describe pod t26-unlisted` i `$K -n <ns> get events --sort-by=.lastTimestamp`.
  - `ErrImageNeverPull`, `ErrImagePull` albo `ImagePullBackOff`: brak obrazu w węźle; `make images`, potem powtórz.
  - `violates PodSecurity`: zatrzymaj się i zgłoś komunikat (dry-run przechodził).
  - Inna przyczyna: zatrzymaj się i zgłoś wynik.
- **Test poda próbnego daje `("200", 0)` przy istniejącym default-deny:** Cilium nie egzekwuje polityki na nowym podzie. Zatrzymaj się i zgłoś:
  - `mise exec -- hubble observe --to-namespace <ns> --last 20` (po `make hubble-relay`);
  - `$K -n kube-system exec ds/cilium -- cilium-dbg endpoint list`.
  Nie dodawaj `sleep` ani ponowień.
- **W przebiegu bez polityki pada test spoza `EXPECTED_FAILED`** (np. Hubble):
  1. Powtórz skrypt raz.
  2. Ten sam wynik: `mise exec -- uv run --locked pytest tests/security/test_network_policies.py` na klastrze z polityką.
  3. Pada też tam: to stan klastra; `make deploy`, potem powtórz. Nie pada: zatrzymaj się i zgłoś oba logi z `reports/mutation-check/`.
- **Skrypt kończy się komunikatem `Polityka shop/default-deny NIE wróciła`:** wykonaj podane w nim polecenie, potem `$K -n shop get networkpolicy default-deny`.
- **Krok 5 Verification daje `kod 1` i `Nieoczekiwany wynik … (kod pytest 130)` albo `(kod pytest 2)` zamiast `kod 130`:** bash obsłużył przerwanie dopiero po ocenie wyniku. Polityka wraca tak samo. Sprawdź `$K -n shop get networkpolicy default-deny`; jeśli istnieje, zapisz kod w opisie PR i kontynuuj.
- **`make up` pada na zajętym porcie (`address already in use`):** zwolnij port 8080, 3000 albo 8025 na `127.0.0.1` i powtórz.
