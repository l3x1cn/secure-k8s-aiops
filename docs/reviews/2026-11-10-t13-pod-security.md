# Code Review: t13-pod-security

Review scope: changes since 249cbc5 (7 files)

Zakres: `249cbc57612717cd49710a74635b2df218919067..HEAD` (3 commity zadań), dostarczone z `docs/plans/2026-11-10-t13-pod-security.md`.

**Podsumowanie:** 0 CRITICAL, 0 HIGH, 0 MEDIUM, 1 LOW. Audyt bezpieczeństwa: bez uwag (gitleaks, Semgrep, Bandit, Trivy config, pip-audit). Weryfikacja planu na klastrze: `1 failed, 4 passed` przed `make deploy` T13 (dokładnie dwie linie `/tmp bez wolumenu emptyDir`), `92 passed` po wdrożeniu, mutacja etykiet PSA `2 failed, 3 passed`, mutacja `readOnlyRootFilesystem: false` `1 failed, 4 passed`, `make down && make up` kończy się `92 passed`, `RESTARTS` bez zmian po 2 minutach. QA pominięte na prośbę właściciela (brak `.av/config.toml`, zmiana bez powierzchni FE/BE).

---

### [LOW] MAINT-001: sprawdzenie UID 10001 wyłącza się bez błędu, gdy zmieni się prefiks obrazów projektu
**Status:** ✅ Fixed (2026-11-10)

**ID:** MAINT-001
**Location:** `tests/security/test_pod_security.py:26`
**Category:** Maintainability
**Effort:** trivial

**Problem:**
„Własny obraz” to `container["image"].startswith(OWN_IMAGE_REPO)`, a `OWN_IMAGE_REPO` jest zakodowaną na stałe kopią `IMAGE_REPO` (`Makefile:14`, `.github/workflows/images.yml:23`). Notki „zmieniaj razem” przy tej wartości (`Makefile:13`, `images.yml:22`) nie wymieniają testu. Gdy ścieżka repozytorium się zmieni, a stała nie, żaden kontener nie pasuje: warunek `run_as_user != OWN_UID` nigdy się nie wykonuje i test przechodzi. Pusta lista podów jest strzeżona (`assert pods`, linia 136), ta gałąź nie.

**Impact:**
`docs/architektura.md` mówi, że UID 10001 pilnuje test. Trivy KSV-0020 i KSV-0021 (LOW) wymagają tylko UID powyżej 10000, a `trivy config` w CI dochodzi dopiero w T15. Po zmianie prefiksu nic nie przypina dokładnego UID, a żaden test nie czerwienieje. `runAsNonRoot` nadal jest sprawdzany dla każdego kontenera, więc root pozostaje wykluczony.

**Remediation:**

```python
# Before (linie 134-137)
    listed = get_json("pods", "-A", "-l", PART_OF)
    pods = [p for p in listed["items"] if "deletionTimestamp" not in p["metadata"]]
    assert pods, f"brak podów z etykietą {PART_OF} (make deploy)"
    problems = []

# After
    listed = get_json("pods", "-A", "-l", PART_OF)
    pods = [p for p in listed["items"] if "deletionTimestamp" not in p["metadata"]]
    assert pods, f"brak podów z etykietą {PART_OF} (make deploy)"
    images = [c["image"] for p in pods for c in p["spec"]["containers"]]
    # Bez obrazu projektu sprawdzenie UID nic nie obejmuje (np. po zmianie IMAGE_REPO).
    assert any(image.startswith(OWN_IMAGE_REPO) for image in images), images
    problems = []
```

Opcjonalnie dopisać test do notek „zmieniaj razem” w `Makefile:13` i `.github/workflows/images.yml:22`. Liczba testów zostaje `92`.

---

## Verification Summary

**Method:** Cross-domain correlation and adversarial review (Cross-Verifier + Challenger)

| Metric | Count |
|--------|-------|
| Findings verified | 1 |
| False positives removed | 0 |
| Severity adjustments | 0 |
| Cross-analysis findings | 0 |

### Cross-Analysis (Security <-> Quality)

- Brak ustaleń bezpieczeństwa i dokumentacji, więc brak kompozytów. Jedyne ustalenie (MAINT-001) pochodzi z audytu jakości.
- Luka pokrycia: ryzyko MAINT-001 ograniczone do LOW. Po wyłączeniu sprawdzenia root nadal jest wykluczony (`runAsNonRoot` w teście i PSA restricted); zostaje niepinowany UID inny niż 10001 (Trivy KSV-0020 i KSV-0021, w CI od T15).
- Luka pokrycia: notki „zmieniaj razem” w `Makefile:13` i `images.yml:22` nie wymieniają testu; ujęte w remediacji MAINT-001.
- Luka pokrycia: wiersz Z3 w `docs/bezpieczenstwo.md:89` przypisuje UID 10001 testowi, który sprawdza go tylko dla obrazów projektu; `docs/architektura.md:80` mówi to wprost (UID obrazów zewnętrznych sprawdza tylko review), więc nie jest to usterka.

### Challenged Findings

- MAINT-001 potwierdzone na LOW; brak usunięć i zmian wagi. Odrzucenie „Z3 pod UID 10001 przypisany testowi” stoi, choć sam powód jest słaby: KSV-0020 i KSV-0021 to LOW i nie zatrzymują bramki HIGH/CRITICAL. Pozostałe powody (inne wiersze macierzy z częściowym pokryciem, `architektura.md:80`) wystarczają.

### Rejected by auditors (self-falsification)

- Bandit B404/B603/B607/B108/B101 — lista argumentów bez powłoki, `/tmp` to tylko ścieżka montowania porównywana ze specyfikacją poda, asercje pytest.
- Intruder z zapisywalnym `/tmp` — zapisana decyzja planu; exec ma tylko cluster-admin, limit 16Mi, system plików root pozostaje tylko do odczytu.
- monitoring z `audit: privileged` — decyzja właściciela i zaakceptowane ryzyko R1; kind nie ma logu audytu.
- Test hardening nie sprawdza `privileged`, `hostNetwork`, `hostPID`, `hostPath`, ephemeral containers — odrzuca je PSA `enforce: restricted`, co dowodzi `test_privileged_pod_is_rejected`.
- Wybór podów tylko po etykiecie `part-of` — ta sama konwencja w `test_rbac.py` i `Makefile`.
- Namespace'y bez etykiet PSA (default, nowe) wracają do privileged — stan sprzed zmiany, poza zakresem (R3, T29).
- Etykiety bez `*-version` — decyzja planu (domyślnie `latest`, jak w T04).
- Trivy KSV-0013, KSV-0110, KSV-0125 — znane uwagi MEDIUM i LOW, jak na `main`.
- Trzecia kopia `kubectl()`, `get_json()` i fixture `cluster` — decyzja planu, ten sam kandydat co w przeglądzie T12.
- Złożoność cyklomatyczna `hardening_problems` (14) — siedem niezależnych `if`, ruff projektu nie wybiera C901.
- Brak adnotacji typów w funkcjach testowych i gołe `dict` — konwencja projektu, ruff nie wybiera ANN.
- Brak testów jednostkowych dla `hardening_problems` — żaden helper w `tests/security` ich nie ma; mutacje z Verification przechodzą przez ten kod na klastrze.
- Test przechodzi, gdy workload nie ma podów — `make deploy` kończy się błędem rolloutu, gdy PSA odrzuca szablon poda.
- Brak testu etykiet `warn` i `audit` — założenie planu z zapisaną alternatywą.
- Brak notki „zmieniaj razem” przy `RESTRICTED_NAMESPACES` — `namespaces.yaml` wskazuje test, tabela w architekturze wiąże listę.
- Powtórzone wyjaśnienie warn i audit w manifeście, dokumentacji i teście — projekt trzyma uzasadnienie w obu miejscach (jak `sre-readonly.yaml` i `architektura.md`).
- Dodatkowe reguły ruff (PLW1510, PERF401, S108) — poza regułami projektu, S108 to fałszywy alarm.
- 8 uwag LOW do dokumentacji (m.in. data „`main` po T13” przed scaleniem, uproszczenie dziedziczenia `warn`, przyszłe charty w monitoring, `docs/bezpieczenstwo.md` poza listą plików Task 3) — wszystkie odrzucone po weryfikacji; zmiana macierzy w tym PR wynika z jej własnej reguły (`docs/bezpieczenstwo.md:5`, `:120`).

### Doctrine-gap candidates

- Brak reguły, że każdy pod w namespace'ach aplikacji nosi etykietę `app.kubernetes.io/part-of=secure-k8s-aiops`; pod bez niej omija sprawdzenia, których PSA nie wymusza (`readOnlyRootFilesystem`, UID 10001, `/tmp`).
- Brak reguły współdzielenia helperów między modułami `tests/security` (`kubectl()`, `get_json()` i fixture `cluster` w trzech kopiach, a kopie zaczęły się różnić: ta ma parametr `stdin`).
- Brak reguły, że test wybierający zakres wzorcem (prefiks obrazu, etykieta) musi oblewać, gdy wzorzec nic nie obejmuje.

### Out of scope (scope check)

None.
