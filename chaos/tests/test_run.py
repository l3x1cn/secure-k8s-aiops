import base64
import importlib.util
import json
import re
import signal
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
        # Fragment polecenia, na którym kubectl dostaje Ctrl+C (raz).
        self.interrupt_on: str | None = None
        self.orders_ip = ORDERS_IP
        self.secret = json.dumps(
            {"data": {"admin-user": b64("admin"), "admin-password": b64("sekret")}}
        )

    def __call__(self, args: Sequence[str], timeout: float):
        args = tuple(args)
        self.calls.append((self.clock.now(), args))
        command = " ".join(args)
        if self.interrupt_on is not None and self.interrupt_on in command:
            self.interrupt_on = None
            raise KeyboardInterrupt
        if args[:3] == ("get", "secret", "grafana-admin"):
            return completed(stdout=self.secret) if self.secret else completed(1)
        if args[:2] == ("get", "pods"):
            return completed(stdout=self.orders_ip)
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
        self.sigint_on_annotation = False
        self.requests: list[httpx.Request] = []
        self.annotations: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.unreachable:
            raise httpx.ConnectError("Connection refused", request=request)
        self.requests.append(request)
        if (request.method, request.url.path) == ("GET", "/api/org"):
            return httpx.Response(self.org_status, json={"id": 1})
        if (request.method, request.url.path) == ("POST", "/api/annotations"):
            if self.sigint_on_annotation:
                self.sigint_on_annotation = False
                signal.raise_signal(signal.SIGINT)
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
    assert start(env) == 0

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


def test_every_window_gets_a_scenario_annotation(env, capsys):
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
    assert [a["text"] for a in env.grafana.annotations] == [
        "S3 errors → orders, przebieg t21",
        "S7 scan → orders, przebieg t21",
    ]
    progress = [line.split(" ", 1)[1] for line in capsys.readouterr().out.splitlines()]
    assert progress == [
        f"run t21 {env.runs / 't21'}",
        "start S3 errors orders",
        "end S3 errors orders",
        "start S7 scan orders",
        "end S7 scan orders",
    ]
    auth = env.grafana.requests[-1].headers["Authorization"]
    assert auth == f"Basic {b64('admin:sekret')}"
    assert {r.url.host for r in env.grafana.requests} == {"127.0.0.1"}


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


def test_failed_cleanup_command_is_only_a_warning(env, capsys):
    env.cluster.codes["read pid"] = [1]
    env.clock.interrupt_at = START + timedelta(seconds=30)

    assert start(env, "--scenarios", "S6", "--gap", "0s", "--run-id", "t21") == 130

    err = capsys.readouterr().err
    assert "warning: sh -c" in err
    assert "in loadgen/fault-runner failed" in err
    assert last_exec(env) == ("loadgen/fault-runner", ("fault-runner", "stop"))
    [window] = windows(env.runs / "t21")
    assert (window["end"] - window["start"]).total_seconds() == 30


def test_ctrl_c_before_run_starts_exits_without_cleanup(env, capsys):
    env.cluster.interrupt_on = "get secret"

    assert start(env, "--run-id", "t21") == 130

    assert "interrupted" in capsys.readouterr().err
    assert env.cluster.execs() == []
    assert not (env.runs / "t21").exists()


def test_scan_without_running_orders_pod_stops_run(env, capsys):
    env.cluster.orders_ip = ""

    assert start(env, "--scenarios", "S7", "--gap", "0s", "--run-id", "t21") == 1

    assert "S7 scan failed: no running orders pod" in capsys.readouterr().err
    assert last_exec(env) == ("loadgen/fault-runner", ("fault-runner", "stop"))
    assert env.cluster.execs()[0][1] == "intruder/intruder"


def test_unreadable_git_commit_stops_before_any_scenario(
    env, capsys, monkeypatch, tmp_path
):
    monkeypatch.setattr(chaos_run, "REPO_ROOT", tmp_path)

    assert start(env, "--run-id", "t21") == 1

    assert "cannot read git commit" in capsys.readouterr().err
    assert env.cluster.execs() == []
    assert not (env.runs / "t21").exists()


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


def test_ctrl_c_during_annotation_post_still_delivers_it(env, capsys):
    env.grafana.sigint_on_annotation = True

    code = start(env, "--scenarios", "S1,S2", "--gap", "0s", "--run-id", "t21")

    assert code == 130
    assert "interrupted" in capsys.readouterr().err
    labels = windows(env.runs / "t21")
    assert [w["scenario"] for w in labels] == ["S1"]
    assert [a["tags"][1] for a in env.grafana.annotations] == ["S1"]
    assert last_exec(env) == ("loadgen/fault-runner", ("fault-runner", "stop"))
    assert utc(run_json(env.runs / "t21")["end"]) == labels[0]["end"]


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
