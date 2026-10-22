import io
import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from observability import instrument, setup_logging
from prometheus_client import REGISTRY

CONTRACT_FIELDS = {"ts", "level", "service", "route", "status", "duration_ms", "msg"}


@pytest.fixture
def log_stream():
    root = logging.getLogger()
    test_client_logger = logging.getLogger("httpx2")
    saved_handlers, saved_level = root.handlers[:], root.level
    saved_client_level = test_client_logger.level
    stream = io.StringIO()
    setup_logging("demo", stream=stream)
    # TestClient loguje własne żądania; w logu mają zostać tylko wpisy usługi.
    test_client_logger.setLevel(logging.WARNING)
    yield stream
    root.handlers[:] = saved_handlers
    root.setLevel(saved_level)
    test_client_logger.setLevel(saved_client_level)


@pytest.fixture
def client():
    app = FastAPI()
    instrument(app)

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.get("/items/{item_id}")
    def item(item_id: str):
        return {"id": item_id}

    @app.get("/boom")
    def boom():
        raise RuntimeError("boom")

    return TestClient(app, raise_server_exceptions=False)


def requests_total(method: str, route: str, status: str) -> float:
    labels = {"method": method, "route": route, "status": status}
    return REGISTRY.get_sample_value("http_requests_total", labels) or 0.0


def log_lines(stream: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_route_label_is_template_not_raw_path(client):
    before = requests_total("GET", "/items/{item_id}", "200")
    client.get("/items/a")
    client.get("/items/b")
    assert requests_total("GET", "/items/{item_id}", "200") == before + 2
    assert (
        REGISTRY.get_sample_value(
            "http_requests_total",
            {"method": "GET", "route": "/items/a", "status": "200"},
        )
        is None
    )


def test_unknown_paths_share_one_label(client):
    before = requests_total("GET", "unmatched", "404")
    assert client.get("/nope/1").status_code == 404
    client.get("/nope/2")
    assert requests_total("GET", "unmatched", "404") == before + 2


def test_probes_and_scrapes_are_not_counted(client):
    before = (
        requests_total("GET", "/healthz", "200"),
        requests_total("GET", "/metrics", "200"),
    )
    client.get("/healthz")
    client.get("/metrics")
    after = (
        requests_total("GET", "/healthz", "200"),
        requests_total("GET", "/metrics", "200"),
    )
    assert after == before == (0.0, 0.0)


def test_metrics_endpoint_exposes_contract_metrics(client):
    client.get("/items/x")
    body = client.get("/metrics").text
    assert "http_requests_total{" in body
    assert "http_request_duration_seconds_bucket{" in body
    assert 'le="0.3"' in body
    assert "process_cpu_seconds_total" in body


def test_unhandled_exception_is_counted_and_logged_as_500(client, log_stream):
    before = requests_total("GET", "/boom", "500")
    response = client.get("/boom")
    assert response.status_code == 500
    assert requests_total("GET", "/boom", "500") == before + 1
    [entry] = [e for e in log_lines(log_stream) if e["route"] == "/boom"]
    assert entry["level"] == "ERROR"
    assert entry["status"] == 500
    assert "RuntimeError: boom" in entry["exc"]


def test_request_log_has_contract_fields(client, log_stream):
    client.get("/items/x")
    client.get("/healthz")
    [entry] = log_lines(log_stream)
    assert CONTRACT_FIELDS <= entry.keys()
    assert entry["service"] == "demo"
    assert entry["level"] == "INFO"
    assert entry["route"] == "/items/{item_id}"
    assert entry["status"] == 200
    assert entry["duration_ms"] >= 0
    assert entry["msg"] == "GET /items/x"


def test_client_errors_log_as_warning(client, log_stream):
    client.get("/nope")
    [entry] = log_lines(log_stream)
    assert entry["level"] == "WARNING"


def test_non_request_logs_keep_contract_shape(log_stream):
    logging.getLogger("uvicorn.error").critical("shutting down")
    [entry] = log_lines(log_stream)
    assert CONTRACT_FIELDS <= entry.keys()
    assert entry["level"] == "ERROR"
    assert (entry["route"], entry["status"], entry["duration_ms"]) == (None, None, None)
