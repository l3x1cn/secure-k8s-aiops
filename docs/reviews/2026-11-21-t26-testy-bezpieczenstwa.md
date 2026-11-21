Review scope: changes since f30e5fe (8 files)

# Code review: gałąź `t26-testy-bezpieczenstwa` (f30e5fe..HEAD)

Dostarczone z `docs/plans/2026-11-21-t26-testy-bezpieczenstwa.md`. Zakres: `Makefile`, `README.md`, `docs/architektura.md`, `docs/bezpieczenstwo.md`, `pyproject.toml`, `tests/security/mutation_check.sh`, `tests/security/test_network_policies.py`, `uv.lock`.

**Wynik:** 0 CRITICAL, 0 HIGH, 0 MEDIUM, 5 LOW. Żaden wpis nie blokuje scalenia.

Skanery: gitleaks (brak wycieków), Semgrep (bez trafień w zmianach), Bandit (trafienia odrzucone), shellcheck 0.11.0 (czysto), ruff (czysto), `uv lock --check` (ok), pip-audit (nowe pakiety `pytest-html` 4.2.0 i `pytest-metadata` 3.1.1 bez CVE).

## Findings

### [LOW] SEC-001: Drugie przerwanie podczas przywracania w pułapce EXIT zostawia shop/default-deny usunięte, bez ostrzeżenia [verified]
**Status:** ✅ Fixed (2026-11-21)

**ID:** SEC-001
**Location:** `tests/security/mutation_check.sh:74`
**Category:** Security
**OWASP:** A10:2025
**CWE:** CWE-636
**Effort:** trivial

**Problem:**
Pułapki `trap 'exit 130' INT` (linia 74) i `trap 'exit 143' TERM` (linia 75) działają też w `on_exit` (linie 65–72). Drugi SIGINT albo SIGTERM w trakcie `kubectl apply` w `restore` (linia 60) zabija kubectl, a bash wykonuje `exit 130` wewnątrz pułapki EXIT. Gałąź `|| return 1` i komunikat `Polityka shop/default-deny NIE wróciła` (linia 68) nigdy się nie wykonują, a skrypt kończy kodem 130, który nagłówek (linia 12) opisuje jako „polityka przywrócona”. Model pułapek z dwoma SIGINT do grupy procesów dał `restoring` i kod 130 bez przywrócenia.

**Impact:**
Po szybkim podwójnym Ctrl+C w shop zostaje bez `default-deny`. Pody `frontend`, `orders` i każdy pod z `allow-dns` pozostają izolowane, ale pod bez własnej reguły ingress przyjmuje połączenia, dopóki ktoś nie uruchomi `make deploy` albo `kubectl apply`. Brak polityki wykryje dopiero kolejny `make test-security` (`test_namespace_has_default_deny[shop]`).

**Remediation:**

```bash
# Before
on_exit() {
	local status=$?
	if ! restore; then

# After
on_exit() {
	local status=$?
	# Przywracania polityki nie może przerwać kolejny Ctrl+C ani SIGTERM.
	trap '' INT TERM
	if ! restore; then
```

Potem `mise exec shellcheck@0.11.0 -- shellcheck tests/security/mutation_check.sh` i krok 5 Verification (`timeout --preserve-status -s INT 30 bash tests/security/mutation_check.sh` → kod 130, polityka wróciła).

---

### [LOW] SEC-002: Linie ERROR liczą się jako oczekiwane porażki, więc przejściowy błąd fixture może udać wykrycie mutacji [verified]
**Status:** ✅ Fixed (2026-11-21)

**ID:** SEC-002
**Location:** `tests/security/mutation_check.sh:52`
**Category:** Security
**Effort:** easy

**Problem:**
`failed_ids` zbiera identyfikatory z linii `FAILED` i `ERROR` do jednego zbioru, który porównuje z `EXPECTED_FAILED` (linie 28–29, 100). Jednorazowy błąd w fixture `unlisted_pod` dla `[shop]` (np. przekroczony `kubectl wait`, `pytest.fail` w `kubectl()`, `tests/security/test_network_policies.py:125-127`) daje `ERROR …::test_intruder_to_unlisted_pod_is_denied[shop]`, razem z `FAILED …::test_namespace_has_default_deny[shop]` to dokładnie oczekiwany zbiór, choć połączenia nie sprawdzono. Drugi przypadek: mutacja przeżywa (połączenie przechodzi), a `kubectl delete` w teardown fixture raz zawodzi, więc przechodzący test jest raportowany jako `ERROR`.
Trwały błąd łapie przebieg po przywróceniu polityki, który musi być zielony (linie 108–113). Plan mówi, że oczekiwane są porażki (`FAILED`); nie zapisuje, że `ERROR` oczekiwanego testu liczy się jako wykrycie.

**Impact:**
Fałszywy werdykt „Mutacja wykryta” w przypadku, którego test ma pilnować. Wymaga jednorazowego błędu ograniczonego do przypadku `[shop]`; klaster nie traci ochrony.

**Remediation:**
Wymagać, żeby `test_intruder_to_unlisted_pod_is_denied[shop]` był w linii `FAILED`, a nie `ERROR`: dwa zbiory (`failed_ids` tylko z `^FAILED `, a osobno sprawdzenie braku linii `^ERROR `). Każdy `ERROR` w przebiegu z mutacją to wynik nieoczekiwany.

---

### [LOW] MAINT-001: `mutation_check.sh` wcina tabulatorami, pozostałe skrypty powłoki dwiema spacjami [verified]
**Status:** ✅ Fixed (2026-11-21)

**ID:** MAINT-001
**Location:** `tests/security/mutation_check.sh:35`
**Category:** Maintainability
**Effort:** trivial

**Problem:**
28 linii z tabulatorami. `scripts/doctor.sh`, `scripts/manifests.sh`, `scripts/secrets.sh` i `scripts/trivy.sh` mają 0 tabulatorów i wcinają dwiema spacjami (np. `scripts/trivy.sh:28`). Plan (Task 4, krok 1) wskazuje „wcięcia tabulatorem, jak `scripts/trivy.sh`”, ale `trivy.sh` nie używa tabulatorów. Nic tego nie wymusza (brak shfmt i `.editorconfig`).

**Impact:**
Repo traci jedną konwencję dla skryptów powłoki; różnica będzie się rozchodzić.

**Remediation:**
Wciąć skrypt dwiema spacjami na poziom (maksymalna głębokość 2), potem uruchomić shellcheck. Albo zostawić tabulatory i poprawić błędne „jak `scripts/trivy.sh`” w planie.

---

### [LOW] MAINT-002: Sprawdzenie narzędzi przed mutacją pomija `hubble` [verified]
**Status:** ✅ Fixed (2026-11-21)

**ID:** MAINT-002
**Location:** `tests/security/mutation_check.sh:34`
**Category:** Maintainability
**Effort:** trivial

**Problem:**
Pętla sprawdza tylko `kubectl` i `uv`, a komentarz w linii 20 wymienia „kubectl, hubble i uv”. Przebieg potrzebuje też `hubble`: fixture `hubble_server` (`tests/security/test_network_policies.py:289-291`) wywołuje `pytest.fail("Brak hubble w PATH…")`. Bez `hubble` skrypt usuwa `shop/default-deny`, uruchamia cały moduł (ok. 3 min), a dopiero potem kończy się `Nieoczekiwany wynik` z `ERROR` dla `test_hubble_shows_policy_denied_intruder_to_orders`.

**Impact:**
Brak narzędzia wygląda jak nieoczekiwany wynik mutacji, a klaster zostaje zmieniony bez potrzeby. Polityka wraca.

**Remediation:**

```bash
# Before
for tool in kubectl uv; do

# After
for tool in kubectl uv hubble; do
```

---

### [LOW] DOC-001: Wiersz testu mutacyjnego podaje tylko połowę powodu, dla którego pozostałe testy odmowy przechodzą [verified, obniżone z MEDIUM]
**Status:** ✅ Fixed (2026-11-21)

**ID:** DOC-001
**Location:** `docs/bezpieczenstwo.md:81`
**Category:** Documentation
**Drift-class:** decision
**Fix-policy:** needs-decision
**Decision:** A — W docs/bezpieczenstwo.md:81 (wiersz „| Z1 | test mutacyjny:”, kolumna „Kontrola”) zamień nawias „(frontend i orders mają własne polityki ingress, więc ich testy odmowy przechodzą)” na „(frontend i orders mają własne polityki ingress, a `allow-dns` izoluje egress każdego poda w shop, więc ich testy odmowy przechodzą)” i nic więcej nie zmieniaj w tym wierszu ani w żadnym innym pliku. [user, 2026-11-21]
**Verification-plan:** tool: Grep pattern=`ingress, więc ich testy odmowy` path=`docs/*.md;README.md;tests` → (empty), no match line in any top-level doc, the README or tests; tool: Grep pattern=`allow-dns.? izoluje egress każdego poda` path=`docs/*.md;tests/security/mutation_check.sh` → match lines in exactly three files: docs/architektura.md, docs/bezpieczenstwo.md (line 81) and tests/security/mutation_check.sh; Read docs/bezpieczenstwo.md:81 → excerpt contains „a `allow-dns` izoluje egress każdego poda w shop, więc ich testy odmowy przechodzą) | T26 |” (soft)
**Decision-pin:** block=1f1280577414d33a5b7495dd14dd10210d1d75924ab7058412a9f64d7e76fbe6 | docs/bezpieczenstwo.md=5694109896402fe984b91dceb8e6ad137503f6d6:edit
**Dispatch:** attempt 1 dispatched 2026-11-21
**Verification:** advisory — Grep `ingress, więc ich testy odmowy` (brak trafień), Grep `allow-dns.? izoluje egress każdego poda` (trzy pliki), re-read docs/bezpieczenstwo.md:81 (soft)

**Problem:**
Wiersz mówi „(frontend i orders mają własne polityki ingress, więc ich testy odmowy przechodzą)”. `test_orders_to_frontend_is_denied` przechodzi bez `shop/default-deny` tylko dzięki `allow-dns` (`podSelector: {}`, Egress, `deploy/base/networkpolicies/dns.yaml:11-12`), który izoluje egress orders; `frontend-ingress` wpuszcza dowolne źródło na TCP 8080 (`deploy/base/networkpolicies/shop.yaml:17-20`). Testy `test_egress_to_internet_is_denied` dla frontend i orders też przechodzą dzięki izolacji egress. Pełny powód jest w `docs/architektura.md:173` i w nagłówku `tests/security/mutation_check.sh:5-7`. Wiersz dotyczy połączeń do frontend i orders, więc „własne polityki ingress” jest dla nich poprawne; niedomówienie dotyczy egress.

**Impact:**
Czytelnik macierzy może uznać, że `frontend-ingress` blokuje orders → frontend, i dodać regułę egress dla orders, otwierając ten przepływ.

**Remediation:**
Dopisać powód egress: „(frontend i orders mają własne polityki ingress, a `allow-dns` izoluje egress każdego poda w shop, więc ich testy odmowy przechodzą)”, albo zastąpić nawias odsyłaczem do [Przepływy sieciowe](architektura.md#przepływy-sieciowe).

---

## Verification Summary

**Method:** Cross-domain correlation and adversarial review (Cross-Verifier + Challenger)

| Metric | Count |
|--------|-------|
| Findings verified | 5 |
| False positives removed | 0 |
| Severity adjustments | 1 |
| Cross-analysis findings | 0 |

### Cross-Analysis (Security <-> Quality)

- [CORRELATION-1] SEC-001 + MAINT-002: brakujące narzędzie wychodzi na jaw dopiero po usunięciu polityki, a przebieg kończy się przez ścieżkę przywracania, którą drugi Ctrl+C potrafi po cichu zabić. Naprawić osobno: `hubble` w pętli sprawdzającej (linia 34) i `trap '' INT TERM` na początku `on_exit` (linia 65). Oba LOW.
- [GAP-1] Nagłówek `tests/security/mutation_check.sh` (linie 8 i 12) oraz `README.md:76` obiecują przywrócenie polityki po Ctrl+C. Po poprawce SEC-001 obietnica jest prawdziwa, więc dokumentacji nie trzeba zmieniać.
- [GAP-2] Fixture `unlisted_pod` (`tests/security/test_network_policies.py:342-343`): drugi Ctrl+C podczas `kubectl delete` w `finally` zostawia pod `t26-unlisted`. Następny przebieg usuwa pozostałość (linie 336–337); przy przywróconej polityce pod jest izolowany.
- [GAP-3] `test_intruder_to_unlisted_pod_is_denied` sprawdza tylko ingress, a `allow-dns` powiela połowę Egress z `default-deny` w shop, loadgen i aiops. Wiersze Z1 (`docs/bezpieczenstwo.md:80-81`) cytują test mutacyjny jako dowód dla `default-deny`, ale dowodzi on tylko ingress.

### Challenged Findings

- DOC-001: obniżone z MEDIUM do LOW. Wiersz dotyczy połączeń do frontend i orders, a pełny powód jest w `docs/architektura.md:173` i nagłówku skryptu.
- SEC-002: przywrócone z odrzuconych przez audytora bezpieczeństwa (LOW); odrzucenie obejmowało tylko trwałe błędy.

### Rejected by auditors (self-falsification)

- Bandit B104: `http.server` na `0.0.0.0` — zamierzone (domyślnie może wybrać IPv6 `::`), pod testowy jest izolowany i krótkotrwały.
- Bandit B603/B607/B404: subprocess z częściową ścieżką — kubectl i hubble z PATH z mise z założenia, argumenty jako lista bez powłoki.
- Bandit B101: `assert` w testach pytest.
- Semgrep `uv-missing-dependency-cooldown` na `pyproject.toml:9` — sekcja nie zmieniona w tym diffie.
- pip-audit: opentelemetry-api 1.45.1, soupsieve 3.0.4, tornado 6.6 — wpisy w `uv.lock` sprzed gałęzi, osobna aktualizacja.
- Skrypt honoruje `KUBE_CONTEXT` i mógłby usunąć politykę na klastrze innym niż kind — decyzja z planu; brak klastra innego niż kind (`deploy/overlays/cloud` ma tylko `.gitkeep`).
- `http.server` listuje `/` obrazu orders — nic wrażliwego nie jest wystawione.
- Zapisany XSS w `reports/security.html` — pytest-html 4.2.0 escapuje wyjście testów.
- Wrażliwe dane w raportach JUnit i HTML — `reports/` jest w `.gitignore`.
- Wstrzyknięcie przez `KUBE_CONTEXT='$(KUBE_CONTEXT)'` — wartość pochodzi od osoby uruchamiającej make, jak w `Makefile:104`.
- Pusty wpis PATH z `mise bin-paths` — konwencja z `scripts/trivy.sh:21-23`.
- shellcheck `-o all` (SC2250/SC2292/SC2310) — style opcjonalne, SC2310 zamierzone.
- Długa funkcja `unlisted_pod_manifest` — literał deklaratywny, złożoność 1.
- Brak typów w `test_intruder_to_unlisted_pod_is_denied` — żaden test w module ich nie ma.
- Zduplikowany `kubectl()` — wzorzec modułów testowych, plan wskazał `test_pod_security.py:33-46`.
- Stałe `SETTLE_SECONDS` zamiast odpytywania — decyzja z planu (jak T12).
- Drugi Ctrl+C w pułapce bez komunikatu — ten sam defekt co SEC-001.
- Fixture `unlisted_pod` zwraca IP — opisane w docstringu, nazwa z planu.
- `README.md:76` podaje tylko test poda bez reguły — streszczenie niepełne, ale prawdziwe.
- „Stan na 10.11.2026” w `docs/bezpieczenstwo.md:3` — celowo bez zmian (plan, Task 5).
- Brak etykiety `t26-unlisted` w tabeli etykiet — celowo, etykieta nie pasuje do żadnego selektora.
- `--strict-markers` poza `pyproject.toml` — żaden dokument nie opisuje rejestracji markerów.
- Oczekiwany zbiór porażek w dwóch dokumentach — konwencja macierzy; oba zgodne z `mutation_check.sh:28-29`.
- Komentarz w `default-deny.yaml:3` — nadal prawdziwy, plik poza zakresem.
- `docs/architektura.md:173` „oba pody mają własne polityki ingress” — klauzula `allow-dns` domyka wyjaśnienie.

### Doctrine-gap candidates

- Skrypty usuwające kontrolę z klastra nie mają reguły ograniczającej kontekst kubectl (przed T29, nakładka cloud).
- Brak reguły stylu i lintu dla powłoki: brak `.editorconfig`, `shfmt` i shellcheck w `make lint` i CI.
- Każdy z 5 modułów testów klastra ma własny `kubectl()`, dwa są już identyczne (wariant ze `stdin`).

### Out of scope (scope check)

None
