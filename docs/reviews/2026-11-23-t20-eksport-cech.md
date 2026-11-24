Review scope: changes since b8e04e6 (22 files)

# Code review: gałąź `t20-eksport-cech` (b8e04e6..HEAD)

Dostarczone z `docs/plans/2026-11-23-t20-eksport-cech.md`. Zakres: `.github/dependabot.yml`, `README.md`, `aiops/notebooks/02-eda.ipynb`, `aiops/pyproject.toml`, `aiops/src/aiops/` (`__init__`, `export`, `features`, `prometheus`), `aiops/tests/` (`__init__`, `conftest`, `test_export`, `test_features`, `fixtures/query_range.json`, `fixtures/record.py`), `chaos/Dockerfile`, `services/frontend/Dockerfile`, `services/orders/Dockerfile`, `docs/architektura.md`, `docs/detekcja.md`, `docs/testing/plans/2026-11-23-t20-prometheus-feature-export-test-plan.md`, `pyproject.toml`, `uv.lock`.

**Wynik:** 0 CRITICAL, 0 HIGH, 1 MEDIUM, 2 LOW. Żaden wpis nie blokuje scalenia.

Skanery: gitleaks i trufflehog (brak wycieków), Semgrep i Bandit (trafienia odrzucone), pip-audit i Trivy na `uv.lock` (3 CVE i 1 MEDIUM w wpisach, których zmiana nie dotyka; nowe pakiety `pyarrow` 26.0.1, `pandas`, `numpy`, `scikit-learn` bez znanych podatności), `uv lock --check` (zgodny), ruff (czysto), docs-drift (0 nowych trafień). Obrazy frontend, orders i fault-runner nie instalują `aiops`, `pyarrow`, `pandas`, `numpy` ani `scikit-learn` (`uv export --no-dev --package …`).

## Findings

### [MEDIUM] DOC-001: Kontrakt mówi, że brak ewaluacji reguły daje NaN, ale trzy cechy `http_*` dostają wtedy 0 [verified]
**Status:** ✅ Fixed (2026-11-24)


**ID:** DOC-001
**Location:** `docs/architektura.md:216` (to samo twierdzenie w `README.md:145`)
**Category:** Documentation
**Drift-class:** decision
**Fix-policy:** needs-decision
**Decision:** A — in docs/architektura.md line 216 (the bullet starting "wartość w kroku t to ostatnia ewaluacja reguły") replace the sentence "Brak ewaluacji (np. restart Prometheusa) daje NaN, a nie wartość sprzed kilku minut z 5-minutowego lookbacku" with one saying that a missed evaluation gives NaN rather than a value from the 5-minute lookback, except in the three http_* features, where every missing value (no series, NaN, missed evaluation) is 0 so the gap shows in the other features, and in README.md line 145 replace "brak ewaluacji reguły to NaN" with "brak ewaluacji pozostałych reguł to NaN"; change no code or test [user, 2026-11-24]
**Verification-plan:** grep -n "poza trzema cechami" docs/architektura.md → one match on the line that also contains "lookbacku"; grep -c "brak ewaluacji reguły to NaN" README.md → 0; grep -c "brak ewaluacji pozostałych reguł to NaN" README.md → 1
**Verification:** hard — grep -n "poza trzema cechami" docs/architektura.md matched line 216 together with "lookbacku"; grep -c "brak ewaluacji reguły to NaN" README.md returned 0; grep -c "brak ewaluacji pozostałych reguł to NaN" README.md returned 1

**Problem:**
`docs/architektura.md:216` mówi dla każdej cechy: „Brak ewaluacji (np. restart Prometheusa) daje NaN”, a `README.md:145`: „brak ewaluacji reguły to NaN”. W kodzie krok bez próbki staje się NaN przy wyrównaniu do siatki (`aiops/src/aiops/features.py:69-77`), po czym linia 78 (`frame[ZERO_WITHOUT_TRAFFIC] = frame[ZERO_WITHOUT_TRAFFIC].fillna(0.0)`) wpisuje 0 w `http_requests_rate1m`, `http_errors_ratio_rate1m` i `http_latency_p95_seconds_1m` bez względu na przyczynę. `docs/architektura.md:217` podaje tylko dwa powody zera: brak serii przed pierwszym żądaniem i NaN bez ruchu. Docstring funkcji (`features.py:55-56`: „Brak ewaluacji reguły to NaN, poza ZERO_WITHOUT_TRAFFIC”) jest zgodny z kodem; rozjazd dotyczy dokumentacji. Odtworzone na nagraniu: po usunięciu kroków 5–7 każdej reguły frontendu `cpu_usage_ratio_of_limit` jest NaN, a trzy kolumny `http_*` mają 0; `max_gap_seconds` zwraca `{'frontend': 90, 'orders': 0}`.

**Impact:**
Sekcja jest kontraktem ramki dla T23 i T24 na poziomie komórek. Restart Prometheusa zostawia pozostałe sześć kolumn jako NaN, więc `max_gap_seconds` (warunek na wierszu) i odrzucenie wierszy z NaN przed `fit` nadal wykrywają lukę. Konsument, który imputuje kolumna po kolumnie albo czyta zero `http_*` jako brak ruchu, odczyta jednak lukę jako spadek ruchu do zera. [INFERENCE] Awaria samego scrape'u `/metrics` aplikacji przy działających regułach cAdvisor dałaby `http_*` = 0 bez żadnej luki.

**Remediation:**
Najpierw decyzja, co ma się zmienić.
- Zero ma zostać (zgodnie z „Assumptions & contingencies” planu i docstringiem): dopisać wyjątek w `docs/architektura.md:216-217`, np. „Brak ewaluacji daje NaN, poza trzema cechami `http_*`: każdy ich brak wartości (brak serii, NaN, brak ewaluacji) to 0, więc lukę pokazują pozostałe cechy”, i zawęzić `README.md:145` do „brak ewaluacji pozostałych reguł to NaN”. Dodać test: brak jednej próbki w środku serii `http_*`, która poza tym ma dane (dziś nie jest pokryty, zob. MAINT-002).
- Brak ewaluacji ma zostać NaN także w `http_*`: zmienić `fetch_features`, żeby wypełniał zerem tylko serię nieobecną w całym oknie albo NaN zwrócone przez API, a nie brakujące kroki siatki. Wtedy trzeba poprawić też komentarz i docstring w `features.py:30-32` i `features.py:55-56`; dokumentacja zostaje bez zmian.

---

### [LOW] MAINT-001: Treść błędu bez `errorType` albo niebędąca obiektem JSON kończy `PrometheusError` wyjątkiem `KeyError` lub `AttributeError` [verified]
**Status:** ✅ Fixed (2026-11-23)


**ID:** MAINT-001
**Location:** `aiops/src/aiops/prometheus.py:61`
**Category:** Maintainability
**Effort:** trivial

**Problem:**
Linia 67 czyta `body['errorType']` zawsze, gdy treść zawiera `"error"`. Odpowiedź `{"error": "unauthorized"}` z bramki albo proxy pod `--prometheus-url` rzuca `KeyError`, a treść 2xx, która nie jest obiektem JSON, rzuca `AttributeError` na `body.get` (linia 65). Docstring `PrometheusError` (linie 17–18) obiecuje ten wyjątek dla każdej odpowiedzi innej niż sukces. Odtworzone na `MockTransport`: 401 z `{"error": "unauthorized"}` daje `KeyError: 'errorType'`. Prometheus zawsze zwraca `errorType` razem z `error`, więc błąd wywołuje tylko serwer inny niż Prometheus.

**Impact:**
CLI nadal kończy się kodem 1 bez pliku (wyjątek leci przed `to_parquet`, `export.py:74-75`), ale zamiast jednej linii na stderr jest traceback. Wywołujący bibliotekę (T24 w klastrze) dostaje `KeyError`/`AttributeError` zamiast `PrometheusError`, więc jego `except PrometheusError` jej nie złapie.

**Remediation:**

```python
# Before
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.is_error or body.get("status") != "success":
            detail = (
                f"{body['errorType']}: {body['error']}"
                if "error" in body
                else response.text
            )

# After
        try:
            body = response.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        if response.is_error or body.get("status") != "success":
            detail = (
                f"{body.get('errorType', 'error')}: {body['error']}"
                if "error" in body
                else response.text
            )
```

---

### [LOW] MAINT-002: Zadeklarowane ścieżki błędów nie mają testów: `ValueError` dla czasu bez strefy, treść błędu niebędąca JSON-em i brak próbki w środku serii `http_*` [verified]
**Status:** ✅ Fixed (2026-11-23)


**ID:** MAINT-002
**Location:** `aiops/tests/test_features.py:50`
**Category:** Maintainability
**Effort:** easy

**Problem:**
1. `fetch_features` rzuca `ValueError("start and end must be timezone-aware")` (`aiops/src/aiops/features.py:58-59`). `docs/architektura.md:213` („czasy ze strefą”) i plan QA (`docs/testing/plans/2026-11-23-t20-prometheus-feature-export-test-plan.md:42`) traktują to jako kontrakt, na którym polega T24; w `aiops/tests` nie ma żadnego testu.
2. Gałąź treści innej niż JSON (`prometheus.py:62-64` → `response.text`, linia 69) nie ma testu; to ścieżka odpowiedzi 502 z proxy albo port-forwardu. Ten sam blok (`prometheus.py:61-69`) obsługuje też wejścia z MAINT-001 (JSON z `error` bez `errorType`, JSON niebędący obiektem), a żadne z trzech kształtów nie jest sprawdzane przez `test_export.py`.
3. `test_missing_evaluations_are_gaps` (`test_features.py:78-96`) usuwa próbki tylko z `cpu_usage_ratio_of_limit`, a `test_http_features_without_traffic_are_zero` (`:50`) obejmuje tylko serię nieobecną albo całą z NaN. Brak jednej próbki w środku istniejącej serii `http_*` (przedmiot DOC-001) nie ma testu.

**Impact:**
Kontrakt ramki, na którym opierają się T23 i T24, ma niesprawdzone klauzule; zmiana zero-fill w `features.py:78` w którąkolwiek stronę albo usunięcie `ValueError` przejdzie testy bez zmian.

**Remediation:**

```python
def test_naive_times_are_rejected_before_any_request(window):
    start, end = window
    transport = httpx.MockTransport(lambda r: pytest.fail(f"unexpected {r.url}"))
    with PrometheusClient(URL, transport=transport) as client:
        with pytest.raises(ValueError, match="timezone-aware"):
            fetch_features(client, start.replace(tzinfo=None), end)
```

Do `test_export.py` dodać przypadki `MockTransport` zwracające `httpx.Response(502, text="<html>Bad Gateway</html>")` i `httpx.Response(401, json={"error": "unauthorized"})`; każdy ma dać kod 1, komunikat na stderr i brak pliku. Do `test_features.py` dodać przypadek z usuniętą próbką w środku serii `http_*` i asercją wybranej w DOC-001 wartości oraz `max_gap_seconds`.

---

## Verification Summary

**Method:** Cross-domain correlation and adversarial review (Cross-Verifier + Challenger)

| Metric | Count |
|--------|-------|
| Findings verified | 3 |
| False positives removed | 1 |
| Severity adjustments | 0 |
| Cross-analysis findings | 0 |

### Cross-Analysis (Security <-> Quality)
- Brak korelacji z udziałem bezpieczeństwa: audyt bezpieczeństwa nie zgłosił żadnego wpisu.
- Jedyna para międzydomenowa to DOC-001 (dokumentacja) i MAINT-002 (testy): obie dotyczą kontraktu `fetch_features` dla T23 i T24. Wymagają dwóch osobnych poprawek (decyzja o zerach `http_*` oraz testy), więc nie powstał composite.
- Wpływ MAINT-001 dotyczy kontraktu biblioteki (`PrometheusError` dla T24), nie kontraktu CLI: CLI nadal kończy się kodem 1 bez pliku.

### Challenged Findings
- Błąd `mypy` `arg-type` w `aiops/src/aiops/prometheus.py:51-58` (`params` jako `dict[str, object]`) — false positive: projekt nie ma sprawdzania typów (`make lint` to tylko `ruff check` i `ruff format --check`), wcześniejsze przeglądy (`docs/reviews/2026-11-07-t11-rbac.md:301`, `docs/reviews/2026-11-22-t17-logi-zdarzenia.md:265`) odrzucały takie wpisy z tego samego powodu, a w czasie działania nie ma wady. Brak narzędzia pokrywa luka doktrynalna poniżej.
- Część MAINT-002: `pytest.raises(SystemExit)` bez sprawdzania kodu 2 (`aiops/tests/test_export.py:66`) — nie utrzymano, bo powtarza styl `chaos/tests/test_cli.py:89,94` i jest zapisana jako luka doktrynalna.

### Rejected by auditors (self-falsification)
- Bandit B404/B603/B607 `subprocess` z `kubectl` w `aiops/tests/fixtures/record.py:34` — lista argumentów bez powłoki, ten sam wzorzec w `tests/observability/`.
- Bandit B101 `assert` w testach — tak pytest sprawdza wyniki.
- Semgrep `uv-missing-dependency-cooldown` w `pyproject.toml:9` — linia niezmieniona; jedyny nowy pakiet (`pyarrow` 26.0.1) wydano 2026-11-03, co najmniej 7 dni przed `uv lock`.
- Znane CVE w `uv.lock` (`opentelemetry-api`, `soupsieve`, `tornado`) — wpisy niezmienione przez ten diff.
- Niezwalidowany kształt odpowiedzi Prometheusa (CWE-755) — zawarty w MAINT-001 jako odporność, nie podatność.
- Zapis do dowolnej ścieżki `--out` (CWE-73) — ścieżka z własnego argumentu operatora.
- HTTP bez TLS do Prometheusa (CWE-319) — domyślny adres to `kubectl port-forward` na localhost; adres w klastrze tylko opisany dla T24.
- Pakiet `aiops` obcy na PyPI (dependency confusion) — nazwa rozwiązywana wyłącznie z workspace'u (`pyproject.toml:22`, `uv.lock:23`), Dependabot go pomija (`.github/dependabot.yml:22`).
- Zależności ML w obrazach usług — obrazy instalują tylko własny pakiet (`--package <usługa>`).
- Dane klastra w notebooku i nagraniu — etykiety tylko `__name__`, `namespace`, `service`; wyniki bez ścieżek, adresów IP i tokenów.
- DIP: `fetch_features` zależy od konkretnego `PrometheusClient` — ten sam wzorzec co `main(argv, transport)` w `chaos/src/fault_runner/cli.py`.
- Mieszanie logiki i I/O w `fetch_features` — 31 linii, w pełni pokryte przez `FakePrometheus`.
- Zero-fill `http_*` ukrywa awarie scrape'u — świadoma decyzja planu (Approach „Brak ruchu HTTP”, Assumptions); strona dokumentacyjna to DOC-001.
- Kolizja nazw `aiops/tests/__init__.py` z `tests/` w korzeniu — sprawdzone: oba porządki zbierają 143 testy.
- `CONTRACT` i `HTTP_COLUMNS` powielają `FEATURES` — celowe przypięcie kontraktu (komentarz `test_features.py:7-8`).
- Nieoznaczone typy parametrów testów (ruff ANN) — konwencja projektu (zestaw reguł E4/E7/E9/F).
- p95 prawie stałe (0,00475 s) — układ kubełków w niezmienionym `libs/observability/src/observability/__init__.py:26`; do inżynierii cech w T23.
- `OSError` z `mkdir` i `to_parquet` niezłapany w `export.main` — poza kontraktem CLI z planu; kod wyjścia i tak niezerowy.
- Zduplikowane serie usługi nadpisywane po cichu — każda reguła agreguje `sum by (namespace, service)`.
- Pomocnik proxy `kubectl` powtarza `tests/observability` — ok. 11 linii.
- `max_gap_seconds` pętlą Pythona — najwyżej 8 640 wierszy na usługę przy retencji 3 dni.
- Limit 11 000 punktów Prometheusa — odpowiedź 400 kończy eksport kodem 1 bez pliku.
- Zdanie „README opisuje zapis do `aiops/data/`”, opis siatki „od start do end”, komentarz w `pyproject.toml` o `test_traffic.py`, odwołanie do sekcji „Dane i cechy” w `export.py` — nie są nieprawdziwe.
- Twierdzenie „`last_over_time` usuwa nazwę metryki” w `docs/plans/2026-11-23-t20-eksport-cech.md:55` — poza zakresem (plik z bazy); nagranie zachowuje `__name__`, a kod i dokumentacja tego nie powtarzają.

### Doctrine-gap candidates
- Limit 7 dni dla ręcznego `uv lock` wymusza tylko tekst planu: Dependabot (`.github/dependabot.yml:17-18`) i `platform/versions.env:16` mają cooldown, a `[tool.uv]` nie ma `exclude-newer`. Ten branch jako pierwszy dodaje ręcznie nowy pakiet (`pyarrow`).
- Brak sprawdzania typów w narzędziach: `make lint` to tylko ruff. Kandydat na regułę: krok mypy lub basedpyright w `make lint`.
- Brak konwencji kodów wyjścia argparse w testach: testy `chaos` i `aiops` akceptują każdy `SystemExit`. Kandydat na regułę: testy CLI sprawdzają `excinfo.value.code`.

### Out of scope (scope check)
None
