# T21 · Orkiestrator scenariuszy awarii z etykietami (issue #21)

## Context

Issue #21 (R4 AI/ML, Sprint 2, zależy od T08 i T12 — oba zamknięte) wymaga powtarzalnych przebiegów awarii ze znanymi oknami czasu, czyli etykiet prawdy. Korzystają z nich ocena detekcji (T23, T30) i e2e w CI (T28). Zakres:
- `chaos/run.py` uruchamiany na hoście przez uv, z opcjami `--scenarios S1,…,S7`, `--gap 10m` i `--run-id`;
- scenariusze z sekcji „Scenariusze awarii” wykonywane przez `kubectl exec` w `fault-runner` i `intruder`;
- zapis `reports/runs/<run-id>/labels.jsonl` (`scenario`, `name`, `target`, `start`, `end`; UTC, ISO 8601) i `run.json` (commit, początek, koniec);
- adnotacja Grafany (`POST /api/annotations`, tag `scenario`) dla każdego okna;
- Ctrl+C wywołuje `fault-runner stop` i zamyka bieżące okno w etykietach.

Kryteria akceptacji:
1. pełny przebieg S1–S7 daje 7 wpisów w `labels.jsonl`;
2. okna scenariuszy są widoczne jako adnotacje na dashboardach.

Decyzje użytkownika (2026-11-24):
- Ctrl+C w S6 i S7 kończy też proces w podzie: PID leży w `/tmp` poda, a orkiestrator wysyła mu `kill`. Sam `fault-runner stop` zatrzymuje tylko awarie w orders.
- Kryterium 2 sprawdza tymczasowy dashboard, który weryfikacja importuje przez API (zrzut ekranu do #21). Zapytanie adnotacji po tagu trafia do kontraktu w `docs/architektura.md` dla T22. `deploy/` zostaje bez zmian.
- S1 trwa 4 min zamiast 2. To zamyka ryzyko „S1 i HighCPU (T19, T21)” z `docs/detekcja.md:80`. Zmieniają się: tabela kontraktu, domyślne `seconds` awarii `cpu` w orders i orkiestrator.

Stan docelowy:
- `chaos/run.py` (jeden plik, biblioteka standardowa + httpx) ma testy `chaos/tests/test_run.py` w `make unit`;
- orders ma domyślny czas awarii `cpu` 240 s;
- `docs/architektura.md`, `docs/detekcja.md` i README opisują kontrakt orkiestratora (CLI, okna, `labels.jsonl`, `run.json`, adnotacje, Ctrl+C) oraz S1 = 4 min.

### Ustalone fakty (sprawdzone 2026-11-24)

- **Repozytorium.**
  - Bieżąca gałąź to `t20-eksport-cech` (HEAD `88237b3`, drzewo czyste), a PR #67 (T20) jest scalony do `main`.
  - Lokalny `origin/main` (`3c01b4b`, T17) pochodzi sprzed scalenia, dlatego warunek wstępny robi `git fetch`.
  - Numery linii w planie pochodzą z `88237b3`.
- **Klaster nie działa.** Daemon Dockera jest wyłączony (brak `/var/run/docker.sock`), więc weryfikacja na klastrze wymaga `make up`.
- **fault-runner** (`chaos/src/fault_runner/cli.py`):
  - polecenia: `fault <nazwa> [--seconds N] [--param K=V]`, `stop`, `spike --users N --seconds S`;
  - sukces: JSON odpowiedzi na stdout i kod 0;
  - brak połączenia albo status błędu: komunikat na stderr i kod 1; `kubectl exec` przekazuje ten kod;
  - `spike` blokuje przez `--seconds` i wypisuje liczniki dopiero na końcu.
- **orders** (`services/orders/src/orders/faults.py`):
  - naraz działa jedna awaria, nowa zastępuje bieżącą;
  - domyślne `seconds`: cpu 120 (linia 236), memory, errors i latency 180;
  - `crash` wysyła 202, a potem robi `os._exit(1)`;
  - `/healthz` nie podlega awariom;
  - kontrakt mówi „domyślne wartości jak w tabeli” (`docs/architektura.md:282`), więc zmiana S1 w tabeli zmienia też domyślne 120 na 240;
  - żaden test nie sprawdza dziś domyślnego czasu cpu; `test_cpu_fault_burns_cpu_until_stopped` używa wartości domyślnej i zatrzymuje awarię.
- **Pody.**
  - `deploy/base/fault-runner/deployment.yaml`: namespace loadgen, obraz python:3.13-slim (`sh` to dash), `readOnlyRootFilesystem`, `/tmp` z `emptyDir` 16Mi, limit 500m/128Mi.
  - `deploy/base/intruder/deployment.yaml`: namespace intruder, `curlimages/curl` z `sh`, `date`, `sleep` i `curl` (używa ich już README:122), `/tmp` z `emptyDir`, limit 100m/32Mi; PID 1 to `sh -c "trap 'exit 0' TERM; sleep infinity & wait"`.
  - Żaden z nich nie ma tokenu SA, a namespace intruder nie ma NetworkPolicy.
  - Testy wołają je przez `kubectl --context $KUBE_CONTEXT exec -n <ns> deploy/<nazwa> -- …` (`tests/security/test_network_policies.py:115-137`).
- **Grafana.**
  - Adres http://localhost:3000 (NodePort 30300, `deploy/observability/values/kube-prometheus-stack.yaml:70-84`); konto admina z Secretu `grafana-admin` (klucze `admin-user`, `admin-password`).
  - Wzór odczytu konta: `grafana_get` w `tests/observability/test_logs.py:129-146`.
  - W repo nie ma jeszcze żadnego dashboardu (T22 jest otwarte).
  - Adnotacja bez `dashboardUID` należy do całej organizacji. Widać ją tylko na dashboardzie z zapytaniem adnotacji po tagu, bo wbudowane „Annotations & Alerts” filtruje po dashboardzie. To wiedza o Grafanie, którą potwierdza krok 6 weryfikacji.
- **S7.**
  - Usługa `orders` wystawia tylko port 8080.
  - Cilium działa bez `kubeProxyReplacement` (`platform/cilium/values.yaml`), więc ClusterIP na innym porcie nie jest tłumaczony na pod [INFERENCE].
  - Takie próby nie dałyby `POLICY_DENIED` dla orders, bo `service:policy_drops:rate1m` liczy `destination_workload` (`deploy/observability/recording-rules.yaml:117-137`).
  - Dlatego wszystkie 6 portów idzie na IP poda; potwierdza to krok 7 weryfikacji.
- **S1 i HighCPU.**
  - `HighCPU` to `service:cpu_usage_ratio_of_limit > 0.8` z `for: 2m` i ewaluacją co 30 s (`deploy/observability/alert-rules.yaml:17-19`).
  - Reguła to `rate(container_cpu_usage_seconds_total[1m])` podzielone przez limit 500m (`recording-rules.yaml:21-35`, `deploy/base/orders/deployment.yaml:69`).
  - Pętla CPU (jeden wątek) daje ok. 1,0 limitu, więc warunek trwa ok. D − 36 s, gdzie D to czas awarii: 84 s przy 2 min, 144 s przy 3 min (alert w ok. 80% przebiegów), 204 s przy 4 min (zawsze co najmniej 5 ewaluacji).
- **`--gap`.** W prototypie (`aiops/notebooks/01-prototyp.ipynb`, funkcja `simulate`) przerwa jest przed każdym scenariuszem i po ostatnim: `position += GAP_STEPS` przed każdym scenariuszem i `+ GAP_STEPS` na końcu. Okna ewaluacji T30 to [start − 1 min, end + 5 min].
- **Pakowanie i testy.**
  - `chaos/run.py` leży poza `src/fault_runner`, więc nie trafia do koła ani do obrazu fault-runner: końcowy etap `chaos/Dockerfile` kopiuje tylko `/app/.venv`.
  - `ruff check` i `ruff format --check` obejmują ten plik (`select = ["E4","E7","E9","F"]`, 88 znaków).
  - pytest: `testpaths` zawiera `chaos`, działa z `--import-mode=importlib`, a `chaos/tests` nie ma `__init__.py`. Test ładuje więc skrypt przez `importlib.util.spec_from_file_location`.
  - httpx jest zależnością pakietu `chaos`, więc `uv run --locked python chaos/run.py` go ma.
  - `make unit` zbiera dziś 113 testów, a `.gitignore` ma już `reports/`.
  - Narzędzia z `mise.toml` nie są w PATH zwykłej powłoki (`which ruff` → brak), dlatego polecenia idą przez `mise exec --` albo po `eval "$(mise env -s bash)"`.
- **Szkic kodu z tego planu sprawdzony poza repo.**
  - Kopia z `git archive HEAD` z plikami z Tasków 1–3: pełny pytest `140 passed`, `ruff check` i `ruff format --check` czyste (72 pliki).
  - Test orders pada przed zmianą domyślnej wartości (`119.88 s`), a po niej przechodzi.
  - Na fałszywym `kubectl` i atrapie Grafany na porcie 3000 SIGINT do grupy procesów (jak Ctrl+C) w S6 i w S7, także przez `uv run`, dał: kod 130, `kill` PID-u w podzie, potem `fault-runner stop`, okno 3 s w `labels.jsonl`, wysłaną adnotację i żadnych osieroconych procesów.
  - Skrypt S7 pod `/bin/sh` z atrapami `curl` i `date`: runda to 6 prób (porty 8080, 22, 80, 443, 5432, 6379) na podany IP w 1,0 s. Skrypt kill kończy pętlę (SIGTERM), a bez pliku PID kończy się kodem 1.

## Warunek wstępny (główny agent, przed startem delivery)

W korzeniu repozytorium:

```bash
git status --short          # pusto
git fetch origin
git switch main && git pull --ff-only
git log -1 --oneline        # scalenie PR #67 (T20) albo nowszy commit
git switch -c t21-orkiestrator-scenariuszy
```

- Jeśli `main` ma nowsze commity w plikach z planu, przeczytaj je przed edycją. Edycje są opisane treścią, a numery linii to tylko podpowiedź.
- Plan trafia do `docs/plans/2026-11-24-t21-orkiestrator-scenariuszy.md` commitem `docs: add delivery plan t21-orkiestrator-scenariuszy`.
- Weryfikacja na klastrze (kroki 2–9) wymaga Dockera (`docker info`; bez daemona `sudo systemctl start docker`) i zajmuje ok. 50 min.

## Approach

Kolejność: 1 → 2 → 3.
- Taski 1 i 2 to Python w dwóch osobnych pakietach (`services/orders` i `chaos`); Task 3 to Markdown.
- Task 2 nie zależy od Task 1, bo orkiestrator podaje `--seconds 240` jawnie. `make unit` pokaże jednak 140 testów dopiero po obu taskach.
- Task 3 opisuje zachowanie z Tasków 1–2.

Decyzje wspólne:
- **Przebieg.**
  - Kolejność: start → przerwa `gap` → scenariusz → przerwa → … → ostatni scenariusz → przerwa → koniec, jak w prototypie.
  - Scenariusze idą w kolejności z `--scenarios`, bez losowania.
  - `--gap` ma postać `<N>s` albo `<N>m` (domyślnie 600 s); `0s` jest dozwolone.
- **Okno.**
  - `start` to chwila tuż przed pierwszym poleceniem scenariusza.
  - Kroki mają przesunięcie względem `start` (S5: 0, 60 i 120 s).
  - `end` to późniejsza z dwóch chwil: `start` + czas scenariusza albo powrót polecenia blokującego (S6, S7).
  - Czasy są w UTC, obcięte do sekund, w formacie `isoformat()`, np. `2026-11-24T10:10:00+00:00` (jak w `aiops.export`).
- **Polecenia w podach.** Każde idzie przez `kubectl --context $KUBE_CONTEXT exec -n <ns> deploy/<nazwa> -- …`:
  - S1: `fault-runner fault cpu --seconds 240`;
  - S2: `fault memory --seconds 180 --param target_ratio=0.9`;
  - S3: `fault errors --seconds 180 --param ratio=0.5`;
  - S4: `fault latency --seconds 180 --param ms=500`;
  - S5: `fault crash` po 0, 60 i 120 s;
  - S6: `sh -c 'echo $$ > /tmp/chaos-s6.pid && exec fault-runner spike --users 50 --seconds 180'`;
  - S7: skrypt `sh` w intruderze z IP poda orders jako `$1`. PID trafia do `/tmp/chaos-s7.pid`. Przez 120 s co sekundę skrypt puszcza w tle 6 × `curl -s -o /dev/null -m 1 http://$1:<port>/`, potem `sleep 1` i `wait`.
  - Każde `fault-runner fault` ma do 5 prób co 2 s, jak `fault_runner()` w `tests/observability/test_logs.py:56-66`.
  - Timeouty: 60 s na polecenie, w S6 i S7 czas scenariusza + 60 s, 30 s na sprzątanie.
- **Przerwanie (KeyboardInterrupt) i błąd scenariusza.**
  - Na czas sprzątania SIGINT jest ignorowany, a potem przywracany.
  - W S6 i S7 orkiestrator uruchamia `sh -c 'read pid < /tmp/chaos-s<N>.pid && kill "$pid"'` w tym samym podzie.
  - Zawsze wysyła `fault-runner stop`.
  - Otwarte okno zamyka w tej chwili (linia w `labels.jsonl` i adnotacja), a `run.json` dostaje `end`.
  - Kody wyjścia: 130 przy przerwaniu (stderr `interrupted`) albo 1 przy błędzie (stderr `<ID> <nazwa> failed (exit N): <stderr>`).
  - Nieudane polecenie sprzątania daje ostrzeżenie `warning: …` i nie zmienia kodu.
  - Ctrl+C przed startem przebiegu (podczas odczytu Secretu albo sprawdzania Grafany) daje kod 130 bez sprzątania.
- **Pliki.**
  - Katalog `reports/runs/<run-id>/` powstaje na starcie; istniejący katalog to błąd argparse z kodem 2.
  - `labels.jsonl` powstaje pusty na starcie. Linia dochodzi przy zamknięciu okna, z kluczami w kolejności `scenario`, `name`, `target`, `start`, `end`.
  - `run.json` to `{"commit", "start", "end"}` z `indent=2`, zapisany na starcie z `end: null` i nadpisany na końcu.
  - `commit` pochodzi z `git rev-parse HEAD` w korzeniu repo.
- **Grafana.**
  - Klient: httpx `Client(base_url="http://localhost:3000", auth=(user, password), timeout=10)`.
  - Konto pochodzi z `kubectl get secret grafana-admin -n monitoring -o json` (wartości w base64).
  - Przed pierwszym scenariuszem `GET /api/org` musi zwrócić 200; inaczej kod 1 bez katalogu przebiegu.
  - Przy zamknięciu okna idzie `POST /api/annotations` z `{"time": start_ms, "timeEnd": end_ms, "tags": ["scenario", "<ID>"], "text": "<ID> <nazwa> → <cel>, przebieg <run-id>"}`.
  - Błąd daje `warning: grafana annotation for <ID> failed: …`, a przebieg trwa dalej.
  - Jedna adnotacja na okno, bez PATCH.
- **Wyjście.**
  - Na stdout, po jednej linii z `flush=True`: `<UTC ISO> run <run-id> <katalog>`, `<UTC ISO> start <ID> <nazwa> <cel>` i `<UTC ISO> end <ID> <nazwa> <cel>`.
  - Komunikaty błędów są po angielsku, a pomoc argparse po polsku, jak w `fault_runner.cli` i `aiops.export`.
- **Szwy testowe.**
  - `main(argv=None, *, kubectl=run_kubectl, clock=None, transport=None, runs_dir=RUNS_DIR) -> int`.
  - `kubectl(args, timeout) -> subprocess.CompletedProcess[str]`, gdzie `args` nie zawiera `kubectl --context …`.
  - `clock` ma `now() -> datetime` (UTC) i `sleep(seconds)`.
  - `transport` trafia do `httpx.Client`.
  - Prawdziwe `run_kubectl` zamienia brak kubectl i timeout na kod 1 z opisem na stderr.
- **Bez zmian:**
  - `Makefile` (T28 woła skrypt wprost);
  - CI (`make unit` bierze `testpaths`);
  - `pyproject.toml`, `uv.lock` i Dockerfile'e;
  - `deploy/`, `.gitignore` i `chaos/src/fault_runner/`.

### Task 1: S1 trwa 4 min: domyślny czas awarii cpu w orders
**Commit:** feat(orders): domyślny czas awarii cpu 240 s, jak S1 (T21)

**Files:**
- Modify: `services/orders/src/orders/faults.py`
- Test: `services/orders/tests/test_faults.py`

1. W `services/orders/tests/test_faults.py`:
   - po `import time` (linia 3) dopisz `from datetime import UTC, datetime`;
   - po `test_cpu_fault_burns_cpu_until_stopped` (kończy się w linii 179) dodaj test, z dwiema pustymi liniami przed nim i po nim:

```python
def test_cpu_fault_lasts_four_minutes_by_default(client):
    # S1 z docs/architektura.md: 4 min, żeby HighCPU (`for: 2m`) zdążył wystrzelić.
    started = client.post("/faults/cpu", headers=FAULT_AUTH)

    assert started.status_code == 202
    ends_at = datetime.fromisoformat(started.json()["ends_at"])
    assert 235 <= (ends_at - datetime.now(UTC)).total_seconds() <= 240
```

2. `mise exec -- uv run --locked pytest services/orders/tests/test_faults.py -k four_minutes` → `1 failed` (`assert 235 <= 119.8…`).
3. W `services/orders/src/orders/faults.py:236` zamień `def cpu(seconds: Seconds = 120) -> FaultStarted:` na `def cpu(seconds: Seconds = 240) -> FaultStarted:`.

Sprawdzenie:
- `mise exec -- uv run --locked pytest services/orders/tests/test_faults.py` → `54 passed`;
- `mise exec -- make lint` → kod 0.

### Task 2: Orkiestrator chaos/run.py
**Commit:** feat(chaos): orkiestrator scenariuszy S1–S7 z etykietami okien i adnotacjami w Grafanie (T21)

**Files:**
- Create: `chaos/run.py`
- Test: `chaos/tests/test_run.py`

Przepisz obie treści bez zmian. Są sformatowane `ruff format` i przechodzą `ruff check` z konfiguracją repo.

1. Utwórz `chaos/tests/test_run.py`:

```python
import base64
import importlib.util
import json
import re
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

# chaos/run.py to skrypt hosta spoza pakietu fault_runner, więc test ładuje go z pliku.
_spec = importlib.util.spec_from_file_location(
    "chaos_run", Path(__file__).resolve().parents[1] / "run.py"
)
chaos_run = importlib.util.module_from_spec(_spec)
sys.modules["chaos_run"] = chaos_run
_spec.loader.exec_module(chaos_run)

START = datetime(2026, 11, 24, 10, 0, tzinfo=UTC)
ORDERS_IP = "10.244.1.7"


def b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


def completed(code: int = 0, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess([], code, stdout, stderr)


class FakeClock:
    """Czas płynie tylko w sleep(); `interrupt_at` to chwila naciśnięcia Ctrl+C."""

    def __init__(self) -> None:
        self.current = START
        self.interrupt_at: datetime | None = None

    def now(self) -> datetime:
        return self.current

    def sleep(self, seconds: float) -> None:
        target = self.current + timedelta(seconds=seconds)
        if self.interrupt_at is not None and self.current <= self.interrupt_at < target:
            self.current, self.interrupt_at = self.interrupt_at, None
            raise KeyboardInterrupt
        self.current = target


class FakeCluster:
    """kubectl na niby-klastrze: zapisuje polecenia; S6 i S7 trwają tu swój czas."""

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.calls: list[tuple[datetime, tuple[str, ...]]] = []
        # Fragment polecenia → kody wyjścia kolejnych pasujących wywołań (potem 0).
        self.codes: dict[str, list[int]] = {}
        self.secret = json.dumps(
            {"data": {"admin-user": b64("admin"), "admin-password": b64("sekret")}}
        )

    def __call__(self, args: Sequence[str], timeout: float):
        args = tuple(args)
        self.calls.append((self.clock.now(), args))
        if args[:3] == ("get", "secret", "grafana-admin"):
            return completed(stdout=self.secret) if self.secret else completed(1)
        if args[:2] == ("get", "pods"):
            return completed(stdout=ORDERS_IP)
        command = " ".join(args)
        for fragment, codes in self.codes.items():
            if fragment in command and codes:
                code = codes.pop(0)
                if code:
                    return completed(code, stderr="orders unreachable")
        if "fault-runner spike" in command:
            self.clock.sleep(180)
        elif "curl" in command:
            self.clock.sleep(120)
        return completed()

    def execs(self) -> list[tuple[datetime, str, tuple[str, ...]]]:
        """(czas, namespace/Deployment, polecenie w podzie) każdego kubectl exec."""
        return [
            (at, f"{args[2]}/{args[3].removeprefix('deploy/')}", args[5:])
            for at, args in self.calls
            if args[0] == "exec"
        ]


class FakeGrafana:
    def __init__(self) -> None:
        self.org_status = 200
        self.annotation_status = 200
        self.unreachable = False
        self.requests: list[httpx.Request] = []
        self.annotations: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.unreachable:
            raise httpx.ConnectError("Connection refused", request=request)
        self.requests.append(request)
        if (request.method, request.url.path) == ("GET", "/api/org"):
            return httpx.Response(self.org_status, json={"id": 1})
        if (request.method, request.url.path) == ("POST", "/api/annotations"):
            self.annotations.append(json.loads(request.content))
            return httpx.Response(self.annotation_status, json={"id": 1})
        return httpx.Response(404)


@dataclass
class Env:
    clock: FakeClock
    cluster: FakeCluster
    grafana: FakeGrafana
    runs: Path


@pytest.fixture
def env(tmp_path: Path) -> Env:
    clock = FakeClock()
    return Env(clock, FakeCluster(clock), FakeGrafana(), tmp_path / "runs")


def start(env: Env, *args: str) -> int:
    return chaos_run.main(
        list(args),
        kubectl=env.cluster,
        clock=env.clock,
        transport=httpx.MockTransport(env.grafana),
        runs_dir=env.runs,
    )


def utc(value: str) -> datetime:
    moment = datetime.fromisoformat(value)
    assert moment.utcoffset() == timedelta(0), value
    return moment


def windows(run_dir: Path) -> list[dict]:
    lines = (run_dir / "labels.jsonl").read_text().splitlines()
    return [
        {**label, "start": utc(label["start"]), "end": utc(label["end"])}
        for label in map(json.loads, lines)
    ]


def run_json(run_dir: Path) -> dict:
    return json.loads((run_dir / "run.json").read_text())


def last_exec(env: Env) -> tuple[str, tuple[str, ...]]:
    _, pod, argv = env.cluster.execs()[-1]
    return pod, argv


def test_full_run_writes_seven_windows_separated_by_gap(env):
    assert start(env, "--gap", "10m") == 0

    run_dir = env.runs / "20261124T100000Z"
    labels = windows(run_dir)
    assert [(w["scenario"], w["name"], w["target"]) for w in labels] == [
        ("S1", "cpu", "orders"),
        ("S2", "memory", "orders"),
        ("S3", "errors", "orders"),
        ("S4", "latency", "orders"),
        ("S5", "crash", "orders"),
        ("S6", "spike", "frontend"),
        ("S7", "scan", "orders"),
    ]
    assert [(w["end"] - w["start"]).total_seconds() for w in labels] == [
        240,
        180,
        180,
        180,
        180,
        180,
        120,
    ]
    run = run_json(run_dir)
    edges = [utc(run["start"])]
    for window in labels:
        edges += [window["start"], window["end"]]
    edges.append(utc(run["end"]))
    gaps = [later - earlier for earlier, later in zip(edges[::2], edges[1::2])]
    assert gaps == [timedelta(minutes=10)] * 8
    assert re.fullmatch(r"[0-9a-f]{40}", run["commit"])


def test_every_window_gets_a_scenario_annotation(env):
    assert start(env, "--scenarios", "S3,S7", "--gap", "1m", "--run-id", "t21") == 0

    labels = windows(env.runs / "t21")
    assert [(a["tags"], a["time"], a["timeEnd"]) for a in env.grafana.annotations] == [
        (
            ["scenario", w["scenario"]],
            int(w["start"].timestamp()) * 1000,
            int(w["end"].timestamp()) * 1000,
        )
        for w in labels
    ]
    auth = env.grafana.requests[-1].headers["Authorization"]
    assert auth == f"Basic {b64('admin:sekret')}"


@pytest.mark.parametrize(
    ("scenario", "commands"),
    [
        ("S1", [(0, ("cpu", "--seconds", "240"))]),
        ("S2", [(0, ("memory", "--seconds", "180", "--param", "target_ratio=0.9"))]),
        ("S3", [(0, ("errors", "--seconds", "180", "--param", "ratio=0.5"))]),
        ("S4", [(0, ("latency", "--seconds", "180", "--param", "ms=500"))]),
        ("S5", [(0, ("crash",)), (60, ("crash",)), (120, ("crash",))]),
    ],
)
def test_orders_faults_follow_scenario_table(env, scenario, commands):
    assert start(env, "--scenarios", scenario, "--gap", "0s") == 0

    assert env.cluster.execs() == [
        (
            START + timedelta(seconds=offset),
            "loadgen/fault-runner",
            ("fault-runner", "fault", *args),
        )
        for offset, args in commands
    ]


def test_spike_and_scan_run_in_their_pods(env):
    assert start(env, "--scenarios", "S6,S7", "--gap", "0s") == 0

    [spike, scan] = env.cluster.execs()
    assert spike[1] == "loadgen/fault-runner"
    assert spike[2][:2] == ("sh", "-c")
    assert "fault-runner spike --users 50 --seconds 180" in spike[2][2]
    assert scan[0] == spike[0] + timedelta(seconds=180)
    assert scan[1] == "intruder/intruder"
    assert scan[2][:2] == ("sh", "-c")
    assert scan[2][-1] == ORDERS_IP


def test_crash_is_retried_while_orders_restarts(env):
    env.cluster.codes["fault crash"] = [0, 1, 1]

    assert start(env, "--scenarios", "S5", "--gap", "0s", "--run-id", "t21") == 0

    offsets = [(at - START).total_seconds() for at, _, _ in env.cluster.execs()]
    assert offsets == [0, 60, 62, 64, 120]
    [window] = windows(env.runs / "t21")
    assert (window["end"] - window["start"]).total_seconds() == 180


def test_failing_fault_stops_run_and_closes_its_window(env, capsys):
    env.cluster.codes["fault memory"] = [1] * 5

    code = start(env, "--scenarios", "S1,S2,S3", "--gap", "1m", "--run-id", "t21")

    assert code == 1
    assert "S2 memory failed" in capsys.readouterr().err
    labels = windows(env.runs / "t21")
    assert [w["scenario"] for w in labels] == ["S1", "S2"]
    # 5 prób co 2 s.
    assert (labels[1]["end"] - labels[1]["start"]).total_seconds() == 8
    assert last_exec(env) == ("loadgen/fault-runner", ("fault-runner", "stop"))
    assert utc(run_json(env.runs / "t21")["end"]) == labels[1]["end"]


def test_ctrl_c_stops_fault_and_closes_current_window(env, capsys):
    # Przerwa 1 min, S1 4 min, przerwa 1 min, potem 50 s S2.
    env.clock.interrupt_at = START + timedelta(minutes=6, seconds=50)

    code = start(env, "--scenarios", "S1,S2,S3", "--gap", "1m", "--run-id", "t21")

    assert code == 130
    assert "interrupted" in capsys.readouterr().err
    labels = windows(env.runs / "t21")
    assert [w["scenario"] for w in labels] == ["S1", "S2"]
    assert (labels[1]["end"] - labels[1]["start"]).total_seconds() == 50
    assert [a["tags"][1] for a in env.grafana.annotations] == ["S1", "S2"]
    assert last_exec(env) == ("loadgen/fault-runner", ("fault-runner", "stop"))
    assert utc(run_json(env.runs / "t21")["end"]) == labels[1]["end"]


@pytest.mark.parametrize(
    ("scenario", "pod", "pid_file"),
    [
        ("S6", "loadgen/fault-runner", "/tmp/chaos-s6.pid"),
        ("S7", "intruder/intruder", "/tmp/chaos-s7.pid"),
    ],
)
def test_ctrl_c_kills_spike_and_scan_in_their_pod(env, scenario, pod, pid_file):
    env.clock.interrupt_at = START + timedelta(seconds=30)

    assert start(env, "--scenarios", scenario, "--gap", "0s", "--run-id", "t21") == 130

    *_, (_, kill_pod, kill), (_, stop_pod, stop) = env.cluster.execs()
    assert kill_pod == pod
    assert kill[:2] == ("sh", "-c")
    assert pid_file in kill[2] and "kill" in kill[2]
    assert (stop_pod, stop) == ("loadgen/fault-runner", ("fault-runner", "stop"))
    [window] = windows(env.runs / "t21")
    assert (window["end"] - window["start"]).total_seconds() == 30


def test_ctrl_c_in_gap_only_stops_faults(env):
    env.clock.interrupt_at = START + timedelta(seconds=30)

    assert start(env, "--scenarios", "S1", "--gap", "1m", "--run-id", "t21") == 130

    assert windows(env.runs / "t21") == []
    assert [argv for _, _, argv in env.cluster.execs()] == [("fault-runner", "stop")]


def test_failed_annotation_is_only_a_warning(env, capsys):
    env.grafana.annotation_status = 500

    assert start(env, "--scenarios", "S1", "--gap", "0s", "--run-id", "t21") == 0

    assert len(windows(env.runs / "t21")) == 1
    assert "annotation for S1 failed" in capsys.readouterr().err


@pytest.mark.parametrize("problem", ["no secret", "unauthorized", "unreachable"])
def test_grafana_problem_stops_before_any_scenario(env, capsys, problem):
    match problem:
        case "no secret":
            env.cluster.secret = ""
        case "unauthorized":
            env.grafana.org_status = 401
        case "unreachable":
            env.grafana.unreachable = True

    assert start(env, "--run-id", "t21") == 1

    assert "grafana" in capsys.readouterr().err
    assert env.cluster.execs() == []
    assert not (env.runs / "t21").exists()


@pytest.mark.parametrize(
    "args",
    [
        ["--scenarios", "S8"],
        ["--scenarios", "S1,S1"],
        ["--scenarios", ""],
        ["--gap", "10"],
        ["--gap", "1h"],
        ["--run-id", "../t21"],
        ["--run-id", ".t21"],
    ],
)
def test_invalid_arguments_exit_before_touching_cluster(env, args):
    with pytest.raises(SystemExit) as exit_info:
        start(env, *args)

    assert exit_info.value.code == 2
    assert env.cluster.calls == []


def test_existing_run_directory_is_rejected(env):
    (env.runs / "t21").mkdir(parents=True)

    with pytest.raises(SystemExit) as exit_info:
        start(env, "--run-id", "t21")

    assert exit_info.value.code == 2
    assert env.cluster.calls == []
```

2. `mise exec -- uv run --locked pytest chaos/tests/test_run.py` → błąd zbierania (`FileNotFoundError`: brak `chaos/run.py`).
3. Utwórz `chaos/run.py`:

```python
"""Orkiestrator scenariuszy awarii S1–S7 z etykietami prawdy (T21).

Uruchamiany na hoście przy klastrze z `make up` (kubectl z mise.toml w PATH):

    uv run --locked python chaos/run.py [--scenarios S1,…,S7] [--gap 10m] [--run-id ID]

Scenariusze z docs/architektura.md (sekcja „Scenariusze awarii”) idą przez
`kubectl exec` w loadgen/fault-runner i intruder/intruder. Przerwa `--gap` trwa
przed każdym scenariuszem i po ostatnim, jak w aiops/notebooks/01-prototyp.ipynb.
Wynik: reports/runs/<run-id>/labels.jsonl (jedno okno na linię) i run.json; każde
okno dostaje w Grafanie adnotację z tagiem `scenario`. Ctrl+C kończy bieżący
scenariusz (S6 i S7: kill procesu w podzie; zawsze `fault-runner stop`), zamyka
jego okno i kończy przebieg kodem 130. Kontekst kubectl: zmienna KUBE_CONTEXT,
domyślnie kind-secure-k8s-aiops, jak w Makefile.
"""

import argparse
import base64
import json
import os
import re
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

import httpx

KUBE_CONTEXT = os.environ.get("KUBE_CONTEXT", "kind-secure-k8s-aiops")
# localhost:3000 → NodePort 30300 Grafany (extraPortMappings w platform/kind/cluster.yaml).
GRAFANA_URL = "http://localhost:3000"
REPO_ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = REPO_ROOT / "reports" / "runs"

COMMAND_TIMEOUT = 60
CLEANUP_TIMEOUT = 30
# Jak fault_runner() w tests/observability/test_logs.py: po restarcie orders (S5)
# usługa dostaje endpoint chwilę po gotowości kontenera.
FAULT_ATTEMPTS = 5
RETRY_SECONDS = 2

type Pod = tuple[str, str]  # (namespace, Deployment)

FAULT_RUNNER: Pod = ("loadgen", "fault-runner")
INTRUDER: Pod = ("intruder", "intruder")

SPIKE_PID = "/tmp/chaos-s6.pid"
SCAN_PID = "/tmp/chaos-s7.pid"
# exec: PID z pliku należy do procesu fault-runner, więc kill kończy skok ruchu.
SPIKE = f"echo $$ > {SPIKE_PID} && exec fault-runner spike --users 50 --seconds 180"
# $1 to IP poda orders: usługa orders wystawia tylko port 8080, więc odrzucenie
# POLICY_DENIED na pozostałych portach daje tylko połączenie prosto do poda.
# Co sekundę 6 prób naraz; każda trwa najwyżej 1 s, bo Cilium porzuca SYN.
SCAN = f"""echo $$ > {SCAN_PID}
end=$(($(date +%s) + 120))
while [ "$(date +%s)" -lt "$end" ]; do
  for port in 8080 22 80 443 5432 6379; do
    curl -s -o /dev/null -m 1 "http://$1:$port/" &
  done
  sleep 1
  wait
done"""
# Same wbudowane polecenia powłoki: działa w obrazie fault-runner i curl.
KILL = 'read pid < {pid_file} && kill "$pid"'


@dataclass(frozen=True)
class Step:
    """Polecenie w podzie `offset` sekund od początku okna scenariusza."""

    offset: int
    pod: Pod
    argv: tuple[str, ...]
    attempts: int = 1
    timeout: int = COMMAND_TIMEOUT
    # S7: IP poda orders dopisane jako ostatni argument ($1 skryptu SCAN).
    orders_ip: bool = False


@dataclass(frozen=True)
class Scenario:
    id: str
    name: str
    target: str
    seconds: int
    steps: tuple[Step, ...]
    # Kończy proces scenariusza w podzie przy przerwaniu (S6, S7).
    abort: Step | None = None


def _fault(offset: int, name: str, *args: str) -> Step:
    argv = ("fault-runner", "fault", name, *args)
    return Step(offset, FAULT_RUNNER, argv, attempts=FAULT_ATTEMPTS)


def _kill(pod: Pod, pid_file: str) -> Step:
    argv = ("sh", "-c", KILL.format(pid_file=pid_file))
    return Step(0, pod, argv, timeout=CLEANUP_TIMEOUT)


SCENARIOS = {
    scenario.id: scenario
    for scenario in (
        Scenario("S1", "cpu", "orders", 240, (_fault(0, "cpu", "--seconds", "240"),)),
        Scenario(
            "S2",
            "memory",
            "orders",
            180,
            (_fault(0, "memory", "--seconds", "180", "--param", "target_ratio=0.9"),),
        ),
        Scenario(
            "S3",
            "errors",
            "orders",
            180,
            (_fault(0, "errors", "--seconds", "180", "--param", "ratio=0.5"),),
        ),
        Scenario(
            "S4",
            "latency",
            "orders",
            180,
            (_fault(0, "latency", "--seconds", "180", "--param", "ms=500"),),
        ),
        Scenario(
            "S5",
            "crash",
            "orders",
            180,
            tuple(_fault(offset, "crash") for offset in (0, 60, 120)),
        ),
        Scenario(
            "S6",
            "spike",
            "frontend",
            180,
            (
                Step(
                    0, FAULT_RUNNER, ("sh", "-c", SPIKE), timeout=180 + COMMAND_TIMEOUT
                ),
            ),
            abort=_kill(FAULT_RUNNER, SPIKE_PID),
        ),
        Scenario(
            "S7",
            "scan",
            "orders",
            120,
            (
                Step(
                    0,
                    INTRUDER,
                    ("sh", "-c", SCAN, "scan"),
                    timeout=120 + COMMAND_TIMEOUT,
                    orders_ip=True,
                ),
            ),
            abort=_kill(INTRUDER, SCAN_PID),
        ),
    )
}
STOP = Step(0, FAULT_RUNNER, ("fault-runner", "stop"), timeout=CLEANUP_TIMEOUT)


class Clock(Protocol):
    def now(self) -> datetime: ...

    def sleep(self, seconds: float) -> None: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


type Kubectl = Callable[[Sequence[str], float], subprocess.CompletedProcess[str]]


def run_kubectl(
    args: Sequence[str], timeout: float
) -> subprocess.CompletedProcess[str]:
    """`kubectl --context KUBE_CONTEXT <args>`; brak kubectl i timeout dają kod 1."""
    command = ["kubectl", "--context", KUBE_CONTEXT, *args]
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(command, 1, "", repr(exc))


class RunError(Exception):
    """Błąd, który kończy przebieg kodem 1."""


class Orchestrator:
    def __init__(
        self,
        directory: Path,
        run_id: str,
        commit: str,
        kubectl: Kubectl,
        clock: Clock,
        grafana: httpx.Client,
    ) -> None:
        self.directory = directory
        self.labels = directory / "labels.jsonl"
        self.run_id = run_id
        self.commit = commit
        self.kubectl = kubectl
        self.clock = clock
        self.grafana = grafana
        self.start = self._now()
        # Otwarte okno: scenariusz i początek.
        self.current: tuple[Scenario, datetime] | None = None

    def run(self, scenarios: Sequence[Scenario], gap: int) -> int:
        self.directory.mkdir(parents=True)
        self.labels.touch()
        self._write_run(end=None)
        self._say(f"run {self.run_id} {self.directory}")
        try:
            for scenario in scenarios:
                self.clock.sleep(gap)
                self._execute(scenario)
            self.clock.sleep(gap)
        except KeyboardInterrupt:
            self._abort()
            print("interrupted", file=sys.stderr)
            return 130
        except RunError as exc:
            self._abort()
            print(exc, file=sys.stderr)
            return 1
        self._write_run(end=self._now())
        return 0

    def _execute(self, scenario: Scenario) -> None:
        start = self._now()
        self.current = (scenario, start)
        self._say(f"start {scenario.id} {scenario.name} {scenario.target}")
        for step in scenario.steps:
            self._wait_until(start + timedelta(seconds=step.offset))
            self._step(scenario, step)
        self._wait_until(start + timedelta(seconds=scenario.seconds))
        self._close()

    def _step(self, scenario: Scenario, step: Step) -> None:
        argv = step.argv + ((self._orders_ip(scenario),) if step.orders_ip else ())
        for attempt in range(step.attempts):
            if attempt:
                self.clock.sleep(RETRY_SECONDS)
            result = self._exec(step.pod, argv, step.timeout)
            if result.returncode == 0:
                return
        raise RunError(
            f"{scenario.id} {scenario.name} failed (exit {result.returncode}): "
            f"{result.stderr.strip()}"
        )

    def _orders_ip(self, scenario: Scenario) -> str:
        result = self.kubectl(
            [
                "get",
                "pods",
                "-n",
                "shop",
                "-l",
                "app.kubernetes.io/name=orders",
                "--field-selector=status.phase=Running",
                "-o",
                "jsonpath={.items[0].status.podIP}",
            ],
            COMMAND_TIMEOUT,
        )
        if result.returncode != 0 or not result.stdout.strip():
            raise RunError(
                f"{scenario.id} {scenario.name} failed: no running orders pod: "
                f"{result.stderr.strip()}"
            )
        return result.stdout.strip()

    def _abort(self) -> None:
        """Zatrzymuje bieżący scenariusz i zamyka przebieg; Ctrl+C tego nie przerwie."""
        previous = signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            if self.current is not None and self.current[0].abort is not None:
                self._cleanup(self.current[0].abort)
            self._cleanup(STOP)
            self._close()
            self._write_run(end=self._now())
        finally:
            signal.signal(signal.SIGINT, previous)

    def _cleanup(self, step: Step) -> None:
        result = self._exec(step.pod, step.argv, step.timeout)
        if result.returncode != 0:
            print(
                f"warning: {' '.join(step.argv)} in {'/'.join(step.pod)} failed: "
                f"{result.stderr.strip()}",
                file=sys.stderr,
            )

    def _exec(
        self, pod: Pod, argv: Sequence[str], timeout: float
    ) -> subprocess.CompletedProcess[str]:
        namespace, name = pod
        return self.kubectl(
            ["exec", "-n", namespace, f"deploy/{name}", "--", *argv], timeout
        )

    def _close(self) -> None:
        """Zapisuje otwarte okno do labels.jsonl i Grafany; bez okna nic nie robi."""
        if self.current is None:
            return
        (scenario, start), self.current = self.current, None
        end = self._now()
        label = {
            "scenario": scenario.id,
            "name": scenario.name,
            "target": scenario.target,
            "start": start.isoformat(),
            "end": end.isoformat(),
        }
        with self.labels.open("a") as labels:
            labels.write(json.dumps(label) + "\n")
        self._say(f"end {scenario.id} {scenario.name} {scenario.target}")
        self._annotate(scenario, start, end)

    def _annotate(self, scenario: Scenario, start: datetime, end: datetime) -> None:
        annotation = {
            "time": int(start.timestamp()) * 1000,
            "timeEnd": int(end.timestamp()) * 1000,
            "tags": ["scenario", scenario.id],
            "text": (
                f"{scenario.id} {scenario.name} → {scenario.target}, "
                f"przebieg {self.run_id}"
            ),
        }
        try:
            response = self.grafana.post("/api/annotations", json=annotation)
        except httpx.HTTPError as exc:
            problem = repr(exc)
        else:
            if response.is_success:
                return
            problem = f"{response.status_code} {response.text}"
        print(
            f"warning: grafana annotation for {scenario.id} failed: {problem}",
            file=sys.stderr,
        )

    def _write_run(self, end: datetime | None) -> None:
        run = {
            "commit": self.commit,
            "start": self.start.isoformat(),
            "end": None if end is None else end.isoformat(),
        }
        (self.directory / "run.json").write_text(json.dumps(run, indent=2) + "\n")

    def _wait_until(self, moment: datetime) -> None:
        delay = (moment - self.clock.now()).total_seconds()
        if delay > 0:
            self.clock.sleep(delay)

    def _now(self) -> datetime:
        return self.clock.now().replace(microsecond=0)

    def _say(self, message: str) -> None:
        print(f"{self._now().isoformat()} {message}", flush=True)


def grafana_credentials(kubectl: Kubectl) -> tuple[str, str]:
    """Konto admina z Secretu grafana-admin, jak w tests/observability/test_logs.py."""
    result = kubectl(
        ["get", "secret", "grafana-admin", "-n", "monitoring", "-o", "json"],
        COMMAND_TIMEOUT,
    )
    if result.returncode != 0:
        raise RunError(
            f"cannot read secret monitoring/grafana-admin: {result.stderr.strip()}"
        )
    try:
        data = json.loads(result.stdout)["data"]
        user, password = (
            base64.b64decode(data[key]).decode()
            for key in ("admin-user", "admin-password")
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise RunError(
            f"cannot read secret monitoring/grafana-admin: {exc!r}"
        ) from None
    return user, password


def check_grafana(grafana: httpx.Client) -> None:
    """Adresy i konto sprawdzone przed pierwszym scenariuszem, a nie po nim."""
    try:
        response = grafana.get("/api/org")
    except httpx.HTTPError as exc:
        raise RunError(f"grafana unavailable at {GRAFANA_URL}: {exc!r}") from None
    if response.status_code != 200:
        raise RunError(
            f"grafana unavailable at {GRAFANA_URL}: "
            f"{response.status_code} {response.text}"
        )


def git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RunError(f"cannot read git commit: {exc!r}") from None
    if result.returncode != 0:
        raise RunError(f"cannot read git commit: {result.stderr.strip()}")
    return result.stdout.strip()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chaos/run.py",
        description="Scenariusze awarii S1–S7 z etykietami okien i adnotacjami.",
    )
    parser.add_argument(
        "--scenarios",
        type=_scenarios,
        default=tuple(SCENARIOS.values()),
        metavar="S1,…,S7",
        help="scenariusze po przecinku, w tej kolejności (domyślnie S1–S7)",
    )
    parser.add_argument(
        "--gap",
        type=_duration,
        default=600,
        metavar="10m",
        help="przerwa przed każdym scenariuszem i po ostatnim: <N>s albo <N>m",
    )
    parser.add_argument(
        "--run-id",
        type=_run_id,
        help="katalog reports/runs/<run-id>; domyślnie czas startu UTC",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    kubectl: Kubectl = run_kubectl,
    clock: Clock | None = None,
    transport: httpx.BaseTransport | None = None,
    runs_dir: Path = RUNS_DIR,
) -> int:
    """`kubectl`, `clock`, `transport` i `runs_dir` podmieniają otoczenie w testach."""
    parser = build_parser()
    args = parser.parse_args(argv)
    clock = clock or SystemClock()
    run_id = args.run_id or clock.now().strftime("%Y%m%dT%H%M%SZ")
    directory = runs_dir / run_id
    if directory.exists():
        parser.error(f"run directory already exists: {directory}")

    try:
        auth = grafana_credentials(kubectl)
        with httpx.Client(
            base_url=GRAFANA_URL, auth=auth, timeout=10, transport=transport
        ) as grafana:
            check_grafana(grafana)
            orchestrator = Orchestrator(
                directory, run_id, git_commit(), kubectl, clock, grafana
            )
            return orchestrator.run(args.scenarios, args.gap)
    except RunError as exc:
        print(exc, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        # Przerwanie przed startem przebiegu: w klastrze nic jeszcze nie działa.
        return 130


def _scenarios(value: str) -> tuple[Scenario, ...]:
    ids = [part.strip() for part in value.split(",")]
    for id_ in ids:
        if id_ not in SCENARIOS:
            raise argparse.ArgumentTypeError(
                f"unknown scenario {id_!r}, expected S1–S7"
            )
    if len(set(ids)) != len(ids):
        raise argparse.ArgumentTypeError(f"duplicate scenario in {value!r}")
    return tuple(SCENARIOS[id_] for id_ in ids)


def _duration(value: str) -> int:
    match = re.fullmatch(r"(\d+)([sm])", value)
    if match is None:
        raise argparse.ArgumentTypeError(
            f"expected duration like 10m or 90s, got {value!r}"
        )
    number, unit = match.groups()
    return int(number) * (60 if unit == "m" else 1)


def _run_id(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value) is None:
        raise argparse.ArgumentTypeError(
            f"run id may contain only letters, digits, '.', '_' and '-', got {value!r}"
        )
    return value


if __name__ == "__main__":
    sys.exit(main())
```

Co testy sprawdzają (`26` przypadków):
- **Kryterium 1.** Domyślny przebieg S1–S7 daje 7 okien z właściwymi `scenario`, `name`, `target` i czasami (240, 180, 180, 180, 180, 180, 120 s). Przerwy wynoszą 10 min przed każdym scenariuszem i po ostatnim; katalog ma nazwę z czasu UTC; `run.json` zawiera SHA commita.
- **Kryterium 2 po stronie API.** Każde okno dostaje adnotację z tagami `["scenario", "<ID>"]` i `time`/`timeEnd` równymi oknu w ms, a żądanie niesie Basic auth z Secretu.
- **Polecenia.** Polecenia S1–S5 są zgodne z tabelą, a crashe S5 przychodzą po 0, 60 i 120 s. S6 i S7 działają we właściwych podach, a S7 dostaje IP poda orders. Crash jest ponawiany co 2 s.
- **Błąd scenariusza.** Po 5 nieudanych próbach orkiestrator wysyła `fault-runner stop`, zamyka okno i kończy się kodem 1.
- **Ctrl+C:**
  - w oknie: `fault-runner stop`, okno ucięte, adnotacja, `run.json` z `end`, kod 130;
  - w S6 i S7: `kill` PID-u w ich podzie przed `stop`;
  - w przerwie: tylko `stop`, bez okna.
- **Grafana.** Nieudana adnotacja to tylko ostrzeżenie. Brak Secretu, 401 i brak połączenia dają kod 1 przed pierwszym poleceniem w klastrze i bez katalogu.
- **Argumenty.** Błędne argumenty i istniejący katalog dają kod 2 bez kubectl.

Sprawdzenie:
- `mise exec -- uv run --locked pytest chaos/tests/test_run.py` → `26 passed`;
- `mise exec -- uv run --locked python chaos/run.py --help` → usage `chaos/run.py [-h] [--scenarios S1,…,S7] [--gap 10m] [--run-id RUN_ID]`;
- `mise exec -- uv run --locked python chaos/run.py --gap 10` → kod 2, `expected duration like 10m or 90s, got '10'`;
- `mise exec -- make lint` → kod 0;
- `mise exec -- make unit` → `140 passed` (bez Task 1: `139 passed`).

### Task 3: Dokumentacja kontraktu orkiestratora i S1 = 4 min
**Commit:** docs: orkiestrator scenariuszy i S1 = 4 min (T21) w README, architekturze i detekcji

**Files:**
- Modify: `docs/architektura.md`
- Modify: `docs/detekcja.md`
- Modify: `README.md`

1. `docs/architektura.md`, sekcja „Scenariusze awarii”:
   - linię 286 (`- `crash` kończy proces kodem 1 …; powtórzenia S5 planuje orkiestrator (T21).`) zamień na:

````markdown
- `crash` kończy proces kodem 1 zaraz po wysłaniu odpowiedzi 202; trzy crashe S5 (0, 60 i 120 s od początku okna) wysyła orkiestrator `chaos/run.py` (T21).
````

   - wiersz S1 (linia 291) zamień na:

````markdown
| S1 | cpu | orders | `POST /faults/cpu?seconds=240`: pętla obciążająca CPU | 4 min | HighCPU, AnomalyDetected |
````

   - wiersz S7 (linia 297) zamień na:

````markdown
| S7 | scan | orders | intruder: `curl -m 1` na IP poda orders, porty 8080, 22, 80, 443, 5432 i 6379 naraz, co 1 s | 2 min | PolicyDeniedConnections, AnomalyDetected |
````

   - po wierszu S7 wstaw jedną pustą linię i blok poniżej. Pusta linia 298 przed `## Struktura repozytorium` zostaje:

````markdown
S1 trwa 4 min, bo `HighCPU` (`for: 2m`) potrzebuje 5 kolejnych ewaluacji powyżej progu, a `service:cpu_usage_ratio_of_limit` (rate z 1 min) przekracza 0,8 przez czas awarii minus ok. 36 s ([docs/detekcja.md](detekcja.md#ryzyka-dla-innych-zadań)). S7 celuje w IP poda, bo usługa `orders` wystawia tylko port 8080: odrzucenie `POLICY_DENIED` po stronie orders daje tylko połączenie, które dociera do poda.

**Orkiestrator (T21).** `uv run --locked python chaos/run.py [--scenarios S1,…,S7] [--gap 10m] [--run-id <id>]` na hoście (kubectl z `mise.toml`, kontekst ze zmiennej `KUBE_CONTEXT`, domyślnie `kind-secure-k8s-aiops`; Grafana pod http://localhost:3000):
- `--scenarios` wykonuje się w podanej kolejności (domyślnie S1–S7). `--gap` (`<N>s` albo `<N>m`, domyślnie `10m`) to przerwa przed każdym scenariuszem i po ostatnim, jak w `aiops/notebooks/01-prototyp.ipynb`; S1–S7 z `--gap 10m` trwa 101 min. `--run-id` (litery, cyfry, `.`, `_`, `-`; domyślnie czas startu UTC, np. `20261124T100000Z`) to nowy katalog `reports/runs/<run-id>/` (poza git). Nieznany albo powtórzony scenariusz, zły format i istniejący katalog: kod 2 bez poleceń w klastrze.
- S1–S4 to jedno `fault-runner fault <nazwa>` z `--seconds` i `--param` z tabeli, a S5 to `fault-runner fault crash` po 0, 60 i 120 s. Każde `fault-runner fault` ma do 5 prób co 2 s, bo po restarcie orders usługa dostaje endpoint z opóźnieniem. S6 uruchamia `fault-runner spike` przez `sh -c` z PID-em w `/tmp/chaos-s6.pid`, a S7 pętlę `sh` w intruderze z PID-em w `/tmp/chaos-s7.pid`; IP poda orders daje `kubectl get pods -n shop -l app.kubernetes.io/name=orders`.
- Okno zaczyna się tuż przed pierwszym poleceniem scenariusza i kończy po czasie z tabeli; S6 i S7 kończą się razem z poleceniem w podzie (1–3 s później). Czasy w UTC, co do sekundy.
- `labels.jsonl`: jedna linia JSON na zamknięte okno, dopisywana od razu; plik powstaje pusty na starcie przebiegu. `target` to usługa, której alerty liczą się jako wykrycie (T30):

```json
{"scenario": "S1", "name": "cpu", "target": "orders", "start": "2026-11-24T10:10:00+00:00", "end": "2026-11-24T10:14:00+00:00"}
```

- `run.json`: `{"commit": "<SHA HEAD>", "start": "<ISO 8601>", "end": "<ISO 8601>"}`; w trakcie przebiegu `end` ma wartość `null`.
- Adnotacje: po zamknięciu okna `POST /api/annotations` kontem z Secretu `grafana-admin`, z `time` i `timeEnd` okna (ms), `tags: ["scenario", "<ID>"]` i tekstem `<ID> <nazwa> → <cel>, przebieg <run-id>`. Bez `dashboardUID` adnotacja należy do całej organizacji, więc dashboard pokazuje ją zapytaniem adnotacji po tagu (T22, wpis w `annotations.list` dashboardu):

```json
{
  "name": "Scenariusze",
  "datasource": {"type": "grafana", "uid": "-- Grafana --"},
  "enable": true,
  "iconColor": "red",
  "target": {"type": "tags", "tags": ["scenario"], "matchAny": false, "limit": 100}
}
```

- Przed pierwszym scenariuszem orkiestrator czyta Secret `grafana-admin`, sprawdza `GET /api/org` i commit (`git rev-parse HEAD`); błąd: kod 1 bez katalogu przebiegu. Nieudana adnotacja w trakcie przebiegu to tylko ostrzeżenie na stderr.
- Ctrl+C: w S6 i S7 `kill` PID-u z pliku w podzie, zawsze `fault-runner stop`, zamknięcie bieżącego okna (linia w `labels.jsonl` i adnotacja), `end` w `run.json`, kod 130. Polecenie scenariusza, które zawiedzie po wszystkich próbach, kończy przebieg tym samym sprzątaniem i kodem 1.
````

2. `docs/detekcja.md`:
   - linię 13 (`- 20 przebiegów, … co 10 min (`--gap` z T21). …`) zamień na:

````markdown
- 20 przebiegów, w każdym 30 min rozgrzewki i S1–S7 w losowej kolejności, z przerwą 10 min przed każdym scenariuszem i po ostatnim (`--gap` z T21). Razem ok. 33 h ruchu po rozgrzewce.
````

   - linię 80 (`- **S1 i HighCPU (T19, T21).** …`) zamień na:

````markdown
- **S1 i HighCPU (T19, T21).** W prototypie S1 trwał 2 min i reguły nie wykryły go ani razu: `HighCPU` ma `for: 2m`, więc warunek musi być spełniony w 5 kolejnych ewaluacjach co 30 s (120–150 s zależnie od fazy ewaluacji). Przy pełnym obciążeniu `service:cpu_usage_ratio_of_limit` (rate z 1 min) przekracza 0,8 od ok. 48 s po starcie awarii do ok. 12 s po jej końcu, czyli przez czas awarii minus 36 s. T21 wydłużył S1 do 4 min (204 s powyżej progu); przy 3 min (144 s) alert wystrzeliłby tylko w ok. 80% przebiegów.
````

3. `README.md`: po linii 115 (pusta linia po bloku sekcji „Awarie (fault-runner)”, przed `### Alerty (Mailpit)`) wstaw blok poniżej i jedną pustą linię po nim:

````markdown
### Scenariusze awarii (chaos/run.py)

Orkiestrator uruchamia scenariusze S1–S7 przez `kubectl exec` w `loadgen/fault-runner` i `intruder/intruder` i zapisuje ich okna (etykiety prawdy do ewaluacji detekcji) w `reports/runs/<run-id>/` (poza git). Kontrakt: [docs/architektura.md](docs/architektura.md#scenariusze-awarii).

```bash
uv run --locked python chaos/run.py                                    # S1–S7, przerwa 10 min: ok. 1 h 41 min
uv run --locked python chaos/run.py --scenarios S1,S3,S7 --gap 4m --run-id e2e
cat reports/runs/e2e/labels.jsonl reports/runs/e2e/run.json            # okna i commit przebiegu
```

Przerwa `--gap` trwa przed każdym scenariuszem i po ostatnim. Każde okno dostaje w Grafanie adnotację z tagiem `scenario`; dashboard pokazuje ją zapytaniem adnotacji ze źródłem `-- Grafana --` i filtrem po tagu `scenario` (ustawienia dashboardu → Annotations). Ctrl+C zatrzymuje bieżący scenariusz (`fault-runner stop`, w S6 i S7 także proces w podzie), zamyka jego okno i kończy przebieg kodem 130.
````

Sprawdzenie:
- `mise exec -- make lint` → kod 0 (nowe bloki to `json` i `bash`, ruff formatuje w Markdownie tylko `python`);
- `grep -c 'seconds=120' docs/architektura.md` → `0`;
- `grep -c 'Orkiestrator (T21)' docs/architektura.md` → `1`.

## Critical files & anchors

- `chaos/src/fault_runner/cli.py:28-103` — CLI wywoływane przez `kubectl exec`: kody wyjścia, opcjonalne `--seconds`, blokujący `spike`.
- `services/orders/src/orders/faults.py:235-237` — domyślne `seconds` awarii cpu (Task 1).
- `tests/observability/test_logs.py:43-66,129-146` — wzór wywołania `kubectl`, ponowień `fault_runner()` i odczytu konta Grafany, który powtarza `chaos/run.py`.
- `docs/architektura.md:278-297` — sekcja „Scenariusze awarii” z tabelą S1–S7 (Task 3).
- `deploy/base/fault-runner/deployment.yaml:54,61-73` i `deploy/base/intruder/deployment.yaml:39,49,52-58` — `/tmp` z `emptyDir` przy `readOnlyRootFilesystem`, potrzebny na pliki PID S6 i S7.

## Verification

Wszystko w korzeniu repo, w jednej powłoce bash, po `eval "$(mise env -s bash)"`: od tej chwili narzędzia z `mise.toml` są w PATH, a `jq` pochodzi z systemu. Jeśli liczba albo kod wyjścia się nie zgadza, zatrzymaj się i zgłoś wynik.

1. **Testy jednostkowe i lint** (bez klastra): `make lint` → kod 0; `make unit` → `140 passed`.
2. **Klaster.**
   - `docker info >/dev/null && echo docker-ok`, potem `make up` → kod 0. Nowy klaster dostaje obrazy z tej gałęzi.
   - Na klastrze sprzed gałęzi `make up` niczego nie restartuje, więc wykonaj:
     - `make images`;
     - `kubectl --context kind-secure-k8s-aiops -n shop rollout restart deployment/orders`;
     - `kubectl --context kind-secure-k8s-aiops -n shop rollout status deployment/orders`.
   - Do końca kroku 8 na klastrze działa tylko Locust i orkiestrator: bez `make test-security`, `tests/observability`, ręcznych poleceń `fault-runner` poza krokiem 3 i bez `make deploy`.
3. **Domyślny czas cpu (Task 1):**

```bash
K="kubectl --context kind-secure-k8s-aiops"
date -u +%T; $K -n loadgen exec deploy/fault-runner -- fault-runner fault cpu   # ends_at = teraz + 4 min (±5 s)
$K -n loadgen exec deploy/fault-runner -- fault-runner stop                     # {"stopped":"cpu"}
```

4. **Kryterium 1: pełny przebieg.** `time uv run --locked python chaos/run.py --gap 1m --run-id t21-pelny` kończy się kodem 0 po ok. 29 min (8 × 1 min przerw + 21 min scenariuszy). Na stdout jest linia `run`, a po niej 7 par `start`/`end` dla S1…S7. Następnie:

```bash
R=reports/runs/t21-pelny
wc -l < $R/labels.jsonl                                   # 7
cat $R/run.json                                           # commit = $(git rev-parse HEAD), end ≠ null
uv run --locked python - <<'EOF'
import json
from datetime import datetime
for line in open("reports/runs/t21-pelny/labels.jsonl"):
    w = json.loads(line)
    seconds = datetime.fromisoformat(w["end"]) - datetime.fromisoformat(w["start"])
    print(w["scenario"], w["name"], w["target"], w["start"], int(seconds.total_seconds()))
EOF
```

   Oczekiwane linie (czasy w UTC z `+00:00`):
   - `S1 cpu orders … 240`;
   - `S2 memory orders … 180`;
   - `S3 errors orders … 180`;
   - `S4 latency orders … 180`;
   - `S5 crash orders … 180`;
   - `S6 spike frontend … 180–185`;
   - `S7 scan orders … 120–125`.
5. **HighCPU po S1 (decyzja S1 = 4 min).** `curl -s 'localhost:8025/api/v1/search?query=subject:HighCPU' | jq -r '.messages[].Subject'` → co najmniej jedna linia `[FIRING:1] HighCPU orders (…)`.
6. **Kryterium 2: adnotacje na dashboardzie.**

```bash
GA="admin:$(make -s grafana-password)"
FROM=$(date -d "$(jq -r .start $R/run.json)" +%s)000
TO=$(date -d "$(jq -r .end $R/run.json)" +%s)000
curl -sf -u "$GA" "http://localhost:3000/api/annotations?tags=scenario&from=$FROM&to=$TO&limit=100" \
  | jq -r '.[] | "\(.tags | join(",")) \((.timeEnd - .time) / 1000)"' | sort   # 7 linii: scenario,S1 240 … scenario,S7 120–125
PROM_UID=$(curl -sf -u "$GA" http://localhost:3000/api/datasources | jq -r 'map(select(.type == "prometheus"))[0].uid')
cat > /tmp/t21-adnotacje.json <<EOF
{
  "overwrite": true,
  "dashboard": {
    "uid": "t21-adnotacje",
    "title": "T21 · adnotacje scenariuszy (tymczasowy)",
    "schemaVersion": 39,
    "annotations": {"list": [{
      "name": "Scenariusze",
      "datasource": {"type": "grafana", "uid": "-- Grafana --"},
      "enable": true,
      "iconColor": "red",
      "target": {"type": "tags", "tags": ["scenario"], "matchAny": false, "limit": 100}
    }]},
    "panels": [
      {"id": 1, "type": "timeseries", "title": "CPU / limit", "gridPos": {"x": 0, "y": 0, "w": 12, "h": 8},
       "datasource": {"type": "prometheus", "uid": "$PROM_UID"},
       "targets": [{"refId": "A", "expr": "service:cpu_usage_ratio_of_limit"}]},
      {"id": 2, "type": "timeseries", "title": "Pamięć / limit", "gridPos": {"x": 12, "y": 0, "w": 12, "h": 8},
       "datasource": {"type": "prometheus", "uid": "$PROM_UID"},
       "targets": [{"refId": "A", "expr": "service:memory_working_set_ratio_of_limit"}]},
      {"id": 3, "type": "timeseries", "title": "Udział 5xx i p95 (s)", "gridPos": {"x": 0, "y": 8, "w": 12, "h": 8},
       "datasource": {"type": "prometheus", "uid": "$PROM_UID"},
       "targets": [{"refId": "A", "expr": "service:http_errors_ratio:rate1m"},
                   {"refId": "B", "expr": "service:http_latency_p95_seconds:1m"}]},
      {"id": 4, "type": "timeseries", "title": "Żądania/s, restarty, odrzucenia/s", "gridPos": {"x": 12, "y": 8, "w": 12, "h": 8},
       "datasource": {"type": "prometheus", "uid": "$PROM_UID"},
       "targets": [{"refId": "A", "expr": "service:http_requests:rate1m"},
                   {"refId": "B", "expr": "service:restarts:increase5m"},
                   {"refId": "C", "expr": "service:policy_drops:rate1m"}]}
    ]
  }
}
EOF
curl -sf -u "$GA" -H 'Content-Type: application/json' -d @/tmp/t21-adnotacje.json \
  http://localhost:3000/api/dashboards/db | jq -r .status                         # success
echo "http://localhost:3000/d/t21-adnotacje?from=$FROM&to=$TO"
```

   - Otwórz wypisany adres (login `admin`, hasło z `make grafana-password`).
   - Na wszystkich 4 panelach musi być 7 czerwonych regionów; podpis po najechaniu to np. `S1 cpu → orders, przebieg t21-pelny` z tagami `scenario`, `S1`. Regiony leżą nad skokami CPU (S1), pamięci (S2), 5xx (S3), p95 (S4), restartów (S5), żądań frontendu (S6) i odrzuceń (S7).
   - Zrób zrzut ekranu do komentarza w #21.
   - Sprzątanie: `curl -sf -u "$GA" -X DELETE http://localhost:3000/api/dashboards/uid/t21-adnotacje && rm /tmp/t21-adnotacje.json`.
7. **S7 celuje w pod (6 portów, `POLICY_DENIED`).**
   - W drugim terminalu: `make hubble-relay`.
   - W pierwszym: `uv run --locked python chaos/run.py --scenarios S7 --gap 0s --run-id t21-s7` → kod 0 po ok. 2 min. Zaraz potem:

```bash
hubble observe --server localhost:4245 --verdict DROPPED --from-namespace intruder --to-namespace shop \
  --since 3m --output json \
  | jq -r 'select(.flow) | "\(.flow.drop_reason_desc) \(.flow.destination.workloads[0].name) \(.flow.l4.TCP.destination_port)"' \
  | sort | uniq -c   # 6 linii: POLICY_DENIED orders 22|443|5432|6379|80|8080
```

8. **Ctrl+C w S6 i S7.** `set -m` daje zadaniu w tle własną grupę procesów, więc `kill -INT` do grupy działa jak Ctrl+C w terminalu:

```bash
set -m; uv run --locked python chaos/run.py --scenarios S6 --gap 0s --run-id t21-ctrlc-s6 & pid=$!; set +m
sleep 40; kill -INT -- -"$pid"; wait "$pid"; echo "kod $?"                       # kod 130, stderr: interrupted
cat reports/runs/t21-ctrlc-s6/labels.jsonl reports/runs/t21-ctrlc-s6/run.json   # 1 okno S6, end − start = 40 ± 3 s; end ≠ null
$K -n loadgen exec deploy/fault-runner -- python -c "import pathlib; m = b'sp' + b'ike'; print(sum(m in p.read_bytes() for p in pathlib.Path('/proc').glob('[0-9]*/cmdline') if p.exists()))"   # 0
set -m; uv run --locked python chaos/run.py --scenarios S7 --gap 0s --run-id t21-ctrlc-s7 & pid=$!; set +m
sleep 30; kill -INT -- -"$pid"; wait "$pid"; echo "kod $?"                       # kod 130
$K -n intruder exec deploy/intruder -- ps -o pid,args                           # tylko PID 1 (sh -c trap …), sleep infinity i ps; bez curl i chaos-s7
```

   Adnotacje obu przerwanych okien widać w `GET /api/annotations?tags=S6` i `?tags=S7`.
9. **Błąd przed startem.** `KUBE_CONTEXT=nie-ma uv run --locked python chaos/run.py --run-id t21-zly; echo "kod $?"` → kod 1, stderr `cannot read secret monitoring/grafana-admin: …`. `ls reports/runs/t21-zly` → brak katalogu.

## Po dostarczeniu (GitHub)

- PR „T21 · Orkiestrator scenariuszy awarii z etykietami” z `Closes #21`. W opisie: kontrakt (`labels.jsonl`, `run.json`, adnotacje, Ctrl+C), S1 = 4 min i wyniki kroków 1 oraz 4–9.
- Komentarz w #21 mapuje kryteria na dowody:
  - kryterium 1 → `labels.jsonl` z `t21-pelny` (7 linii);
  - kryterium 2 → wynik `GET /api/annotations` (7 okien) i zrzut tymczasowego dashboardu.
- Komentarze w zależnych zadaniach:
  - #22: JSON zapytania adnotacji i tagi `scenario` + ID;
  - #28: `uv run --locked python chaos/run.py --scenarios S1,S3,S7 --gap 4m --run-id <id>` trwa ok. 25 min, kody wyjścia 0/1/2/130, wyniki w `reports/runs/<id>/`;
  - #23 i #30: format `labels.jsonl` i `run.json`; okno S6 i S7 kończy się razem z poleceniem;
  - #24 i #27: S1 trwa teraz 4 min.

## Assumptions & contingencies

- **`--gap` i kolejność.** `--gap` działa jak w prototypie (przerwa przed każdym scenariuszem i po ostatnim), a kolejność bierze się z `--scenarios`, bez losowania. Inna semantyka wymaga zmiany `Orchestrator.run` i testu `test_full_run_writes_seven_windows_separated_by_gap`.
- **`kubectl exec` po przerwaniu klienta.** Plan zakłada, że proces w kontenerze dalej działa [INFERENCE]. Jeśli kubelet sam go kończy, `kill` z pliku PID zawiedzie z „no such process”. To tylko `warning`, więc zachowanie zostaje poprawne i nic nie trzeba zmieniać.
- **Krok 5: brak e-maila HighCPU przy S1 = 4 min.** Dopisz zmierzone wartości `service:cpu_usage_ratio_of_limit{service="orders"}` z okna S1 w punkcie „S1 i HighCPU” w `docs/detekcja.md` i zgłoś wynik. T21 nie zmienia reguły `HighCPU`.
- **Krok 7: odrzucenia tylko na 8080 albo powód inny niż `POLICY_DENIED`.** Zatrzymaj się i zgłoś: ruch na IP poda nie trafia wtedy do polityki orders, a S7 nie daje kontraktowego skanu.
- **Krok 6: `PROM_UID` pusty albo panele bez danych.** Sprawdź `curl -sf -u "$GA" http://localhost:3000/api/datasources | jq -r '.[] | "\(.type) \(.uid)"'` i wpisz uid Prometheusa. Jeśli regiony adnotacji się nie rysują, dodaj zapytanie w UI (Dashboard settings → Annotations → `-- Grafana --`, Filter by Tags, `scenario`). Wyeksportowany JSON zapytania zastępuje wtedy blok w `docs/architektura.md` (Task 3) i trafia do PR.
- **Krok 8: brak `ps` w obrazie intrudera.** Użyj `$K -n intruder exec deploy/intruder -- sh -c 'for f in /proc/[0-9]*/cmdline; do tr "\0" " " < "$f"; echo; done'`; nie może być linii z `curl` ani `chaos-s7`.
- **Port 3000 zajęty albo Grafana nie odpowiada.** Orkiestrator kończy się kodem 1 przed pierwszym scenariuszem. Zwolnij `127.0.0.1:3000` albo powtórz `make up`.
- **`main` po `git pull` bez T20 (#67).** Orkiestrator od T20 nie zależy, więc kontynuuj. `make unit` da wtedy `123 passed` (96 + 27) zamiast 140.
