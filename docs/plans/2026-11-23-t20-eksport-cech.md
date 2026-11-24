# T20 · Eksport danych i cechy z Prometheusa (issue #20)

## Context

Issue #20 (R4 AI/ML, Sprint 2, zależy od T16 i T18 — oba scalone): zbiór danych bazowych do uczenia i analizy. Zakres: pakiet `aiops` (`aiops/src/aiops/`) z klientem zapytań zakresowych Prometheusa i ramką 9 cech z reguł `service:*` (krok 30 s, osobno `frontend` i `orders`); CLI `uv run python -m aiops.export --from <ISO> --to <ISO> --out aiops/data/<nazwa>.parquet` (katalog poza git); notebook `aiops/notebooks/02-eda.ipynb` (rozkłady, korelacje, sezonowość na co najmniej 2 h ruchu bazowego); testy jednostkowe na nagranych odpowiedziach Prometheusa (fixtures JSON). Kryteria akceptacji:
1. eksport 2 h ruchu bazowego daje 9 kolumn cech × 2 usługi, bez luk dłuższych niż 1 min;
2. notebook EDA wykonuje się od początku do końca.

Komentarz T16 w #20: reguły mają etykiety `namespace="shop"` i `service` ∈ {frontend, orders}; scrape 15 s, reguły co 30 s, retencja 3 dni na PVC (przeżywa restart poda, nie `make down`); bez ruchu HTTP `http_errors_ratio` i `http_latency_p95_seconds` mają NaN, a reguły `http_*` nie mają serii do pierwszego żądania — eksport musi to obsłużyć; zapytania z hosta przez `make prometheus` albo proxy API serwera (wzór w `tests/observability/test_metrics.py`).

Stan docelowy: pakiet workspace'u `aiops` (httpx, numpy, pandas, pyarrow, scikit-learn) z modułami `aiops.prometheus`, `aiops.features` i `aiops.export`, których T23 i T24 używają dalej; `make unit` obejmuje `aiops/tests`; obrazy frontend, orders i fault-runner dalej się budują; Dependabot pomija pakiet `aiops`; notebook EDA z wynikami z klastra jest w git; README, `docs/architektura.md` i `docs/detekcja.md` opisują kontrakt ramki cech i wyniki EDA.

### Ustalone fakty (sprawdzone 2026-11-23)

- **Repozytorium:** bieżąca gałąź `t17-logi-zdarzenia` (HEAD `e661cee`; PR #66 T17: APPROVED, merge state CLEAN, jeszcze nie scalony), `origin/main` = `0056ffb`. Numery linii w planie pochodzą z `e661cee`; po scaleniu #66 ta sama treść jest na `main`.
- **Klaster nie działa:** brak `/var/run/docker.sock` (daemon Dockera wyłączony), `kubectl --context kind-secure-k8s-aiops` → connection refused. Danych bazowych w Prometheusie nie ma; trzeba je zebrać od nowa (eksport 2 h z 5 min rozgrzewki wymaga ok. 2 h 7 min ruchu Locusta).
- **Reguły:** `deploy/observability/recording-rules.yaml` — grupa `service` z `interval: 30s` (linia 19), 9 reguł z etykietami `namespace="shop"` i `service`; NaN i brak serii `http_*` bez ruchu (linie 8–9); `policy_drops` bez odrzuceń = 0 (`or … up * 0`, linia 136). kube-prometheus-stack 92.17.1 z operatorem v0.94 (`platform/versions.env:11-13`; Prometheus 3.x — wniosek z wersji operatora, niesprawdzony na klastrze), `scrapeInterval: 15s`, `evaluationInterval: 30s`, retencja 3d/4GB (`deploy/observability/values/kube-prometheus-stack.yaml:19-31`). Zwykły selektor w `query_range` bierze ostatnią próbkę z 5 min (domyślny lookback; wartości chartu go nie zmieniają), więc luki krótsze niż 5 min byłyby w eksporcie niewidoczne. `last_over_time(<reguła>[30s])` w kroku 30 s daje jedną ewaluację reguły na krok; to założenie sprawdza nagranie w Task 3 (21 próbek na serię w 10 min).
- **Nazwy kolumn:** `aiops/notebooks/01-prototyp.ipynb`, komórka 1: `FEATURES` = nazwy reguł bez `service:` z `:` → `_` (`cpu_usage_ratio_of_limit`, …, `policy_drops_rate1m`), `SERVICES = ("frontend", "orders")`; parametry ruchu bazowego w `simulate()` (komórka 3); konwencje notebooka: `pd.set_option("display.precision", 3)`, `plt.rcParams["figure.dpi"] = 60`, kernelspec `python3`.
- **Workspace uv** (`pyproject.toml`): `dependencies = ["chaos", "frontend", "orders"]` (7), komentarz o dopisaniu `aiops` w T20 i do ignore Dependabota (14–16), `members` (18), `[tool.uv.sources]` (20–23), grupa `dev` z `numpy`, `pandas`, `scikit-learn` i komentarzem „numpy/pandas/scikit-learn przejdą do zależności pakietu aiops w T20” (25–39), `testpaths = ["chaos", "libs", "services"]` (44), `addopts = ["--import-mode=importlib", "--strict-markers"]` (47). Pakiety: `uv_build>=0.13.1,<0.14`, `requires-python = "==3.13.*"` (`chaos/pyproject.toml`). numpy używa też `tests/observability/test_traffic.py`.
- **Dockerfile'y:** `chaos/Dockerfile`, `services/frontend/Dockerfile` i `services/orders/Dockerfile` kopiują przed `uv sync --frozen` `pyproject.toml` każdego członka workspace'u (linie 15–19, komentarz „inaczej `uv sync --frozen` się przerywa”). Nowy członek bez tej linii psuje `make images` i workflow Images.
- **pytest i katalog `aiops/`:** w kopii układu (`aiops/src/aiops`, `aiops/tests` bez `__init__.py`) pytest 9.1.1 z `--import-mode=importlib` nazywa moduły testów `aiops.tests.*`, importuje rodzica `aiops` z katalogu `aiops/` jako namespace i zasłania zainstalowany pakiet: `ModuleNotFoundError: No module named 'aiops.features'`. Z `aiops/tests/__init__.py` moduły nazywają się `tests.*` i testy przechodzą. W repo nie ma żadnego `conftest.py` ani `tests/__init__.py`.
- **Zależności:** `uv.lock` nie ma pyarrow; pandas 3.1.1 wymaga do Parquet pyarrow ≥ 16.0.0 (`pandas/compat/_optional.py`). pyarrow 26.0.1 wydany 2026-11-03 (≥ 7 dni, jak cooldown Dependabota), koła cp313 dla manylinux x86_64/aarch64, macOS x86_64/arm64 i Windows. `aiops` na PyPI to obcy pakiet (0.0.0.56), więc Dependabot musi go pomijać (`.github/dependabot.yml:19-25`).
- **Wzorce:** CLI jak `chaos/src/fault_runner/cli.py` (argparse z pomocą po polsku, komunikaty błędów po angielsku, `main(argv, transport)`, testy z `httpx.MockTransport` w `chaos/tests/test_cli.py`); zapytania przez proxy API serwera (`kubectl get --raw /api/v1/namespaces/monitoring/services/prometheus-operated:9090/proxy/...`, `tests/observability/test_metrics.py:21-63`); start Locusta: pod `app.kubernetes.io/name=locust` w loadgen (`tests/observability/test_traffic.py:65-82`). httpx 0.28.1 dokleja ścieżkę żądania do ścieżki `base_url` (`httpx/_client.py:404-410`). nbconvert wykonuje notebook w jego katalogu (`nbconvert/exporters/exporter.py:185-188`), więc `../data/baseline.parquet` to `aiops/data/baseline.parquet`.
- **Git i Docker:** `.gitignore` ma `aiops/data/`, `reports/` i `*.nbconvert.ipynb`; `.dockerignore` ma `aiops/data` i `**/tests`. `deploy/base/networkpolicies/aiops.yaml` już pozwala aiops → Prometheus :9090 (T24).
- **Testy:** `make unit` zbiera dziś 96 testów.
- **Szkic kodu z tego planu sprawdzony** w kopii układu poza repo: moduły, testy i nagrywarka przechodzą `ruff format --check` i `ruff check` z konfiguracją repo (ruff 0.17.3); 11 testów przechodzi z pandas 3.1.1, httpx 0.28.1 i pytest 9.1.1 (Parquet zastąpiony pickle, bo w `.venv` nie ma jeszcze pyarrow); komórki notebooka wykonują się bez ostrzeżeń (`-W error`) na syntetycznej ramce o tym samym kształcie; CLI: `--help` działa, czas bez strefy → kod 2, brak Prometheusa → kod 1 bez pliku.
- **Konwencje:** gałąź `txx-krotki-opis`, PR z `Closes #N`, commity `typ(zakres): opis (Txx)`; plan trafia do `docs/plans/<data>-<slug>.md` commitem `docs: add delivery plan <slug>`.

## Warunek wstępny (główny agent, przed startem delivery)

W korzeniu repozytorium:

```bash
git status --short   # pusto
git fetch origin
git cat-file -e origin/main:deploy/observability/values/loki.yaml && echo T17-na-main
```

- `T17-na-main` → `git switch main && git pull --ff-only && git switch -c t20-eksport-cech`.
- Brak (PR #66 nie scalony) → `git switch -c t20-eksport-cech origin/t17-logi-zdarzenia`; PR T20 powstaje dopiero po scaleniu #66 (sekcja „Po dostarczeniu”).
- Docker: `docker info >/dev/null && echo docker-ok`; bez daemona uruchom Dockera (np. `sudo systemctl start docker`) i powtórz.
- Klaster: `mise exec -- kind get clusters` (`secure-k8s-aiops`) i `mise exec -- kubectl --context kind-secure-k8s-aiops get --raw /readyz` (`ok`). Brak klastra albo `readyz` inne niż `ok` → `make up`; gdy `make up` pada na istniejącym klastrze → `make down && make up`.
- Start Locusta (Task 3 nagrywa po 15 min ruchu, Task 4 eksportuje po 2 h 7 min): `mise exec -- kubectl --context kind-secure-k8s-aiops -n loadgen get pods -l app.kubernetes.io/name=locust --field-selector=status.phase=Running -o jsonpath='{.items[0].status.containerStatuses[0].state.running.startedAt}'`.
- Od teraz do końca eksportu w Task 4 na klastrze działa tylko ruch Locusta: bez fault-runnera, poleceń w podzie intruder, `tests/observability`, `make test-security`, `tests/security/mutation_check.sh`, `make deploy`, `rollout restart` i `make down`.
- Task 1 potrzebuje sieci do PyPI (`uv lock`).
- Plan trafia do `docs/plans/2026-11-23-t20-eksport-cech.md` commitem `docs: add delivery plan t20-eksport-cech`.
- Jeśli baza gałęzi ma nowsze commity w plikach z tego planu, przeczytaj je ponownie i przenieś zmiany na nowe numery linii; edycje są opisane treścią.

## Approach

Kolejność 1 → 2 → 3 → 4 → 5. Taski 1, 3 i 4 to Python (pakiet i jego workspace, testy, notebook), 2 i 5 to stos „pozostałe” (Dependabot, Markdown). Task 3 wymaga pakietu z Task 1 i ≥ 15 min ruchu Locusta; Task 4 wymaga modułów z Task 3 i ≥ 2 h 7 min ruchu; Task 5 opisuje nazwy z Tasków 1–4 i wnioski z Task 4. Task 2 nie zależy od innych.

Decyzje wspólne:
- **Ramka cech (kontrakt dla T23 i T24):** `pd.DataFrame` z `MultiIndex` (`service`, `timestamp`); `service` ∈ (`frontend`, `orders`); `timestamp` w UTC co 30 s od `start` do `end` (ułamki sekund obcięte), pełna siatka dla każdej usługi; 9 kolumn float64 w kolejności tabeli reguł, nazwy jak w `01-prototyp.ipynb`. Format długi: `frame.xs("orders", level="service")` daje ramkę jednej usługi, a Parquet zachowuje indeks bez spłaszczania nazw kolumn.
- **Zapytanie:** `last_over_time(<reguła>{namespace="shop"}[30s])` — w kroku t ostatnia ewaluacja reguły z (t − 30 s, t]; brak ewaluacji to NaN, a nie wartość sprzed kilku minut z lookbacku. 9 zapytań, po jednym na regułę: `last_over_time` usuwa nazwę metryki, więc jedno zapytanie na wszystkie reguły dałoby serie o tych samych etykietach.
- **Brak ruchu HTTP:** NaN i brak serii w `http_requests_rate1m`, `http_errors_ratio_rate1m` i `http_latency_p95_seconds_1m` → 0 (brak żądań, błędów i czasu odpowiedzi); pozostałe cechy zostają NaN. Luka = kolejne kroki z NaN w którejkolwiek cesze; `max_gap_seconds` mierzy najdłuższą (liczba kroków × 30 s), także na brzegach okna.
- **CLI:** `python -m aiops.export --from ISO --to ISO --out PLIK [--prometheus-url URL]`, domyślnie `http://localhost:9090` (`make prometheus`). Czas bez strefy albo `--to` ≤ `--from` → błąd argparse (kod 2) bez zapytań. Sukces: plik Parquet (katalog tworzony) i jedna linia JSON na stdout z `max_gap_seconds`; kryterium luk ≤ 60 s sprawdza się w tym JSON-ie, CLI go nie egzekwuje. Błąd Prometheusa albo brak połączenia → komunikat na stderr, kod 1, bez pliku.
- **Testy:** odtwarzacz nagrania (`FakePrometheus` w `aiops/tests/conftest.py`) odpowiada tylko na nagrane zapytanie, okno i krok; przypadki brzegowe (NaN, brak serii, brakujące próbki) test robi, zmieniając nagrane odpowiedzi. Nagrywarka `aiops/tests/fixtures/record.py` zostaje w repo, bo zmiana `feature_query` wymaga nowego nagrania. `aiops/tests/__init__.py` omija kolizję nazw z ustaleń (pytest, katalog `aiops/`).
- **Zależności:** numpy, pandas i scikit-learn przechodzą z grupy `dev` korzenia do pakietu `aiops` (komentarz `pyproject.toml:27`), pyarrow ≥ 26.0.1 dochodzi dla Parquet; matplotlib, ipykernel i nbconvert zostają w `dev`.
- Bez zmian: `Makefile`, CI (`ci.yml` uruchamia `make unit`, który bierze `testpaths`), `deploy/`, `mise.toml`, `.gitignore` (`aiops/data/` już jest), `.dockerignore`.

### Task 1: Pakiet aiops w workspace uv
**Commit:** build(aiops): pakiet aiops w workspace uv z numpy, pandas, pyarrow i scikit-learn (T20)

**Files:**
- Create: `aiops/pyproject.toml`
- Create: `aiops/src/aiops/__init__.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `chaos/Dockerfile`
- Modify: `services/frontend/Dockerfile`
- Modify: `services/orders/Dockerfile`

Dockerfile'y są w tym tasku, bo od commita, który dodaje `aiops` do `members`, `uv sync --frozen` w każdym obrazie wymaga `aiops/pyproject.toml`.

1. Utwórz `aiops/pyproject.toml`:

```toml
[project]
name = "aiops"
version = "0.1.0"
description = "Detekcja anomalii: cechy z Prometheusa, model, detektor i ewaluacja"
requires-python = "==3.13.*"
dependencies = [
    "httpx>=0.28.1",
    "numpy>=2.5.4",
    "pandas>=3.1.0",
    "pyarrow>=26.0.1",
    "scikit-learn>=1.9.1",
]

[build-system]
requires = ["uv_build>=0.13.1,<0.14"]
build-backend = "uv_build"
```

2. Utwórz `aiops/src/aiops/__init__.py`:

```python
"""Detekcja anomalii (docs/detekcja.md): cechy, model, detektor i ewaluacja."""
```

3. `pyproject.toml`:
   - linia 7: `dependencies = ["aiops", "chaos", "frontend", "orders"]`;
   - linie 14–16 (komentarz workspace'u) zamień na cztery linie:

```toml
# Zadanie, które tworzy pakiet Pythona (np. services/frontend w T05, chaos w T08,
# aiops w T20), dopisuje tu jego katalog razem z jego pyproject.toml, linię
# `COPY <katalog>/pyproject.toml <katalog>/` w każdym Dockerfile przed `uv sync --frozen`
# i nazwę pakietu do ignore w .github/dependabot.yml.
```

   - linia 18: `members = ["aiops", "chaos", "libs/observability", "services/frontend", "services/orders"]`;
   - `[tool.uv.sources]`: przed `chaos = { workspace = true }` (21) dopisz `aiops = { workspace = true }`;
   - linie 26–27 (komentarz nad `dev = [`) zamień na:

```toml
# Notebooki aiops/notebooks (T09, T20): `uv run jupyter nbconvert --to notebook --execute <plik>`.
# numpy, pandas i scikit-learn (notebooki, tests/observability/test_traffic.py) daje pakiet aiops (T20).
```

   - z listy `dev` usuń `"numpy>=2.5.4",`, `"pandas>=3.1.0",` i `"scikit-learn>=1.9.1",` (33, 34, 38);
   - linia 44: `testpaths = ["aiops", "chaos", "libs", "services"]`.
4. W `chaos/Dockerfile`, `services/frontend/Dockerfile` i `services/orders/Dockerfile` po linii 15 (komentarz „Każdy członek workspace'u…”) wstaw `COPY aiops/pyproject.toml aiops/`, przed `COPY chaos/pyproject.toml chaos/`.
5. `mise exec -- uv lock`, potem `mise exec -- uv sync --locked`. W `uv.lock` pojawiają się pakiet `aiops` (editable) i `pyarrow`; numpy, pandas i scikit-learn znikają z grupy `dev` korzenia i są zależnościami `aiops`.

Sprawdzenie:
- `mise exec -- uv run --locked python -c 'import aiops, pyarrow, sklearn; print(pyarrow.__version__)'` → `26.0.1` (najnowsze wydanie 23.11.2026; nowsze tylko wtedy, gdy wyszło co najmniej 7 dni przed `uv lock`, inaczej plan awaryjny);
- `make lint` → kod 0; `make unit` → `96 passed`;
- `make images` → kod 0 (trzy obrazy zbudowane i załadowane do kind; działające pody się nie restartują).

### Task 2: Dependabot pomija pakiet aiops
**Commit:** ci(dependabot): pomijaj pakiet workspace'u aiops (T20)

**Files:**
- Modify: `.github/dependabot.yml`

1. Linia 20: `a pod nazwami chaos i frontend są tam obce pakiety.` → `a pod nazwami aiops, chaos i frontend są tam obce pakiety.`
2. W `ignore:` przed `- dependency-name: chaos` (22) dopisz `- dependency-name: aiops` z tym samym wcięciem.

Sprawdzenie: `mise exec -- yq '.updates[1].ignore' .github/dependabot.yml` → wpisy `aiops`, `chaos`, `frontend`, `orders`, `observability`.

### Task 3: Klient Prometheusa, ramka cech, eksport do Parquet i testy
**Commit:** feat(aiops): klient Prometheusa, ramka cech i eksport do Parquet (T20)

**Files:**
- Create: `aiops/src/aiops/prometheus.py`
- Create: `aiops/src/aiops/features.py`
- Create: `aiops/src/aiops/export.py`
- Create: `aiops/tests/__init__.py`
- Create: `aiops/tests/conftest.py`
- Create: `aiops/tests/fixtures/record.py`
- Create: `aiops/tests/fixtures/query_range.json`
- Test: `aiops/tests/test_features.py`
- Test: `aiops/tests/test_export.py`

Treść plików poniżej jest sformatowana ruffem 0.17.3 i przechodzi `ruff check` z konfiguracją repo; przepisz ją bez zmian.

1. Testy najpierw: utwórz `aiops/tests/__init__.py`, `aiops/tests/conftest.py`, `aiops/tests/test_features.py` i `aiops/tests/test_export.py`. `mise exec -- uv run --locked pytest aiops` → błędy importu (`aiops.features`, `aiops.export` jeszcze nie istnieją).
2. Utwórz `aiops/src/aiops/prometheus.py`, `aiops/src/aiops/features.py` i `aiops/src/aiops/export.py`.
3. Utwórz `aiops/tests/fixtures/record.py` i nagraj odpowiedzi, gdy Locust działa co najmniej 15 min (start z warunku wstępnego), a w ostatnich 10 min na klastrze nie działało nic poza nim: `mise exec -- uv run --locked python aiops/tests/fixtures/record.py` → `…/aiops/tests/fixtures/query_range.json: <start>–<end>`. Plik ma klucze `start`, `end`, `step` (30) i `rules` (9 reguł, każda z `query` i `response`); nagrywarka kończy się błędem, jeśli reguła nie ma serii obu usług albo seria nie ma 21 skończonych próbek.
4. `make unit` → `107 passed`; `make lint` → kod 0.
5. Smoke na klastrze (port-forward w tle):

```bash
make prometheus >/dev/null 2>&1 &
sleep 5
TO_S=$(( $(date +%s) / 30 * 30 - 60 )); FROM_S=$(( TO_S - 600 ))
mise exec -- uv run --locked python -m aiops.export --from "$(date -u -d @$FROM_S +%FT%TZ)" --to "$(date -u -d @$TO_S +%FT%TZ)" --out /tmp/t20-smoke.parquet
pkill -f 'port-forward svc/prometheus-operated 9090:9090'
```

   - kod 0, JSON z `"rows": {"frontend": 21, "orders": 21}`, `"features": 9`, `"max_gap_seconds": {"frontend": 0, "orders": 0}`.

`aiops/tests/__init__.py`:

```python
# Pakiet testów: bez niego pytest (--import-mode=importlib) nazwałby moduły
# aiops.tests.* i podstawił katalog aiops/ w miejsce zainstalowanego pakietu aiops.
```

`aiops/tests/conftest.py`:

```python
import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

# Odpowiedzi GET /api/v1/query_range nagrane na klastrze przez fixtures/record.py
# (ruch Locust, 10 min, krok 30 s): zapytanie aiops.features.feature_query
# każdej z 9 reguł service:*.
RECORDING = Path(__file__).parent / "fixtures" / "query_range.json"


class FakePrometheus:
    """Odtwarza nagranie: odpowiada tylko na nagrane zapytanie, okno i krok.

    Inne zapytanie dostaje 400, jak niepoprawne zapytanie w Prometheusie.
    """

    def __init__(self, recording: dict) -> None:
        self.window = (recording["start"], recording["end"], recording["step"])
        self.rules = copy.deepcopy(recording["rules"])

    def __call__(self, request: httpx.Request) -> httpx.Response:
        params = request.url.params
        asked = (float(params["start"]), float(params["end"]), float(params["step"]))
        for entry in self.rules.values():
            if params["query"] == entry["query"] and asked == self.window:
                return httpx.Response(200, json=entry["response"])
        return httpx.Response(
            400,
            json={"status": "error", "errorType": "bad_data", "error": "not recorded"},
        )

    def series(self, rule: str, service: str) -> dict:
        """Nagrana seria reguły dla usługi; test może ją zmienić przed zapytaniem."""
        result = self.rules[rule]["response"]["data"]["result"]
        return next(item for item in result if item["metric"]["service"] == service)

    def drop_series(self, rule: str, service: str) -> None:
        result = self.rules[rule]["response"]["data"]["result"]
        result.remove(self.series(rule, service))


@pytest.fixture(scope="session")
def recording() -> dict:
    return json.loads(RECORDING.read_text())


@pytest.fixture
def prometheus(recording: dict) -> FakePrometheus:
    return FakePrometheus(recording)


@pytest.fixture
def window(recording: dict) -> tuple[datetime, datetime]:
    return (
        datetime.fromtimestamp(recording["start"], UTC),
        datetime.fromtimestamp(recording["end"], UTC),
    )
```

`aiops/tests/test_features.py`:

```python
import httpx
import pandas as pd
import pytest
from aiops.features import fetch_features, max_gap_seconds
from aiops.prometheus import PrometheusClient

# Kontrakt z docs/architektura.md, nie z aiops.features: test łapie regułę albo kolumnę
# usuniętą lub przemianowaną.
CONTRACT = {
    "service:cpu_usage_ratio_of_limit": "cpu_usage_ratio_of_limit",
    "service:memory_working_set_ratio_of_limit": "memory_working_set_ratio_of_limit",
    "service:network_rx_bytes:rate1m": "network_rx_bytes_rate1m",
    "service:network_tx_bytes:rate1m": "network_tx_bytes_rate1m",
    "service:http_requests:rate1m": "http_requests_rate1m",
    "service:http_errors_ratio:rate1m": "http_errors_ratio_rate1m",
    "service:http_latency_p95_seconds:1m": "http_latency_p95_seconds_1m",
    "service:restarts:increase5m": "restarts_increase5m",
    "service:policy_drops:rate1m": "policy_drops_rate1m",
}
HTTP_COLUMNS = [
    "http_requests_rate1m",
    "http_errors_ratio_rate1m",
    "http_latency_p95_seconds_1m",
]


def fetch(prometheus, window) -> pd.DataFrame:
    transport = httpx.MockTransport(prometheus)
    with PrometheusClient("http://prometheus:9090", transport=transport) as client:
        return fetch_features(client, *window)


def recorded(prometheus, rule: str, service: str) -> list[float]:
    return [float(value) for _, value in prometheus.series(rule, service)["values"]]


def test_frame_has_contract_features_for_both_services_on_30s_grid(prometheus, window):
    frame = fetch(prometheus, window)

    assert frame.index.names == ["service", "timestamp"]
    assert list(frame.columns) == list(CONTRACT.values())
    grid = list(pd.date_range(*window, freq="30s"))
    for service in ("frontend", "orders"):
        per_service = frame.xs(service, level="service")
        assert list(per_service.index) == grid
        for rule, column in CONTRACT.items():
            assert per_service[column].tolist() == recorded(prometheus, rule, service)


def test_http_features_without_traffic_are_zero(prometheus, window):
    # orders przed pierwszym żądaniem: reguły http_* nie mają serii.
    for rule in (
        "service:http_requests:rate1m",
        "service:http_errors_ratio:rate1m",
        "service:http_latency_p95_seconds:1m",
    ):
        prometheus.drop_series(rule, "orders")
    # frontend bez żądań w oknie rate: udział błędów i p95 to 0/0, czyli NaN.
    for rule in (
        "service:http_errors_ratio:rate1m",
        "service:http_latency_p95_seconds:1m",
    ):
        series = prometheus.series(rule, "frontend")
        series["values"] = [[t, "NaN"] for t, _ in series["values"]]

    frame = fetch(prometheus, window)

    orders = frame.xs("orders", level="service")
    frontend = frame.xs("frontend", level="service")
    assert (orders[HTTP_COLUMNS] == 0).all().all()
    assert (frontend[HTTP_COLUMNS[1:]] == 0).all().all()
    assert frontend["http_requests_rate1m"].tolist() == recorded(
        prometheus, "service:http_requests:rate1m", "frontend"
    )
    assert max_gap_seconds(frame) == {"frontend": 0, "orders": 0}


@pytest.mark.parametrize(
    ("missing", "gap"),
    [([5, 6, 7], 90), ([0, 1], 60), ([-1], 30)],
    ids=["middle", "start", "end"],
)
def test_missing_evaluations_are_gaps(prometheus, window, missing, gap):
    series = prometheus.series("service:cpu_usage_ratio_of_limit", "orders")
    samples = series["values"]
    dropped = {k % len(samples) for k in missing}
    series["values"] = [s for k, s in enumerate(samples) if k not in dropped]

    frame = fetch(prometheus, window)

    cpu = frame.xs("orders", level="service")["cpu_usage_ratio_of_limit"]
    expected = pd.to_datetime(
        [samples[k][0] for k in sorted(dropped)], unit="s", utc=True
    )
    assert list(cpu[cpu.isna()].index) == list(expected)
    assert max_gap_seconds(frame) == {"frontend": 0, "orders": gap}
```

`aiops/tests/test_export.py`:

```python
import json

import httpx
import pandas as pd
import pytest
from aiops.export import main
from aiops.features import fetch_features
from aiops.prometheus import PrometheusClient

URL = "http://prometheus:9090"


def run(handler, *args: str) -> int:
    return main(
        ["--prometheus-url", URL, *args], transport=httpx.MockTransport(handler)
    )


def test_export_writes_frame_to_parquet_and_prints_summary(
    prometheus, window, tmp_path, capsys
):
    start, end = window
    out = tmp_path / "data" / "baseline.parquet"

    code = run(
        prometheus,
        "--from",
        start.isoformat(),
        "--to",
        end.isoformat(),
        "--out",
        str(out),
    )

    assert code == 0
    with PrometheusClient(URL, transport=httpx.MockTransport(prometheus)) as client:
        expected = fetch_features(client, start, end)
    pd.testing.assert_frame_equal(pd.read_parquet(out), expected)
    steps = len(pd.date_range(start, end, freq="30s"))
    assert json.loads(capsys.readouterr().out) == {
        "out": str(out),
        "from": start.isoformat(),
        "to": end.isoformat(),
        "rows": {"frontend": steps, "orders": steps},
        "features": 9,
        "max_gap_seconds": {"frontend": 0, "orders": 0},
    }


def unexpected(request: httpx.Request) -> httpx.Response:
    pytest.fail(f"unexpected request {request.url}")


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2026-11-23T08:00:00", "2026-11-23T10:00:00Z"),
        ("2026-11-23T10:00:00Z", "2026-11-23T10:00:00Z"),
        ("wczoraj", "2026-11-23T10:00:00Z"),
    ],
    ids=["without-timezone", "empty-range", "not-iso"],
)
def test_invalid_range_is_rejected_without_request(tmp_path, start, end):
    out = tmp_path / "baseline.parquet"

    with pytest.raises(SystemExit):
        run(unexpected, "--from", start, "--to", end, "--out", str(out))

    assert not out.exists()


def test_prometheus_error_is_reported_without_file(window, tmp_path, capsys):
    def reject(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"status": "error", "errorType": "bad_data", "error": "parse error"},
        )

    start, end = window
    out = tmp_path / "baseline.parquet"

    code = run(
        reject, "--from", start.isoformat(), "--to", end.isoformat(), "--out", str(out)
    )

    assert code == 1
    err = capsys.readouterr().err
    assert "400" in err and "bad_data" in err
    assert not out.exists()


def test_unreachable_prometheus_exits_with_error(window, tmp_path, capsys):
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused", request=request)

    start, end = window
    out = tmp_path / "baseline.parquet"

    code = run(
        refuse, "--from", start.isoformat(), "--to", end.isoformat(), "--out", str(out)
    )

    assert code == 1
    assert "unreachable" in capsys.readouterr().err
    assert not out.exists()
```

`aiops/src/aiops/prometheus.py`:

```python
"""Klient zapytań zakresowych HTTP API Prometheusa (`GET /api/v1/query_range`).

Z hosta: http://localhost:9090 (`make prometheus`); w klastrze (T24):
http://prometheus-operated.monitoring.svc:9090.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Self

import httpx
import pandas as pd

REQUEST_TIMEOUT_SECONDS = 30.0


class PrometheusError(Exception):
    """Prometheus nieosiągalny albo odpowiedź API inna niż sukces."""


@dataclass(frozen=True)
class RangeSeries:
    """Seria wyniku zapytania: etykiety i próbki.

    `values`: float64 z indeksem czasu UTC; wartość "NaN" z API (np. 0/0) to NaN.
    """

    labels: dict[str, str]
    values: pd.Series


class PrometheusClient:
    def __init__(self, url: str, transport: httpx.BaseTransport | None = None) -> None:
        """`transport` podmienia połączenia HTTP w testach."""
        self._client = httpx.Client(
            base_url=url, timeout=REQUEST_TIMEOUT_SECONDS, transport=transport
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def query_range(
        self, query: str, start: datetime, end: datetime, step_seconds: int
    ) -> list[RangeSeries]:
        params = {
            "query": query,
            "start": start.timestamp(),
            "end": end.timestamp(),
            "step": step_seconds,
        }
        try:
            response = self._client.get("/api/v1/query_range", params=params)
        except httpx.HTTPError as exc:
            raise PrometheusError(f"prometheus unreachable: {exc!r}") from exc
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
            raise PrometheusError(
                f"prometheus responded {response.status_code}: {detail}"
            )
        return [_range_series(item) for item in body["data"]["result"]]


def _range_series(item: dict) -> RangeSeries:
    index = pd.to_datetime([t for t, _ in item["values"]], unit="s", utc=True)
    values = pd.Series(
        [float(v) for _, v in item["values"]], index=index, dtype="float64"
    )
    return RangeSeries(labels=item["metric"], values=values)
```

`aiops/src/aiops/features.py`:

```python
"""Ramka cech ML z reguł nagrywających service:*.

Kontrakt: docs/architektura.md, „Kontrakt metryk i logów”. Ta sama ramka służy
eksportowi danych (T20), treningowi modelu (T23) i detektorowi (T24).
"""

from datetime import UTC, datetime

import pandas as pd

from aiops.prometheus import PrometheusClient

SERVICES = ("frontend", "orders")
# Krok grupy reguł `service` w deploy/observability/recording-rules.yaml.
STEP_SECONDS = 30
# Reguła nagrywająca → kolumna ramki: nazwa bez `service:`, `:` zamienione na `_`
# (te same nazwy co w aiops/notebooks/01-prototyp.ipynb).
FEATURES = {
    "service:cpu_usage_ratio_of_limit": "cpu_usage_ratio_of_limit",
    "service:memory_working_set_ratio_of_limit": "memory_working_set_ratio_of_limit",
    "service:network_rx_bytes:rate1m": "network_rx_bytes_rate1m",
    "service:network_tx_bytes:rate1m": "network_tx_bytes_rate1m",
    "service:http_requests:rate1m": "http_requests_rate1m",
    "service:http_errors_ratio:rate1m": "http_errors_ratio_rate1m",
    "service:http_latency_p95_seconds:1m": "http_latency_p95_seconds_1m",
    "service:restarts:increase5m": "restarts_increase5m",
    "service:policy_drops:rate1m": "policy_drops_rate1m",
}
FEATURE_COLUMNS = list(FEATURES.values())
# Bez ruchu HTTP reguły http_* nie mają serii (przed pierwszym żądaniem usługi)
# albo mają NaN (0/0): brak żądań to 0 żądań/s, 0 błędów i 0 s odpowiedzi,
# a nie luka w danych.
ZERO_WITHOUT_TRAFFIC = [
    "http_requests_rate1m",
    "http_errors_ratio_rate1m",
    "http_latency_p95_seconds_1m",
]


def feature_query(rule: str) -> str:
    """Ostatnia ewaluacja reguły w oknie (t − 30 s, t].

    Reguły liczą się co 30 s, więc okno zawiera dokładnie jedną ewaluację. Jej brak daje
    NaN zamiast wartości sprzed kilku minut z 5-minutowego lookbacku zwykłego selektora.
    """
    return f'last_over_time({rule}{{namespace="shop"}}[{STEP_SECONDS}s])'


def fetch_features(
    client: PrometheusClient, start: datetime, end: datetime
) -> pd.DataFrame:
    """Cechy obu usług co STEP_SECONDS od `start` do `end` (UTC, ułamki sekund obcięte).

    Indeks: MultiIndex (service, timestamp), dla każdej usługi pełna siatka kroków.
    Kolumny: FEATURE_COLUMNS (float64). Brak ewaluacji reguły to NaN, poza
    ZERO_WITHOUT_TRAFFIC.
    """
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start and end must be timezone-aware")
    start = start.astimezone(UTC).replace(microsecond=0)
    end = end.astimezone(UTC).replace(microsecond=0)
    grid = pd.date_range(start, end, freq=f"{STEP_SECONDS}s", name="timestamp")
    found: dict[str, dict[str, pd.Series]] = {service: {} for service in SERVICES}
    for rule, column in FEATURES.items():
        for series in client.query_range(feature_query(rule), start, end, STEP_SECONDS):
            service = series.labels.get("service")
            if service in found:
                found[service][column] = series.values
    frame = pd.concat(
        {
            service: pd.DataFrame(
                by_column, index=grid, columns=FEATURE_COLUMNS, dtype="float64"
            )
            for service, by_column in found.items()
        },
        names=["service"],
    )
    frame[ZERO_WITHOUT_TRAFFIC] = frame[ZERO_WITHOUT_TRAFFIC].fillna(0.0)
    return frame


def max_gap_seconds(frame: pd.DataFrame) -> dict[str, int]:
    """Najdłuższa luka każdej usługi w sekundach: kolejne kroki bez którejś cechy."""
    gaps = {}
    for service in SERVICES:
        incomplete = frame.xs(service, level="service").isna().any(axis=1)
        longest = run = 0
        for missing in incomplete:
            run = run + 1 if missing else 0
            longest = max(longest, run)
        gaps[service] = longest * STEP_SECONDS
    return gaps
```

`aiops/src/aiops/export.py`:

```python
"""Eksport cech ML z Prometheusa do pliku Parquet (T20).

Opcje: `uv run python -m aiops.export --help`; przykład w README („Dane i cechy”).
Prometheus z hosta: `make prometheus` (port-forward na localhost:9090) w drugim
terminalu. Ramkę opisuje aiops.features; katalog aiops/data/ jest poza git.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

import httpx

from aiops.features import fetch_features, max_gap_seconds
from aiops.prometheus import PrometheusClient, PrometheusError

DEFAULT_PROMETHEUS_URL = "http://localhost:9090"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m aiops.export",
        description="Eksport cech ML (reguły service:*) z Prometheusa do Parquet.",
    )
    parser.add_argument(
        "--from",
        dest="start",
        type=_aware_datetime,
        required=True,
        metavar="ISO",
        help="początek, ISO 8601 ze strefą, np. 2026-11-23T08:00:00Z",
    )
    parser.add_argument(
        "--to",
        dest="end",
        type=_aware_datetime,
        required=True,
        metavar="ISO",
        help="koniec, ISO 8601 ze strefą",
    )
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="plik .parquet, np. aiops/data/baseline.parquet",
    )
    parser.add_argument(
        "--prometheus-url",
        default=DEFAULT_PROMETHEUS_URL,
        help="adres Prometheusa (domyślnie port-forward z make prometheus)",
    )
    return parser


def main(
    argv: Sequence[str] | None = None, transport: httpx.BaseTransport | None = None
) -> int:
    """`transport` podmienia połączenia HTTP w testach."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.end <= args.start:
        parser.error("--to must be later than --from")

    try:
        with PrometheusClient(args.prometheus_url, transport=transport) as client:
            frame = fetch_features(client, args.start, args.end)
    except PrometheusError as exc:
        print(exc, file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(args.out)
    timestamps = frame.index.get_level_values("timestamp")
    summary = {
        "out": str(args.out),
        "from": timestamps.min().isoformat(),
        "to": timestamps.max().isoformat(),
        "rows": {
            service: int(count)
            for service, count in frame.groupby(level="service").size().items()
        },
        "features": len(frame.columns),
        "max_gap_seconds": max_gap_seconds(frame),
    }
    print(json.dumps(summary))
    return 0


def _aware_datetime(value: str) -> datetime:
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"expected ISO 8601 time, got {value!r}"
        ) from None
    if moment.tzinfo is None:
        raise argparse.ArgumentTypeError(
            f"expected time with timezone (e.g. Z), got {value!r}"
        )
    return moment


if __name__ == "__main__":
    sys.exit(main())
```

`aiops/tests/fixtures/record.py`:

```python
"""Nagrywa odpowiedzi Prometheusa dla testów aiops: fixtures/query_range.json.

Na klastrze z make up, gdy Locust działa od co najmniej 15 min, a w ostatnich 10 min
nie było awarii (S1–S7), skoku ruchu ani testów z tests/:

    mise exec -- uv run --locked python aiops/tests/fixtures/record.py

Nagrywa ostatnie pełne 10 min (21 kroków) zapytania aiops.features.feature_query każdej
reguły. Zapytania idą przez proxy API serwera (kubectl get --raw), jak w
tests/observability/test_metrics.py. Zmiana feature_query wymaga nowego nagrania.
"""

import json
import math
import os
import subprocess
import time
import urllib.parse
from pathlib import Path

from aiops.features import FEATURES, SERVICES, STEP_SECONDS, feature_query

KUBE_CONTEXT = os.environ.get("KUBE_CONTEXT", "kind-secure-k8s-aiops")
PROMETHEUS_PROXY = (
    "/api/v1/namespaces/monitoring/services/prometheus-operated:9090/proxy"
)
WINDOW_SECONDS = 600
OUT = Path(__file__).with_name("query_range.json")


def query_range(query: str, start: int, end: int) -> dict:
    params = {"query": query, "start": start, "end": end, "step": STEP_SECONDS}
    path = f"{PROMETHEUS_PROXY}/api/v1/query_range?" + urllib.parse.urlencode(params)
    result = subprocess.run(
        ["kubectl", "--context", KUBE_CONTEXT, "get", "--raw", path],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return json.loads(result.stdout)


def main() -> None:
    # Krok sprzed minuty: ewaluacja reguł z końca okna jest już zapisana.
    end = int(time.time()) // STEP_SECONDS * STEP_SECONDS - 60
    start = end - WINDOW_SECONDS
    steps = WINDOW_SECONDS // STEP_SECONDS + 1
    rules = {}
    for rule in FEATURES:
        query = feature_query(rule)
        response = query_range(query, start, end)
        result = response["data"]["result"]
        services = sorted(series["metric"]["service"] for series in result)
        if services != sorted(SERVICES):
            raise SystemExit(f"{rule}: series {services}, expected {sorted(SERVICES)}")
        for series in result:
            values = [float(value) for _, value in series["values"]]
            if len(values) != steps or not all(map(math.isfinite, values)):
                raise SystemExit(
                    f"{rule} {series['metric']['service']}: {len(values)} samples, "
                    f"expected {steps} finite"
                )
        rules[rule] = {"query": query, "response": response}
    recording = {"start": start, "end": end, "step": STEP_SECONDS, "rules": rules}
    OUT.write_text(json.dumps(recording, indent=1) + "\n")
    print(f"{OUT}: {start}–{end}")


if __name__ == "__main__":
    main()
```

### Task 4: Notebook EDA na 2 h ruchu bazowego
**Commit:** feat(aiops): notebook EDA cech z 2 h ruchu bazowego (T20)

**Files:**
- Create: `aiops/notebooks/02-eda.ipynb`

1. Okno eksportu: ostatnie 2 h, zaczynające się co najmniej 5 min po starcie Locusta (rozgrzewka jak w `tests/observability/test_traffic.py`), bez alertów w shop. Kroki 1 i 2 w tym samym shellu (zmienne `TO_S`, `FROM_S`):

```bash
K="mise exec -- kubectl --context kind-secure-k8s-aiops"
LOCUST_START=$($K -n loadgen get pods -l app.kubernetes.io/name=locust --field-selector=status.phase=Running -o jsonpath='{.items[0].status.containerStatuses[0].state.running.startedAt}')
TO_S=$(( $(date +%s) / 30 * 30 - 60 )); FROM_S=$(( TO_S - 7200 ))
test "$FROM_S" -ge $(( $(date -d "$LOCUST_START" +%s) + 300 )) && echo okno-ok
Q=$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1]))' 'count_over_time(ALERTS{namespace="shop", alertstate="firing"}[2h])')
$K get --raw "/api/v1/namespaces/monitoring/services/prometheus-operated:9090/proxy/api/v1/query?query=$Q&time=$TO_S"
```

   - brak `okno-ok` → poczekaj do startu Locusta + 2 h 7 min i powtórz blok;
   - odpowiedź ALERTS musi mieć `"result":[]`.
2. Eksport:

```bash
mkdir -p reports
make prometheus >/dev/null 2>&1 &
sleep 5
mise exec -- uv run --locked python -m aiops.export --from "$(date -u -d @$FROM_S +%FT%TZ)" --to "$(date -u -d @$TO_S +%FT%TZ)" --out aiops/data/baseline.parquet | tee reports/t20-eksport.json
pkill -f 'port-forward svc/prometheus-operated 9090:9090'
```

   - kod 0; `"rows": {"frontend": 241, "orders": 241}`, `"features": 9`, obie wartości `max_gap_seconds` ≤ 60.
3. Utwórz `aiops/notebooks/02-eda.ipynb` jednorazowym skryptem poza repo (np. `/tmp/build_02_eda.py`, uruchomionym `mise exec -- uv run --locked python /tmp/build_02_eda.py` w korzeniu repo): `nbformat.v4.new_notebook()`, `nb.metadata["kernelspec"] = {"display_name": "Python 3", "language": "python", "name": "python3"}`, komórki 0–16 poniżej w tej kolejności (`nbformat.v4.new_markdown_cell` / `new_code_cell`, treść bez zmian), `nbformat.write(nb, "aiops/notebooks/02-eda.ipynb")`. Treść komórek code jest sformatowana ruffem; komórka 16 to szablon wniosków.
4. `mise exec -- uv run --locked jupyter nbconvert --to notebook --execute --inplace aiops/notebooks/02-eda.ipynb` → kod 0.
5. W komórce 16 zastąp każde `<…>` liczbami i nazwami z wyników komórek 1–15 (zapis przez `nbformat.read`/`nbformat.write`, bez ponownego wykonania); w wariantach `<a|b>` zostaje jedno słowo. Bez interpretacji poza liczbami z tabel.
6. `make lint` → kod 0; `git status --short` pokazuje tylko `aiops/notebooks/02-eda.ipynb` (`aiops/data/` i `reports/` są ignorowane).

Komórka 0 (markdown):

````markdown
# 02 · EDA cech z klastra (T20)

Cel: zanim powstanie model (T23), sprawdzić na prawdziwym ruchu bazowym rozkłady, korelacje i sezonowość 9 cech z reguł nagrywających (`docs/architektura.md`, „Kontrakt metryk i logów”) oraz założenia danych syntetycznych z prototypu (`01-prototyp.ipynb`, T09).

Dane: co najmniej 2 h ruchu Locusta (T18) bez scenariuszy S1–S7, eksport `aiops.export` do `aiops/data/baseline.parquet` (katalog poza git):

```bash
make prometheus   # drugi terminal
uv run python -m aiops.export --from <ISO> --to <ISO> --out aiops/data/baseline.parquet
uv run jupyter nbconvert --to notebook --execute --inplace aiops/notebooks/02-eda.ipynb
```

Notebook z wynikami jest w git; po nowym eksporcie wyniki i wnioski się zmieniają.
````

Komórka 1 (code):

```python
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from aiops.features import FEATURE_COLUMNS, SERVICES, STEP_SECONDS, max_gap_seconds

pd.set_option("display.precision", 3)
# Niska rozdzielczość wykresów: notebook z wynikami jest w git.
plt.rcParams["figure.dpi"] = 60

DATA = Path("../data/baseline.parquet")  # katalog roboczy notebooka: aiops/notebooks
MIN_HOURS = 2  # kryterium T20
STEPS_PER_MIN = 60 // STEP_SECONDS

features = pd.read_parquet(DATA)
by_service = {service: features.xs(service, level="service") for service in SERVICES}
timestamps = features.index.get_level_values("timestamp")
first, last = timestamps.min(), timestamps.max()
hours = (last - first) / pd.Timedelta(hours=1)
assert hours >= MIN_HOURS, f"eksport ma {hours:.2f} h, potrzeba {MIN_HOURS} h"
print(f"{first} – {last}: {hours:.2f} h, krok {STEP_SECONDS} s")
```

Komórka 2 (markdown):

````markdown
## Dane i luki

Luka to kolejne kroki, w których brakuje którejkolwiek cechy (`aiops.features.max_gap_seconds`); kryterium T20: najwyżej 60 s. Cechy `http_*` bez ruchu mają 0 (reguła eksportu), więc brak wartości oznacza brak ewaluacji reguły.
````

Komórka 3 (code):

```python
pd.DataFrame(
    {
        "wiersze": {s: len(f) for s, f in by_service.items()},
        "wiersze z brakami": {
            s: int(f.isna().any(axis=1).sum()) for s, f in by_service.items()
        },
        "najdłuższa luka (s)": max_gap_seconds(features),
    }
)
```

Komórka 4 (markdown):

````markdown
## Przebiegi

Wszystkie cechy obu usług; oś x to minuty od początku eksportu.
````

Komórka 5 (code):

```python
minutes = (by_service[SERVICES[0]].index - first) / pd.Timedelta(minutes=1)
fig, axes = plt.subplots(
    len(FEATURE_COLUMNS), len(SERVICES), figsize=(14, 18), sharex=True
)
for col, service in enumerate(SERVICES):
    axes[0, col].set_title(service)
    for row, feature in enumerate(FEATURE_COLUMNS):
        axes[row, col].plot(minutes, by_service[service][feature], linewidth=0.8)
        axes[row, col].set_ylabel(feature, fontsize=8)
for ax in axes[-1]:
    ax.set_xlabel("minuty")
fig.tight_layout()
```

Komórka 6 (markdown):

````markdown
## Rozkłady

Statystyki i histogramy cech w ruchu bazowym. Cecha z odchyleniem 0 jest dla IsolationForest niewidoczna (`docs/detekcja.md`, „Dlaczego IsolationForest wypada słabo”).
````

Komórka 7 (code):

```python
pd.concat(
    {
        service: frame.describe(percentiles=[0.05, 0.5, 0.95]).T.assign(
            skew=frame.skew()
        )
        for service, frame in by_service.items()
    },
    names=["service", "cecha"],
)
```

Komórka 8 (code):

```python
fig, axes = plt.subplots(len(FEATURE_COLUMNS), len(SERVICES), figsize=(10, 18))
for col, service in enumerate(SERVICES):
    axes[0, col].set_title(service)
    for row, feature in enumerate(FEATURE_COLUMNS):
        axes[row, col].hist(by_service[service][feature].dropna(), bins=30)
        axes[row, col].set_ylabel(feature, fontsize=8)
fig.tight_layout()
```

Komórka 9 (markdown):

````markdown
## Korelacje

Korelacja Spearmana (rangowa, odporna na pojedyncze piki) między cechami każdej usługi; puste pola to cechy stałe. Tabela pod wykresem: ta sama cecha we frontend i orders.
````

Komórka 10 (code):

```python
correlations = {
    service: frame.corr(method="spearman") for service, frame in by_service.items()
}
fig, axes = plt.subplots(1, len(SERVICES), figsize=(16, 7))
for ax, service in zip(axes, SERVICES):
    matrix = correlations[service]
    ax.imshow(matrix, vmin=-1, vmax=1, cmap="coolwarm")
    ax.set_xticks(range(len(FEATURE_COLUMNS)), FEATURE_COLUMNS, rotation=90, fontsize=8)
    ax.set_yticks(range(len(FEATURE_COLUMNS)), FEATURE_COLUMNS, fontsize=8)
    for i, j in np.ndindex(matrix.shape):
        if np.isfinite(matrix.iat[i, j]):
            ax.text(
                j, i, f"{matrix.iat[i, j]:.2f}", ha="center", va="center", fontsize=7
            )
    ax.set_title(service)
fig.tight_layout()
```

Komórka 11 (code):

```python
pd.Series(
    {
        feature: pd.concat([by_service[s][feature] for s in SERVICES], axis=1)
        .corr(method="spearman")
        .iat[0, 1]
        for feature in FEATURE_COLUMNS
    },
    name="Spearman frontend–orders",
)
```

Komórka 12 (markdown):

````markdown
## Sezonowość

Autokorelacja każdej cechy dla przesunięć do 60 min. Ruch Locusta ma okres 30 min (`docs/architektura.md`, „Ruch (Locust)”). Tabela: przesunięcie z najwyższą autokorelacją w zakresie 10–45 min; puste wiersze to cechy stałe.
````

Komórka 13 (code):

```python
MAX_LAG_MIN = 60
PERIOD_SEARCH_MIN = (10, 45)
lags = np.arange(1, MAX_LAG_MIN * STEPS_PER_MIN + 1)
acf = {
    service: pd.DataFrame(
        {
            feature: [frame[feature].autocorr(int(lag)) for lag in lags]
            for feature in FEATURE_COLUMNS
        },
        index=pd.Index(lags / STEPS_PER_MIN, name="przesunięcie (min)"),
    )
    for service, frame in by_service.items()
}
fig, axes = plt.subplots(1, len(SERVICES), figsize=(14, 4), sharey=True)
for ax, service in zip(axes, SERVICES):
    acf[service].plot(ax=ax, linewidth=0.8, legend=False)
    ax.axvline(30, color="gray", linestyle="--", linewidth=0.8)
    ax.set_title(service)
axes[0].set_ylabel("autokorelacja")
axes[-1].legend(fontsize=7, loc="upper right")
fig.tight_layout()


def peak(frame: pd.DataFrame) -> pd.DataFrame:
    search = frame.loc[PERIOD_SEARCH_MIN[0] : PERIOD_SEARCH_MIN[1]]
    search = search.dropna(axis=1, how="all")
    return pd.DataFrame(
        {"okres (min)": search.idxmax(), "autokorelacja": search.max()}
    ).reindex(FEATURE_COLUMNS)


period = pd.concat(
    {service: peak(frame) for service, frame in acf.items()},
    names=["service", "cecha"],
)
period
```

Komórka 14 (markdown):

````markdown
## Założenia prototypu a dane

Poziomy i zależności, z których `01-prototyp.ipynb` (komórka „Model danych” i funkcja `simulate`) generował ruch bazowy, obok wartości z klastra. Wyraz wolny i nachylenie: prosta najmniejszych kwadratów cechy względem `http_requests_rate1m` tej samej usługi (p95 tylko z krokami z ruchem).
````

Komórka 15 (code):

```python
PROTOTYPE = {  # simulate() w 01-prototyp.ipynb, ruch bazowy
    "frontend": {
        "średni ruch (żądania/s)": 10.0,
        "CPU/limit: wyraz wolny": 0.04,
        "CPU/limit: na 1 żądanie/s": 0.009,
        "pamięć/limit (mediana)": 0.30,
        "B odebrane na żądanie (mediana)": 400.0,
        "B wysłane na żądanie (mediana)": 1600.0,
        "p95 (s): wyraz wolny": 0.03,
        "p95 (s): na 1 żądanie/s": 0.0008,
        "udział 5xx (średnia)": 0.001,
        "restarty i odrzucenia (maks.)": 0.0,
        "okres ruchu (min)": 30.0,
    },
    "orders": {
        "średni ruch (żądania/s)": 3.0,
        "CPU/limit: wyraz wolny": 0.03,
        "CPU/limit: na 1 żądanie/s": 0.01,
        "pamięć/limit (mediana)": 0.16,
        "B odebrane na żądanie (mediana)": 350.0,
        "B wysłane na żądanie (mediana)": 450.0,
        "p95 (s): wyraz wolny": 0.012,
        "p95 (s): na 1 żądanie/s": 0.0004,
        "udział 5xx (średnia)": 0.001,
        "restarty i odrzucenia (maks.)": 0.0,
        "okres ruchu (min)": 30.0,
    },
}


def line(x: pd.Series, y: pd.Series) -> tuple[float, float]:
    """Wyraz wolny i nachylenie prostej y = a + b·x (najmniejsze kwadraty)."""
    valid = x.notna() & y.notna()
    slope, intercept = np.polyfit(x[valid], y[valid], 1)
    return float(intercept), float(slope)


measured = {}
for service, frame in by_service.items():
    rps = frame["http_requests_rate1m"]
    busy = rps > 0
    cpu = line(rps, frame["cpu_usage_ratio_of_limit"])
    p95 = line(rps[busy], frame["http_latency_p95_seconds_1m"][busy])
    measured[service] = {
        "średni ruch (żądania/s)": rps.mean(),
        "CPU/limit: wyraz wolny": cpu[0],
        "CPU/limit: na 1 żądanie/s": cpu[1],
        "pamięć/limit (mediana)": frame["memory_working_set_ratio_of_limit"].median(),
        "B odebrane na żądanie (mediana)": (
            frame["network_rx_bytes_rate1m"][busy] / rps[busy]
        ).median(),
        "B wysłane na żądanie (mediana)": (
            frame["network_tx_bytes_rate1m"][busy] / rps[busy]
        ).median(),
        "p95 (s): wyraz wolny": p95[0],
        "p95 (s): na 1 żądanie/s": p95[1],
        "udział 5xx (średnia)": frame["http_errors_ratio_rate1m"].mean(),
        "restarty i odrzucenia (maks.)": frame[
            ["restarts_increase5m", "policy_drops_rate1m"]
        ]
        .max()
        .max(),
        "okres ruchu (min)": period.loc[
            (service, "http_requests_rate1m"), "okres (min)"
        ],
    }

share = (
    by_service["orders"]["http_requests_rate1m"].mean()
    / by_service["frontend"]["http_requests_rate1m"].mean()
)
print(f"udział ruchu orders/frontend: prototyp 0.30, klaster {share:.2f}")
assumptions = pd.concat(
    {
        service: pd.DataFrame(
            {"prototyp": PROTOTYPE[service], "klaster": measured[service]}
        ).assign(**{"klaster/prototyp": lambda t: t["klaster"] / t["prototyp"]})
        for service in SERVICES
    },
    axis=1,
)
assumptions
```

Komórka 16 (markdown):

````markdown
## Wnioski

- **Dane:** <od> – <do> (<godziny> h), <wiersze> kroków na usługę; najdłuższa luka: frontend <s> s, orders <s> s — kryterium T20 (≤ 60 s) <spełnione|niespełnione>.
- **Rozkłady:** cechy stałe w ruchu bazowym (odchylenie 0): frontend <cechy>, orders <cechy>; IsolationForest ich nie widzi (`docs/detekcja.md`). Największa |skośność|: frontend <2 cechy z wartością>, orders <2 cechy z wartością>.
- **Korelacje:** pary cech z |ρ| ≥ 0,8 — frontend: <pary z ρ>; orders: <pary z ρ>. Ta sama cecha we frontend i orders z |ρ| ≥ 0,8: <cechy z ρ>.
- **Sezonowość:** okres `http_requests_rate1m`: frontend <min> min, orders <min> min; autokorelacja w szczycie ≥ 0,5: <cechy>. Okno treningowe 30 min (T23) <obejmuje|nie obejmuje> pełny okres ruchu.
- **Założenia prototypu:** różnica co najmniej 2× (`klaster/prototyp` poniżej 0,5 albo powyżej 2): <wielkość (usługa): prototyp → klaster; …> albo „brak”; udział ruchu orders/frontend: prototyp 0,30, klaster <x>.
````

### Task 5: Dokumentacja
**Commit:** docs: eksport cech i EDA (T20) w README, architekturze i detekcji

**Files:**
- Modify: `README.md`
- Modify: `docs/architektura.md`
- Modify: `docs/detekcja.md`

1. `README.md`: po sekcji „Logi i zdarzenia (Loki)” (kończy się linią 133), przed `## Jak pracujemy` (135), wstaw sekcję (z pustą linią przed i po):

````markdown
### Dane i cechy (aiops)

Pakiet `aiops` pobiera z Prometheusa 9 cech z reguł nagrywających `service:*` dla `frontend` i `orders` co 30 s i zapisuje je do Parquet w `aiops/data/` (poza git). Kontrakt ramki: [docs/architektura.md](docs/architektura.md#kontrakt-metryk-i-logów).

```bash
make prometheus   # drugi terminal: Prometheus na localhost:9090
uv run python -m aiops.export --from 2026-11-23T08:00:00Z --to 2026-11-23T10:00:00Z --out aiops/data/baseline.parquet
uv run jupyter nbconvert --to notebook --execute --inplace aiops/notebooks/02-eda.ipynb   # EDA (T20) na aiops/data/baseline.parquet, co najmniej 2 h ruchu
```

Eksport wypisuje JSON z zakresem, liczbą kroków na usługę, liczbą cech i najdłuższą luką (`max_gap_seconds`, w sekundach). Bez ruchu HTTP cechy `http_*` mają 0, a brak ewaluacji reguły to NaN. Inny adres Prometheusa: `--prometheus-url`. Testy pakietu (`aiops/tests`, nagrane odpowiedzi Prometheusa) uruchamia `make unit`.
````

2. `docs/architektura.md`:
   - linia 34: na końcu akapitu dopisz zdanie: „Każdy Dockerfile kopiuje przed `uv sync --frozen` plik `pyproject.toml` każdego członka workspace'u, więc nowy pakiet workspace'u (np. `aiops`, T20) dopisuje linię `COPY` we wszystkich Dockerfile'ach.”;
   - po linii 211 (`Test: tests/observability/test_logs.py …`) i pustej linii 212, przed `- **Detektor (T24).**` (213), wstaw (z pustą linią po):

````markdown
- **Cechy ML (T20).** Pakiet `aiops` (`aiops/src/aiops/`): `aiops.prometheus.PrometheusClient(url)` pyta `GET /api/v1/query_range` (z hosta `http://localhost:9090` przez `make prometheus`, w klastrze `http://prometheus-operated.monitoring.svc:9090`), a `aiops.features.fetch_features(client, start, end)` (czasy ze strefą) zwraca ramkę wspólną dla eksportu, treningu (T23) i detektora (T24):
  - indeks `MultiIndex` (`service`, `timestamp`): `service` ∈ {frontend, orders}, `timestamp` w UTC co 30 s od `start` do `end` (ułamki sekund obcięte), pełna siatka kroków dla każdej usługi;
  - 9 kolumn float64 w kolejności tabeli reguł; kolumna to nazwa reguły bez `service:` z `:` zamienionym na `_` (np. `network_rx_bytes_rate1m`, `http_latency_p95_seconds_1m`), jak w `aiops/notebooks/01-prototyp.ipynb`;
  - wartość w kroku t to ostatnia ewaluacja reguły w (t − 30 s, t]: `last_over_time(<reguła>{namespace="shop"}[30s])`. Brak ewaluacji (np. restart Prometheusa) daje NaN, a nie wartość sprzed kilku minut z 5-minutowego lookbacku;
  - `http_requests_rate1m`, `http_errors_ratio_rate1m` i `http_latency_p95_seconds_1m` bez serii (przed pierwszym żądaniem usługi) albo z NaN (bez ruchu) mają 0;
  - luka to kolejne kroki z NaN w którejkolwiek cesze; `aiops.features.max_gap_seconds(frame)` podaje najdłuższą lukę każdej usługi w sekundach.

  Eksport: `uv run python -m aiops.export --from <ISO> --to <ISO> --out aiops/data/<nazwa>.parquet [--prometheus-url <URL>]` (czasy ISO 8601 ze strefą). Zapisuje ramkę do Parquet (pyarrow; `pd.read_parquet` przywraca indeks) i wypisuje JSON z polami `out`, `from`, `to`, `rows`, `features`, `max_gap_seconds`. Błąd Prometheusa albo brak połączenia: kod 1 bez pliku. EDA ruchu bazowego: `aiops/notebooks/02-eda.ipynb`.

Test: `aiops/tests` (bez klastra, `make unit`) na odpowiedziach `query_range` nagranych przez `aiops/tests/fixtures/record.py` do `aiops/tests/fixtures/query_range.json`; zmiana zapytania wymaga nowego nagrania. Sprawdza siatkę, kolumny i wartości ramki, zera bez ruchu, luki, plik Parquet, podsumowanie JSON i błędy CLI.
````

   - linia 309: komentarz `# pakiet aiops: cechy, model, detektor, ewaluacja (T20–T25, T30)` → `# pakiet aiops: cechy, model, detektor, ewaluacja (T20–T25, T30); notebooks/ (T09, T20); data/ poza git (T20)`.
3. `docs/detekcja.md`, linia 81: zdanie „Rozkłady i korelacje z prawdziwego ruchu sprawdzi T20 (notebook EDA), a liczby z klastra da T30.” zamień na: „Rozkłady, korelacje i sezonowość ruchu bazowego z klastra pokazuje [`aiops/notebooks/02-eda.ipynb`](../aiops/notebooks/02-eda.ipynb) (T20); różnice co najmniej 2× względem założeń prototypu: <treść punktu „Założenia prototypu” z komórki „Wnioski” bez udziału ruchu, albo „brak”>. Liczby detekcji z klastra da T30.”

Sprawdzenie: `make lint` → kod 0.

## Critical files & anchors

- `pyproject.toml:7,13-23,25-39,44` — workspace, źródła, grupa `dev` (linia 27: polecenie przeniesienia zależności w T20), `testpaths`.
- `chaos/Dockerfile:15-19` (tak samo `services/frontend/Dockerfile` i `services/orders/Dockerfile`) — lista `COPY <członek>/pyproject.toml` przed `uv sync --frozen`.
- `deploy/observability/recording-rules.yaml:8-9,19-137` — 9 reguł, krok 30 s, NaN i brak serii `http_*`, zero `policy_drops`.
- `tests/observability/test_metrics.py:21-63` i `tests/observability/test_traffic.py:65-82` — zapytania przez proxy API serwera (wzór nagrywarki) i start Locusta.
- `aiops/notebooks/01-prototyp.ipynb` — komórka 1 (`FEATURES`, `SERVICES`) i `simulate()` (komórka 3): nazwy kolumn i wartości tabeli `PROTOTYPE` w 02.

## Verification

Korzeń repozytorium, gałąź `t20-eksport-cech` z Taskami 1–5, klaster z warunku wstępnego. `K="mise exec -- kubectl --context kind-secure-k8s-aiops"`. Jeśli liczba albo kod się nie zgadza, zatrzymaj się i zgłoś wynik.

1. Bez klastra: `make lint && make unit` → kod 0, `107 passed`.
2. Obrazy: `make images` → kod 0.
3. Kryterium 1 (eksport 2 h ruchu bazowego), wynik z Task 4:

```bash
cat reports/t20-eksport.json
mise exec -- uv run --locked python -c 'import pandas as pd; f = pd.read_parquet("aiops/data/baseline.parquet"); print(f.index.names, sorted(f.index.get_level_values("service").unique()), f.shape, f.index.get_level_values("timestamp").tz)'
```

   - JSON: `"features": 9`, `"rows": {"frontend": 241, "orders": 241}`, obie wartości `max_gap_seconds` ≤ 60;
   - `['service', 'timestamp'] ['frontend', 'orders'] (482, 9) UTC`.
4. Kryterium 2: `mise exec -- uv run --locked jupyter nbconvert --to notebook --execute aiops/notebooks/02-eda.ipynb --output-dir /tmp` → kod 0 (kopia w `/tmp/02-eda.nbconvert.ipynb`, notebook w repo bez zmian); `mise exec -- uv run --locked python -c 'import json; s = "".join(json.load(open("aiops/notebooks/02-eda.ipynb"))["cells"][-1]["source"]); assert "<" not in s, s; print("wnioski-ok")'` → `wnioski-ok`.
5. Błędy CLI (bez port-forwardu):
   - `mise exec -- uv run --locked python -m aiops.export --from 2026-11-23T08:00:00 --to 2026-11-23T10:00:00Z --out /tmp/t20-x.parquet; echo $?` → komunikat `expected time with timezone`, `2`;
   - to samo z `--from 2026-11-23T08:00:00Z` → `prometheus unreachable: ConnectError(…)`, `1`; `test -e /tmp/t20-x.parquet || echo brak-pliku` → `brak-pliku`.
6. Od zera (definicja ukończenia; dopiero po krokach 3–4, bo usuwa dane Prometheusa): `make down && time make up` → kod 0, czas `real` do opisu PR.

## Po dostarczeniu (GitHub)

Wykonuje główny agent po Verification i po code review bez CRITICAL/HIGH.

1. Gałąź z `origin/t17-logi-zdarzenia`: po scaleniu #66 `git fetch origin && git rebase origin/main && git push --force-with-lease`; dopiero potem PR.
2. PR z gałęzi `t20-eksport-cech` do `main`, tytuł „T20 · Eksport danych i cechy z Prometheusa”, w treści `Closes #20`. Opis: kontrakt ramki (MultiIndex, kolumny, UTC, krok 30 s); `last_over_time(…[30s])` zamiast lookbacku i dlaczego; zera `http_*` bez ruchu; `max_gap_seconds`; przeniesienie numpy, pandas i scikit-learn do pakietu `aiops` i pyarrow 26.0.1; linia `COPY aiops/pyproject.toml` w trzech Dockerfile'ach; `aiops/tests/__init__.py` (kolizja nazw w pytest); nagrywarka; JSON z `reports/t20-eksport.json`; liczba testów (`107 passed`); czas `make up` z kroku 6 Verification.
3. Komentarz w #20: odhaczone kryteria z JSON-em z `reports/t20-eksport.json` i wynikiem kroku 4 Verification.
4. Komentarz w #23: „T20: dane do treningu: `pd.read_parquet("aiops/data/<nazwa>.parquet")` → `MultiIndex` (`service`, `timestamp` UTC, krok 30 s), 9 kolumn float64 (`aiops.features.FEATURE_COLUMNS`, nazwy jak w 01-prototyp); ramka usługi: `frame.xs("orders", level="service")`. Bez ruchu HTTP cechy `http_*` = 0; NaN = brak ewaluacji reguły (luka, `aiops.features.max_gap_seconds`), więc przed `fit` odrzuć wiersze z NaN. scikit-learn jest już zależnością pakietu `aiops`. Wnioski z EDA ruchu bazowego: `aiops/notebooks/02-eda.ipynb`, komórka „Wnioski”.”
5. Komentarz w #24: „T20: cechy na żywo: `with PrometheusClient("http://prometheus-operated.monitoring.svc:9090") as client: frame = fetch_features(client, now - timedelta(minutes=5), now)` (`aiops.prometheus`, `aiops.features`; `now = datetime.now(UTC)`, czas bez strefy to `ValueError`). Wiersz z NaN to brak ewaluacji reguły w tym kroku (zapytanie `last_over_time(…[30s])`, bez 5-minutowego lookbacku); `PrometheusError` przy błędzie HTTP albo połączenia. Dockerfile obrazu z `aiops/` kopiuje przed `uv sync --frozen` `pyproject.toml` każdego członka workspace'u, jak `chaos/Dockerfile`.”

## Assumptions & contingencies

- Brak ruchu HTTP to 0 w trzech cechach `http_*`, nie NaN: model T23/T24 dostaje pełne wiersze, a „brak ruchu” odróżnia się od luki. Jeśli właściciel woli NaN: usuń `ZERO_WITHOUT_TRAFFIC` i jego użycie w `fetch_features`, a `test_http_features_without_traffic_are_zero` zamień na test oczekujący NaN i luki na całym oknie.
- Luki widoczne przez `last_over_time(…[30s])`; zwykły selektor ukryłby luki krótsze niż 5 min.
- Kryterium luk raportuje JSON eksportu; CLI nie kończy się błędem przy luce > 60 s (eksport przebiegu z S5 dla T23 ma prawo mieć luki).
- numpy, pandas i scikit-learn w pakiecie `aiops` zgodnie z komentarzem w `pyproject.toml`; scikit-learn pierwszy raz użyje T23.
- Notebook porównuje dane z założeniami prototypu, bo `docs/detekcja.md:81` zostawia to EDA z T20.

Plan awaryjny:
- **`uv lock` wybiera pyarrow wydany mniej niż 7 dni temu:** `mise exec -- uv lock --upgrade-package pyarrow==26.0.1`. **`uv lock` pada (sieć, konflikt):** zatrzymaj się i zgłoś komunikat; nie zmieniaj innych wersji.
- **Nagrywarka: reguła bez serii obu usług:** `$K -n loadgen get deploy locust`; poczekaj 5 min i powtórz raz; dalej błąd → zatrzymaj się i zgłoś komunikat.
- **Nagrywarka: seria z mniej niż 21 próbkami:** sprawdź restart Prometheusa (`$K -n monitoring get pods -l app.kubernetes.io/name=prometheus`); po 10 min powtórz. Brak pojedynczych kroków przy działającym Prometheusie (założenie jednej ewaluacji na okno 30 s nie trzyma) → w `feature_query` okno `[{STEP_SECONDS}s]` zamień na `[45s]`, docstring na „(t − 45 s, t]”, tak samo opis w Task 5, i nagraj ponownie.
- **`assert_frame_equal` po Parquet różni się tylko typem indeksu albo kolumn:** dodaj `check_index_type=False, check_column_type=False` i asercję `pd.read_parquet(out).index.get_level_values("timestamp").tz` równą UTC (`str(...) == "UTC"`).
- **Eksport 2 h: `max_gap_seconds` > 60:** sprawdź restart Prometheusa w oknie; po 30 min weź nowe okno (krok 1 Task 4); powtórzona luka → zatrzymaj się i zgłoś JSON; nie zmieniaj definicji luki.
- **ALERTS w oknie niepuste:** po 30 min powtórz krok 1 Task 4 z nowym oknem; drugi raz niepuste → zatrzymaj się i zgłoś nazwy alertów.
- **nbconvert pada:** popraw tylko literówkę względem treści komórek z Task 4; inaczej zatrzymaj się i zgłoś traceback.
- **Port 9090 zajęty:** `$K -n monitoring port-forward svc/prometheus-operated 19090:9090` w tle i `--prometheus-url http://localhost:19090`.
- **`make up` pada na zajętym porcie:** zwolnij 8080, 3000 albo 8025 na `127.0.0.1` i powtórz.
