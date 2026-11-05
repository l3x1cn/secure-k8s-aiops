import json
import time
from collections import Counter
from pathlib import Path

import httpx
import pytest
from fault_runner.cli import main

FAULT_TOKEN = "fault-token"
PRODUCTS = [{"id": "kubek"}, {"id": "bluza"}]


class RecordingOrders:
    def __init__(self, status_code: int = 202) -> None:
        self.status_code = status_code
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status_code, json={"fault": "errors"})


@pytest.fixture
def token_file(tmp_path: Path) -> Path:
    path = tmp_path / "token"
    path.write_text(f"{FAULT_TOKEN}\n")
    return path


def run(token_file: Path, handler, *args: str) -> int:
    return main(
        ["--orders-url", "http://orders:8080", "--token-file", str(token_file), *args],
        transport=httpx.MockTransport(handler),
    )


def test_fault_posts_parameters_with_token(token_file, capsys):
    orders = RecordingOrders()
    code = run(
        token_file, orders, "fault", "errors", "--seconds", "60", "--param", "ratio=0.5"
    )

    assert code == 0
    [request] = orders.requests
    assert request.method == "POST"
    assert request.url.path == "/faults/errors"
    assert dict(request.url.params) == {"ratio": "0.5", "seconds": "60"}
    assert request.headers["X-Fault-Token"] == FAULT_TOKEN
    assert json.loads(capsys.readouterr().out) == {"fault": "errors"}


def test_fault_without_seconds_leaves_default_to_orders(token_file):
    orders = RecordingOrders()
    assert run(token_file, orders, "fault", "crash") == 0
    assert orders.requests[0].url.path == "/faults/crash"
    assert "seconds" not in orders.requests[0].url.params


def test_stop_posts_to_stop_endpoint(token_file):
    orders = RecordingOrders(status_code=200)
    assert run(token_file, orders, "stop") == 0
    assert orders.requests[0].url.path == "/faults/stop"


@pytest.mark.parametrize("status_code", [403, 404, 409, 500])
def test_rejected_fault_exits_with_error(token_file, capsys, status_code):
    assert run(token_file, RecordingOrders(status_code), "fault", "cpu") == 1
    assert str(status_code) in capsys.readouterr().err


def test_unreachable_orders_exits_with_error(token_file, capsys):
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    assert run(token_file, refuse, "stop") == 1
    assert "unreachable" in capsys.readouterr().err


def test_missing_token_file_exits_without_request(tmp_path, capsys):
    orders = RecordingOrders()
    assert run(tmp_path / "missing", orders, "fault", "cpu") == 1
    assert orders.requests == []
    assert "fault token" in capsys.readouterr().err


@pytest.mark.parametrize("param", ["ratio", "=0.5"])
def test_malformed_param_is_rejected(token_file, param):
    with pytest.raises(SystemExit):
        run(token_file, RecordingOrders(), "fault", "errors", "--param", param)


def test_unknown_fault_is_rejected(token_file):
    with pytest.raises(SystemExit):
        run(token_file, RecordingOrders(), "fault", "disk")


def test_spike_sends_user_cycles_to_frontend_for_given_time(token_file, capsys):
    seen: Counter[tuple[str, str]] = Counter()
    ordered: list[str] = []

    def frontend(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "frontend"
        seen[(request.method, request.url.path)] += 1
        if request.method == "GET":
            return httpx.Response(200, json=PRODUCTS)
        ordered.append(json.loads(request.content)["product_id"])
        return httpx.Response(201, json={})

    start = time.monotonic()
    code = main(
        [
            "--frontend-url",
            "http://frontend:8080",
            "spike",
            "--users",
            "4",
            "--seconds",
            "1",
            "--wait",
            "0.3",
        ],
        transport=httpx.MockTransport(frontend),
    )
    elapsed = time.monotonic() - start

    assert code == 0
    assert 1 <= elapsed < 1.5
    # 4 użytkowników, cykl co ~0.3 s przez 1 s: do 4 cykli na użytkownika
    # (ostatni, w 0.9 s, może nie zdążyć na wolnej maszynie).
    cycles = seen[("GET", "/")]
    assert seen[("POST", "/order")] == cycles
    assert 12 <= cycles <= 16
    assert set(ordered) == {"kubek", "bluza"}
    assert json.loads(capsys.readouterr().out) == {"200": cycles, "201": cycles}
