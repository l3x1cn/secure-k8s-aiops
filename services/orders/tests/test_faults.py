import asyncio
import mmap
import time
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from orders.app import Settings, create_app
from orders.faults import FaultController
from prometheus_client import REGISTRY

TOKEN = "test-token"
FAULT_TOKEN = "fault-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
FAULT_AUTH = {"X-Fault-Token": FAULT_TOKEN}
ORDER = {"product_id": "kubek", "quantity": 2}
FAULT_PATHS = [
    "/faults/cpu",
    "/faults/memory",
    "/faults/errors",
    "/faults/latency",
    "/faults/crash",
    "/faults/stop",
]
MiB = 1024 * 1024


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def cgroup(tmp_path: Path) -> Path:
    (tmp_path / "memory.max").write_text("max\n")
    (tmp_path / "memory.current").write_text("0\n")
    return tmp_path


@pytest.fixture
def crashes() -> list[int]:
    return []


@pytest.fixture
def client(cgroup: Path, crashes: list[int]):
    settings = Settings(
        api_token=TOKEN, faults_enabled=True, fault_token=FAULT_TOKEN, cgroup_dir=cgroup
    )
    client = TestClient(create_app(settings, crash=lambda: crashes.append(1)))
    yield client
    client.post("/faults/stop", headers=FAULT_AUTH)


def order_statuses(client: TestClient, n: int) -> list[int]:
    return [
        client.post("/orders", json=ORDER, headers=AUTH).status_code for _ in range(n)
    ]


def rss_bytes() -> int:
    return int(Path("/proc/self/statm").read_text().split()[1]) * mmap.PAGESIZE


@pytest.mark.parametrize("path", FAULT_PATHS)
def test_faults_are_404_when_disabled(path):
    client = TestClient(create_app(Settings(api_token=TOKEN)))
    assert client.post(path, headers=FAULT_AUTH).status_code == 404


@pytest.mark.parametrize("path", FAULT_PATHS)
@pytest.mark.parametrize(
    "headers",
    [{}, {"X-Fault-Token": "wrong"}, {"X-Fault-Token": f"{FAULT_TOKEN}x"}, AUTH],
    ids=["missing", "wrong", "token-prefix", "orders-token"],
)
def test_faults_reject_requests_without_valid_fault_token(
    client, crashes, path, headers
):
    assert client.post(path, headers=headers).status_code == 403
    assert order_statuses(client, 4) == [201] * 4
    assert crashes == []


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/faults/errors", {"ratio": 1.5}),
        ("/faults/errors", {"ratio": 0}),
        ("/faults/memory", {"target_ratio": 0.99}),
        ("/faults/latency", {"ms": 0}),
        ("/faults/cpu", {"seconds": 0}),
    ],
)
def test_out_of_range_parameters_are_rejected(client, path, params):
    assert client.post(path, params=params, headers=FAULT_AUTH).status_code == 422


@pytest.mark.parametrize(
    ("ratio", "expected_errors"), [(0.5, 10), (0.25, 5), (0.1, 2), (1, 20)]
)
def test_errors_fault_fails_given_share_of_orders(client, ratio, expected_errors):
    started = client.post(
        "/faults/errors", params={"seconds": 60, "ratio": ratio}, headers=FAULT_AUTH
    )
    assert started.status_code == 202
    assert started.json()["fault"] == "errors"

    statuses = order_statuses(client, 20)
    assert statuses.count(500) == expected_errors
    assert statuses.count(201) == 20 - expected_errors


def test_errors_fault_is_counted_with_route_label(client):
    labels = {"method": "POST", "route": "/orders", "status": "500"}
    before = REGISTRY.get_sample_value("http_requests_total", labels) or 0.0
    client.post("/faults/errors", params={"ratio": 1}, headers=FAULT_AUTH)
    order_statuses(client, 3)
    assert REGISTRY.get_sample_value("http_requests_total", labels) == before + 3


def test_stop_restores_normal_responses(client):
    client.post("/faults/errors", params={"ratio": 1}, headers=FAULT_AUTH)
    assert order_statuses(client, 2) == [500, 500]

    stopped = client.post("/faults/stop", headers=FAULT_AUTH)
    assert stopped.status_code == 200
    assert stopped.json() == {"stopped": "errors"}
    assert order_statuses(client, 4) == [201] * 4
    assert client.post("/faults/stop", headers=FAULT_AUTH).json() == {"stopped": None}


def test_latency_fault_delays_orders_until_stopped(client):
    client.post("/faults/latency", params={"ms": 200}, headers=FAULT_AUTH)
    start = time.perf_counter()
    assert order_statuses(client, 1) == [201]
    assert time.perf_counter() - start >= 0.2

    client.post("/faults/stop", headers=FAULT_AUTH)
    start = time.perf_counter()
    order_statuses(client, 1)
    assert time.perf_counter() - start < 0.1


def test_new_fault_replaces_running_one(client):
    client.post("/faults/errors", params={"ratio": 1}, headers=FAULT_AUTH)
    client.post("/faults/latency", params={"ms": 1}, headers=FAULT_AUTH)
    assert order_statuses(client, 3) == [201] * 3
    assert client.post("/faults/stop", headers=FAULT_AUTH).json() == {
        "stopped": "latency"
    }


def test_fault_ends_after_its_duration(cgroup):
    clock = FakeClock()
    controller = FaultController(cgroup, clock=clock)
    controller.start_errors(seconds=10, ratio=1)
    with pytest.raises(HTTPException):
        asyncio.run(controller.apply())

    clock.now += 10
    asyncio.run(controller.apply())
    assert controller.stop() is None


def test_cpu_fault_burns_cpu_until_stopped(client):
    assert client.post("/faults/cpu", headers=FAULT_AUTH).status_code == 202
    cpu_before = time.process_time()
    time.sleep(0.3)
    assert time.process_time() - cpu_before >= 0.2

    client.post("/faults/stop", headers=FAULT_AUTH)
    cpu_before = time.process_time()
    time.sleep(0.3)
    assert time.process_time() - cpu_before < 0.1


def test_memory_fault_needs_container_limit(client):
    response = client.post("/faults/memory", headers=FAULT_AUTH)
    assert response.status_code == 409


def test_memory_fault_fills_limit_and_releases_on_stop(client, cgroup):
    (cgroup / "memory.max").write_text(f"{400 * MiB}\n")
    (cgroup / "memory.current").write_text(f"{100 * MiB}\n")
    baseline = rss_bytes()

    started = client.post(
        "/faults/memory", params={"target_ratio": 0.5}, headers=FAULT_AUTH
    )
    assert started.status_code == 202
    # 0.5 x 400 MiB - 100 MiB już zużyte = 100 MiB do zajęcia.
    deadline = time.monotonic() + 5
    while rss_bytes() - baseline < 95 * MiB and time.monotonic() < deadline:
        time.sleep(0.05)
    assert 95 * MiB <= rss_bytes() - baseline <= 110 * MiB

    client.post("/faults/stop", headers=FAULT_AUTH)
    assert rss_bytes() - baseline < 10 * MiB


def test_crash_fault_answers_then_exits(client, crashes):
    response = client.post("/faults/crash", headers=FAULT_AUTH)
    assert response.status_code == 202
    assert response.json()["fault"] == "crash"
    assert crashes == [1]


def test_faults_require_fault_token_setting():
    with pytest.raises(ValueError, match="FAULT_TOKEN"):
        Settings(api_token=TOKEN, faults_enabled=True)


@pytest.mark.parametrize(
    ("value", "enabled"),
    [("true", True), ("false", False), ("1", False), (None, False)],
)
def test_faults_enabled_only_by_exact_true(monkeypatch, value, enabled):
    monkeypatch.setenv("ORDERS_API_TOKEN", TOKEN)
    monkeypatch.setenv("FAULT_TOKEN", FAULT_TOKEN)
    if value is None:
        monkeypatch.delenv("FAULTS_ENABLED", raising=False)
    else:
        monkeypatch.setenv("FAULTS_ENABLED", value)
    assert Settings.from_env().faults_enabled is enabled
