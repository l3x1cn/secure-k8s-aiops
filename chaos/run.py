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
