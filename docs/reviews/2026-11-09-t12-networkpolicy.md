# Code Review: t12-networkpolicy

Review scope: changes since 90dd23e (15 files)

Zakres: `90dd23ed9ef80253817545ba5db7f73a481d33c6..HEAD` (4 commity zadań i commit planu), dostarczone z `docs/plans/2026-11-09-t12-networkpolicy.md`.

**Podsumowanie:** 0 CRITICAL, 0 HIGH, 0 MEDIUM, 3 LOW. Audyt bezpieczeństwa: bez uwag (gitleaks, Semgrep, Bandit, Trivy config i image, pip-audit). Weryfikacja planu na klastrze: `9 failed, 4 passed` bez polityk, `87 passed` z politykami, obie mutacje `2 failed, 11 passed`, Hubble CLI pokazuje `POLICY_DENIED`, `make down && make up` kończy się `87 passed`. QA pominięte na prośbę właściciela.

---

### [LOW] MAINT-001: intruder uruchamia `sleep infinity` jako PID 1, który ignoruje SIGTERM
**Status:** ✅ Fixed (2026-11-09)

**ID:** MAINT-001
**Location:** `deploy/base/intruder/deployment.yaml:37`
**Category:** Maintainability
**Effort:** trivial

**Problem:**
`command: [sleep, infinity]` czyni BusyBox `sleep` procesem PID 1 kontenera. Nie ma on obsługi SIGTERM, więc kernel go nie dostarcza. Obraz `curl@sha256:3fb7e13e…` uruchomiony lokalnie z `--user 10001:10001 --read-only --cap-drop ALL`: `docker stop -t 5` trwał 5,17 s (pełny limit i SIGKILL), z pułapką 125 ms. Manifest nie ustawia `terminationGracePeriodSeconds`, więc usunięcie poda czeka domyślne 30 s [INFERENCE: nie usuwano poda na współdzielonym klastrze]. Projekt rozwiązał to już dla drugiego bezczynnego kontenera: `fault-runner idle` czeka na SIGTERM (`chaos/src/fault_runner/cli.py:182-187`).

**Impact:**
Ok. 30 s oczekiwania przy każdym usunięciu, drenażu, rolloucie po podbiciu obrazu i `make down` poda intruder; niespójne z fault-runnerem.

**Remediation:**

```yaml
# Before
          command: [sleep, infinity]
# After
          # sleep jako PID 1 ignoruje SIGTERM, a kubelet czekałby cały terminationGracePeriodSeconds
          # (jak `fault-runner idle`); pułapka kończy kontener od razu.
          command: [sh, -c, "trap 'exit 0' TERM; sleep infinity & wait"]
```

---

### [LOW] MAINT-002: komentarz w `orders-ingress` obiecuje ochronę ścieżki `/faults/*`, której reguła L4 nie daje
**Status:** ✅ Fixed (2026-11-09)

**ID:** MAINT-002
**Location:** `deploy/base/networkpolicies/shop.yaml:60`
**Category:** Maintainability
**Effort:** trivial

**Problem:**
Komentarz „Etykieta z T08: tylko fault-runner może wołać /faults/*.” opisuje gwarancję na poziomie ścieżki. NetworkPolicy działa na portach, a ta sama lista `from` wpuszcza też frontend (`shop.yaml:57-59`) i Prometheus (`shop.yaml:68-73`) na ten sam port 8080, więc obaj dosięgają `/faults/*`. Faktyczną ochroną jest `X-Fault-Token` (`docs/architektura.md:206`); sekret `fault-token` montuje tylko fault-runner i orders. Ten element gwarantuje co innego: żaden inny pod z loadgen (np. locust z T18) nie dosięgnie orders. Identyczne sformułowanie jest w `deploy/base/fault-runner/deployment.yaml:18` (poza diffem, ale nieprawdziwe dzięki tej zmianie).

**Impact:**
Czytelnik manifestu bezpieczeństwa może uznać etykietę za kontrolę dostępu do ścieżki i poluzować sprawdzanie tokenu albo dopisać peera na tej podstawie.

**Remediation:**

```yaml
# Before
        # Etykieta z T08: tylko fault-runner może wołać /faults/*.
# After
        # Z loadgen tylko fault-runner (etykieta role z T08). Reguła działa na L4: /faults/* chroni X-Fault-Token.
```

Wyrównaj też komentarz w `deploy/base/fault-runner/deployment.yaml:18`.

---

### [LOW] DOC-001: komentarz przy `make deploy` nie wymienia NetworkPolicy
**Status:** ✅ Fixed (2026-11-09)

**ID:** DOC-001
**Location:** `Makefile:101`
**Category:** Documentation
**Drift-class:** mechanical
**Fix-policy:** auto

**Problem:**
`deploy/base/kustomization.yaml:6` dopisuje `- networkpolicies`, więc `make deploy` stosuje teraz 13 obiektów NetworkPolicy i włącza default-deny w shop, loadgen i aiops. Komentarz nad celem `deploy` nadal mówi „Overlay local (namespace'y, RBAC i aplikacje)”. Ten sam komentarz poprawiał przegląd T11 (MAINT-004 w `docs/reviews/2026-11-07-t11-rbac.md`). Zgłoszone niezależnie przez audytora jakości i audytora dokumentacji; scalone w jeden wpis.

**Impact:**
Czytelnik Makefile nie dowie się, że `make deploy` zmienia izolację sieciową, a to krok, który najczęściej psuje ruch.

**Remediation:**

```text
# Before
# Overlay local (namespace'y, RBAC i aplikacje) przez kustomize …
# After
# Overlay local (namespace'y, RBAC, NetworkPolicy i aplikacje) przez kustomize …
```

---

## Verification Summary

**Method:** Cross-domain correlation and adversarial review (Cross-Verifier + Challenger)

| Metric | Count |
|--------|-------|
| Findings verified | 3 |
| False positives removed | 0 |
| Severity adjustments | 0 |
| Cross-analysis findings | 0 |

### Cross-Analysis (Security <-> Quality)

- Brak ustaleń bezpieczeństwa, więc brak kompozytów. CQ-3 i DOC-001 to jedna usterka zgłoszona dwa razy (scalona w DOC-001). CQ-1 i CQ-2 nie mają wspólnej przyczyny.
- Luka pokrycia: to samo fałszywe sformułowanie co w MAINT-002 jest w `deploy/base/fault-runner/deployment.yaml:18`; ujęte w remediacji MAINT-002.

### Challenged Findings

- Wszystkie 3 ustalenia potwierdzone na LOW; brak usunięć i zmian wagi.

### Rejected by auditors (self-falsification)

- Namespace intruder bez NetworkPolicy — zapisana decyzja planu, exec do poda ma tylko cluster-admin.
- Eksfiltracja przez DNS do kube-dns — wymagana przez tablicę przepływów; filtr FQDN wymagałby CiliumNetworkPolicy, wykluczonej regułą `networking.k8s.io/v1`.
- orders-ingress wpuszcza Prometheusa na wszystkie ścieżki 8080 — polityki v1 działają na portach, `/faults/*` chroni token.
- Fałszowanie etykiet podów (frontend, role: fault-runner, prometheus) — pody w shop, loadgen i monitoring tworzy tylko cluster-admin.
- Ruch hosta na tym samym węźle omija orders-ingress (Cilium allow-localhost) — fakt platformy, opisany w `docs/architektura.md:126`.
- curl exit 28 niejednoznaczny — osobno wymagany przepływ `POLICY_DENIED` w Hubble.
- `readline()` bez limitu czasu w `hubble_server` — kubectl zamyka stdout przy błędzie port-forward.
- `--since 1m` łapie wcześniejsze odrzucenia — warunek wstępny w teście dowodzi bieżącego odrzucenia.
- Trzy kopie `default-deny` i `allow-dns` — decyzja planu (jawny namespace, wzór `rbac/`), notki „zmieniaj razem”.
- Brak adnotacji typów w funkcjach testowych — konwencja projektu (37 z 37 niezaadnotowanych), ruff nie wybiera ANN.
- Wyniki skanerów Bandit B101/B404/B603/B607, Trivy KSV-0110/KSV-0125, zlib CVE-2026-4738 (MEDIUM, poniżej bramki HIGH/CRITICAL) — szum albo znane uwagi wspólne z pozostałymi Deploymentami.
- `docs/architektura.md:31` („obraz bez tagu”), `platform/versions.env:1`, `docs/karta-projektu.md:64` — poza zakresem lub wyjątek opisany w `architektura.md:19,23`.

### Doctrine-gap candidates

- Pody z `hostNetwork` (node-exporter T16, Alloy T17) dzielą tożsamość węzła i omijają polityki.
- Brak reguły, czy intruder z `deploy/base` trafia do overlayu cloud (T29).
- Namespace monitoring nie ma NetworkPolicy (po T16 Prometheus i Alertmanager osiągalne z dowolnego poda w intruder).
- Brak reguły współdzielenia helperów między modułami `tests/security` (`kubectl()` i fixture `cluster` zduplikowane w `test_rbac.py` i `test_network_policies.py`).
- Brak procedury podbijania zewnętrznych obrazów przypiętych po digest w `deploy/` (dependabot ich nie obejmuje).
- Brak zapisanej zasady obsługi sygnałów PID 1 w bezczynnych kontenerach (istnieje tylko jako komentarz w `cli.py:183-184`).

### Out of scope (scope check)

None.
