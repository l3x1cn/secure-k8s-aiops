Review scope: changes since 0056ffb (12 files)

# Code review: gałąź `t17-logi-zdarzenia` (0056ffb..HEAD)

Dostarczone z `docs/plans/2026-11-21-t17-logi-zdarzenia.md`. Zakres: `Makefile`, `README.md`, `deploy/observability/values/alloy.yaml`, `deploy/observability/values/kube-prometheus-stack.yaml`, `deploy/observability/values/loki.yaml`, `docs/architektura.md`, `docs/bezpieczenstwo.md`, `docs/plans/2026-11-21-t17-logi-zdarzenia.md`, `docs/testing/plans/2026-11-22-t17-loki-alloy-logs-events-test-plan.md`, `platform/versions.env`, `tests/observability/test_logs.py`, `tests/security/test_rbac.py`.

**Wynik:** 0 CRITICAL, 0 HIGH, 4 MEDIUM, 2 LOW. Żaden wpis nie blokuje scalenia.

Skanery: gitleaks i trufflehog (brak wycieków), Semgrep i Bandit (trafienia odrzucone), Trivy na wyrenderowanych manifestach i obrazach `grafana/loki:3.7.10`, `grafana/alloy:v1.22.0` (bez naprawialnych HIGH/CRITICAL w zmianach), ruff (czysto), docs-drift (1 trafienie, odrzucone: `loki.monitoring.svc:3100` to host i port, nie odwołanie do pliku).

## Findings

### [MEDIUM] SEC-001: Każdy pod z dostępem do Lokiego może usuwać logi i zatrzymać Lokiego bez poświadczeń; R1 wymienia tylko odczyt i fałszywe wpisy [verified]

**ID:** SEC-001
**Location:** `deploy/observability/values/loki.yaml:29`
**Category:** Security
**OWASP:** A09:2025
**CWE:** CWE-306
**Effort:** trivial

**Problem:**
`loki.yaml:28-30` włącza `compactor.retention_enabled: true` z `delete_request_store`, a `limits_config` (linie 26-27) nie ustawia `deletion_mode`. Domyślnie w Loki 3.7 to `filter-and-delete`, więc API usuwania działa, gdy retencja jest włączona. Przy `auth_enabled: false` (linia 10) `POST /loki/api/v1/delete` na :3100 nie wymaga poświadczeń. Ten sam port obsługuje `/ingester/shutdown` i `/flush`. Namespace intruder nie ma NetworkPolicy, monitoring nie ma default-deny, a `anomaly-detector` ma egress do `loki:3100` (`deploy/base/networkpolicies/aiops.yaml:50-60`). Nowy tekst R1 (`docs/bezpieczenstwo.md:111`) mówi tylko o odczycie i fałszywych wpisach.

**Impact:**
Atakujący z poda intruder ukrywa własny ślad (`POST /loki/api/v1/delete?query={namespace="intruder"}&start=0`) albo wielokrotnie zatrzymuje `loki-0` przez `/ingester/shutdown`, a back-off kubeleta zostawia luki w zapisie. NetworkPolicy z T29 (L3/L4) nie rozróżni `/query_range` od `/loki/api/v1/delete` na tym samym porcie dla dozwolonych klientów.

**Remediation:**
Wyłącz API usuwania; retencja 72 h działa bez niego. Rozszerz R1 o usuwanie, `/ingester/shutdown`, `/flush` i memberlist :7946.

```yaml
# Before
limits_config:
  retention_period: 72h

# After
limits_config:
  retention_period: 72h
  # API usuwania (/loki/api/v1/delete) bez uwierzytelnienia pozwala każdemu podowi z dostępem do :3100 ukryć logi; retencja działa bez niego.
  deletion_mode: disabled
```

### [MEDIUM] SEC-002: Etykieta `level` przyjmuje dowolną wartość z tekstu logu, więc jeden przejęty pod wyczerpuje limit strumieni Lokiego [verified]

**ID:** SEC-002
**Location:** `deploy/observability/values/alloy.yaml:81`
**Category:** Security
**OWASP:** A06:2025
**CWE:** CWE-770
**Effort:** easy

**Problem:**
`alloy.yaml:77-83` kopiuje pole JSON `level` z każdej zebranej linii do etykiety strumienia (`stage.json`, potem `stage.labels`), bez sprawdzenia, czy należy do zbioru kontraktu DEBUG/INFO/WARNING/ERROR (`docs/architektura.md:186`). Każda nowa wartość tworzy nowy strumień. Loki ma jednego tenanta (`auth_enabled: false`) i domyślny limit 5000 aktywnych strumieni (`max_global_streams_per_user`); po jego przekroczeniu odrzuca nowe strumienie kodem 429. Pody shop, loadgen i aiops nie dosięgną Lokiego bezpośrednio (default-deny egress), więc ta etykieta to jedyna droga, którą mogą tworzyć strumienie.

**Impact:**
Kod uruchomiony w frontendzie drukuje 5000 linii z różnymi `level` i blokuje nowe strumienie dla wszystkich namespace'ów, np. pierwszy strumień `level="ERROR"` orders. Alerty liczą się z metryk, więc cierpi kontekst logowy dla analizy (T24), nie sama detekcja.

**Remediation:**
Etykietą zostaje tylko wartość z kontraktu; inna wartość zostaje w linii i jest wyszukiwalna przez `| json`. Konfiguracja przechodzi przez `tpl` Helma, więc poprawka używa `stage.regex`, bez `{{ }}`.

```alloy
// Before
stage.json {
  expressions = { level = "" }
}

stage.labels {
  values = { level = "" }
}

// After
stage.json {
  expressions = { level = "" }
}

// Etykieta tylko z wartości kontraktu; inna wartość (np. z przejętego poda) nie tworzy nowych strumieni.
stage.regex {
  source     = "level"
  expression = "^(?P<contract_level>DEBUG|INFO|WARNING|ERROR)$"
}

stage.labels {
  values = { level = "contract_level" }
}
```

### [LOW] SEC-003: Port klastra Alloy 12345 bez uwierzytelnienia; obcy peer może przejąć zbieranie zdarzeń wybranych namespace'ów [verified]

**ID:** SEC-003
**Location:** `deploy/observability/values/alloy.yaml:110`
**Category:** Security
**OWASP:** A08:2025
**CWE:** CWE-306
**Effort:** medium

**Problem:**
`alloy.yaml:109-110` włącza clustering: DaemonSet dostaje `--cluster.enabled=true --cluster.join-addresses=alloy-cluster --server.http.listen-addr=0.0.0.0:12345` bez TLS i uwierzytelnienia; ten port obsługuje też UI i endpointy debug. Przy `loki.source.kubernetes_events` (linie 91-101) każdy namespace czyta tylko peer, który go „posiada”. Pody bez polityki egress (intruder) sięgają `monitoring:12345`. R1 nie wspomina o tej powierzchni.

**Impact:**
Obcy peer przejmuje intruder albo shop, a zdarzenia (np. `BackOff`) nie trafiają do Lokiego. Atak wymaga klienta protokołu klastra i pod intruder ma 32 Mi pamięci, stąd LOW.

**Remediation:**
Dopisz port 12345 do R1. W T29 dodaj ingress NetworkPolicy tylko dla podów Alloy albo włącz TLS klastra (`--cluster.enable-tls`); polityka zablokuje też sprawdzanie peerów przez proxy API serwera z planu, więc ta kontrola wymaga zmiany.

```yaml
# Dla T29
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: alloy-ingress
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: alloy
  policyTypes: [Ingress]
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: alloy
      ports:
        - protocol: TCP
          port: 12345
```

### [MEDIUM] MAINT-001: Twierdzenie „Role tylko z get, list, watch na pods i events” dla Alloy sprawdzają wyłącznie próbki `can-i` [verified]

**ID:** MAINT-001
**Location:** `tests/security/test_rbac.py:105-115`
**Category:** Maintainability
**Effort:** easy

**Problem:**
Wiersze `sa:monitoring/alloy-…` w `test_permission_matrix` to 8 przypadków zgody i 4 próbki odmowy. Żaden nie wykryje `create`/`delete` na pods, `pods/exec` ani ClusterRole z innym zasobem niż secrets. Wiersz Z3 (`docs/bezpieczenstwo.md:88`) podaje tylko te wiersze jako dowód. Plik sam deklaruje zasadę „Wykluczenia dowodzimy z reguł ról, nie z próbek `can-i`” (`tests/security/test_rbac.py:197-198`).

**Impact:**
Rozszerzenie Role albo dodanie ClusterRoleBinding dla konta `monitoring/alloy` przy kolejnej aktualizacji chartu przejdzie testy.

**Remediation:**
Dodaj test reguł Role w czterech namespace'ach i braku ClusterRoleBinding dla konta; wpisz go w kolumnę dowodu wiersza Z3.

```python
ALLOY_RULES = [
    {"apiGroups": [""], "resources": ["pods", "events"], "verbs": ["get", "list", "watch"]}
]


def test_alloy_has_only_namespaced_read_rules():
    for namespace in ALLOY_NAMESPACES:
        rules = get_json("role", "alloy", "-n", namespace)["rules"]
        assert rules == ALLOY_RULES, (namespace, rules)
    cluster_bindings = [
        binding["metadata"]["name"]
        for binding in get_json("clusterrolebindings")["items"]
        for subject in binding.get("subjects") or []
        if subject["kind"] == "ServiceAccount"
        and (subject.get("namespace"), subject["name"]) == ("monitoring", "alloy")
    ]
    assert not cluster_bindings, cluster_bindings
```

### [LOW] MAINT-002: Lista namespace'ów z logami występuje trzy razy w `alloy.yaml` bez kontroli zgodności [verified]

**ID:** MAINT-002
**Location:** `deploy/observability/values/alloy.yaml:23`
**Category:** Maintainability
**Effort:** trivial

**Problem:**
Te same cztery namespace'y stoją w `discovery.kubernetes` (linia 23), `loki.source.kubernetes_events` (linia 94) i `rbac.namespaces` (linia 150); lista jest też w `tests/security/test_rbac.py:66`. Dopisanie namespace'u do discovery lub zdarzeń bez `rbac.namespaces` daje 403 i ciche zniknięcie logów, a `rollout status` i `test_logs.py` (sprawdza tylko `shop`) przechodzą. Wzorzec projektu to komentarz „zmieniaj razem” i test (`default-deny.yaml:3`); tu nie ma żadnego.

**Impact:**
Drobna zmiana potrafi po cichu odciąć logi namespace'u, co wyjdzie później jako brak danych dla T24.

**Remediation:**
Opcja A: lista z `rbac.namespaces` przez `tpl` (zmiana komentarza w linii 15, bo `{{ }}` staje się dozwolone). Opcja B: test parsujący plik values i sprawdzający zgodność trzech list.

```yaml
# Before
names = ["shop", "loadgen", "aiops", "intruder"]
namespaces = ["shop", "loadgen", "aiops", "intruder"]

# After
names = {{ .Values.rbac.namespaces | toJson }}
namespaces = {{ .Values.rbac.namespaces | toJson }}
```

### [MEDIUM] DOC-001: R1 twierdzi, że „każdy pod w klastrze” sięga Lokiego, a default-deny egress blokuje większość podów projektu [verified]

**ID:** DOC-001
**Location:** `docs/bezpieczenstwo.md:111`
**Category:** Documentation
**Drift-class:** decision
**Fix-policy:** needs-decision

**Problem:**
Dodane zdanie R1 mówi: „każdy pod w klastrze może czytać logi i zdarzenia z shop, loadgen, aiops i intruder albo dopisać fałszywe wpisy”. `default-deny.yaml:7,18,29` odbiera egress w shop, loadgen i aiops, a reguły per pod (`shop.yaml:25`, `loadgen.yaml:6`, `loadgen.yaml:37`) nie otwierają drogi do Lokiego. Tylko `anomaly-detector-egress` (`aiops.yaml:50-60`) pozwala na `monitoring/loki:3100`. Zdanie przeczy wierszom Z1 i Z2 tego samego dokumentu.

**Impact:**
Osoba planująca NetworkPolicy i uwierzytelnienie Lokiego w T29 dostaje zły zbiór ekspozycji; model zagrożeń sugeruje, że egress z T12 nie działa dla Lokiego.

**Remediation:**
Opcja (a): zawęź zdanie do podów z namespace'ów bez polityk egress (intruder, monitoring, kube-system) i `anomaly-detector`, a przy okazji dopisz usuwanie logów, `/ingester/shutdown`, `/flush`, memberlist, port Alloy 12345 i wyczerpanie limitu strumieni bezpośrednim pushem (SEC-001, SEC-002, SEC-003). Opcja (b): zostaw szerokie sformułowanie z adnotacją „każdy pod, którego egress nie ogranicza NetworkPolicy”.

---

## Verification Summary

**Method:** Cross-domain correlation and adversarial review (Cross-Verifier + Challenger)

| Metric | Count |
|--------|-------|
| Findings verified | 6 |
| False positives removed | 0 |
| Severity adjustments | 0 |
| Cross-analysis findings | 0 |

### Cross-Analysis (Security <-> Quality)
- SEC-001 + DOC-001: wiersz R1 zawyża, które pody sięgają Lokiego, a zaniża, co mogą tam zrobić. Zawężenie R1 (DOC-001) bez dopisania usuwania, `/ingester/shutdown`, `/flush` i memberlist (SEC-001) pogarsza zaniżenie; poprawić w jednym commicie wraz z `deletion_mode: disabled`. NetworkPolicy z T29 (L3/L4) nie odetnie usuwania ani shutdownu dla dozwolonych klientów, więc `deletion_mode: disabled` zostaje jedyną kontrolą.
- SEC-002 + DOC-001: `stage.regex` zamyka tylko drogę przez stdout; pody z poprawionego zbioru DOC-001 mogą nadal pisać bezpośrednio na `/loki/api/v1/push` z tysiącami etykiet. R1 opisuje push tylko jako „dopisać fałszywe wpisy”.
- SEC-003 + MAINT-002: dwa niezależne sposoby cichej utraty zdarzeń jednego namespace'u w `loki.source.kubernetes_events` (obcy peer albo rozjazd listy z `rbac.namespaces`); nic ich nie zgłasza, a test sprawdza tylko `shop`. Oba LOW, kompozyt nie powstał (różne poprawki).
- Luki pokrycia: wiersz Z3 (`docs/bezpieczenstwo.md:88`) cytuje jako dowód test, który nie dowodzi „tylko” ani „bez ClusterRole” (MAINT-001); `docs/architektura.md:206` opisuje etykietę `level` jako pochodzącą z kontraktu, a wartości spoza kontraktu też stają się etykietą (SEC-002); żaden audyt nie sprawdził, czy potok logów zgłasza własne awarie (brak ServiceMonitora i reguł dla Alloy i Lokiego), co może należeć do późniejszego zadania.

### Challenged Findings
- Żaden wpis nie został usunięty ani zmieniony. Challenger potwierdził SEC-001 (domyślne `deletion_mode: filter-and-delete`, `/ingester/shutdown` na :3100), SEC-002 (domyślne `max_global_streams_per_user: 5000`; opis skutku złagodzony: ucierpi kontekst logowy, nie alerty z metryk), SEC-003, MAINT-001, MAINT-002 i DOC-001. Nie zgłosił odrzuconych wpisów do przywrócenia.

### Rejected by auditors (self-falsification)
- semgrep dynamic-urllib-use-detected / bandit B310 (urlopen) — stały URL `http://localhost:3000` i stałe ścieżki w teście.
- bandit B404/B603/B607 (subprocess, kubectl z PATH) — argumenty jako lista bez powłoki, wzorzec jak `tests/security/test_rbac.py`.
- bandit B101 (assert w testach) — idiom pytest.
- bandit B105 (możliwe zakodowane hasło) — ścieżka katalogu tokenu konta usługi, wiersz sprzed zmiany.
- trivy KSV-0118 (domyślny securityContext poda Alloy) — oba kontenery ustawiają `runAsNonRoot`, UID, seccomp, `drop: ALL`, bez eskalacji, read-only root FS.
- trivy KSV-0023 (hostPath) — Alloy czyta `/var/log/pods` tylko do odczytu; opisuje to R2.
- trivy KSV-0125 (rejestr spoza listy) — projekt używa docker.io i quay.io, brak listy dozwolonych rejestrów.
- CVE-2026-78661 w `golang.org/x/net` 0.61.0 w `prometheus-config-reloader` v0.94.2 — ten sam obraz działa już z kube-prometheus-stack (T16); config-reloader nie parsuje niezaufanego HTML.
- Token konta `loki` zamontowany — `loki-clusterrole` ma `rules: []`; `docs/architektura.md:93` wyłącza charty z zasady braku tokenu.
- hostPath `/var/log` szerszy niż `/var/log/pods` — R2 opisuje wybór; wszystkie logi podów i tak leżą w `/var/log/pods`.
- Hasło admina Grafany w teście — czytane z Secretu w czasie testu, wysyłane tylko na localhost:3000, bez `--showlocals`.
- Odczyt i zapis w Lokim bez uwierzytelnienia oraz brak NetworkPolicy — opisuje R1, plan odkłada to na T29 (tylko usuwanie i shutdown to SEC-001).
- Ruch Grafana → Loki po HTTP bez TLS — R3.
- Zduplikowany helper `kubectl()` i fixture `cluster` w `test_logs.py` — wzorzec projektu (6 kopii przed zmianą).
- Trzy podobne polecenia `helm upgrade --install` w `Makefile` — ustalony styl (trzy takie przed zmianą).
- Testy bez `-> None`, helpery zwracają goły `dict` — konwencja projektu, brak mypy/basedpyright.
- `KeyError` zamiast asercji, gdy linia ERROR nie ma `status` albo `route` — nieosiągalne w opisanym przepływie.
- Skutki uboczne testu BackOff (dwa restarty orders, e-mail PodRestarts, wzrost back-offu) — zamierzone i opisane w planie i README.
- Alloy montuje cały `/var/log` — zagadnienie najmniejszych uprawnień, ujęte w R2.
- Pusta ClusterRole i ClusterRoleBinding `loki-clusterrole` — bezczynne (`rules: []`), oczekiwane w planie.
- `loki.monitoring.svc:3100` powtórzone w kilku plikach — kontrakt między wydaniami, opisany w `docs/architektura.md` i sprawdzany przez `test_grafana_has_loki_datasource`.
- `GRAFANA_URL` na stałe `localhost:3000` — port stały w `platform/kind/cluster.yaml`, a `kubectl get --raw` nie wyśle uwierzytelnienia Grafany.
- Pre-pass LINEREF_NOFILE `loki.monitoring.svc:3100` — host i port usługi, nie odwołanie do pliku.
- Czas `make up` w README nie zmierzony po dodaniu Lokiego i Alloy — świadome pominięcie, czas trafia do opisu PR.
- Czas testu T17 „ok. 1 min” w README — czas wykonania, nie do sprawdzenia statycznie.
- R1: „logi z kontraktu nie zawierają treści zamówień” a frontend loguje `ValidationError` — nieosiągalne w żadnej ścieżce (orders nie zwraca niepoprawnego 201), dane są syntetyczne.
- Komentarz znacznika pytest w `pyproject.toml` pomija T17 — komentarz w kodzie, nie dokumentacja; pomijał też T18.
- Stempel „Stan na 10.11.2026 (main po T13)” w `docs/bezpieczenstwo.md:3` — nieaktualny już przed tą zmianą (T14–T26).

### Doctrine-gap candidates
- Obrazy wdrażane przez charty przypięte tylko tagiem — `docker.io/grafana/loki:3.7.10` i `docker.io/grafana/alloy:v1.22.0`; digest wersji chartu utrwala szablony, nie zawartość obrazu, a żadna reguła nie wymaga skanu ani digestu.
- Brak reguły ograniczającej wartości etykiet Lokiego do zbioru zamkniętego — Z7 obejmuje tylko etykiety metryk `method` i `route`.
- Współdzielony helper dla testów na żywym klastrze — `KUBE_CONTEXT`, `kubectl()` i część fixture `cluster` skopiowane w 7 modułach `tests/`.
- Walidacja wartości Helma w CI — `deploy/observability/values/*.yaml`, w tym osadzona konfiguracja Alloy, nie podlega żadnej bramce; błąd składni wychodzi dopiero przy `make up`.
- Stempel „Stan na … (main po Tnn)” w `docs/bezpieczenstwo.md:3` — żadna reguła nie wymaga jego aktualizacji w zadaniu (sześć zadań go pominęło).

### Out of scope (scope check)
None.
