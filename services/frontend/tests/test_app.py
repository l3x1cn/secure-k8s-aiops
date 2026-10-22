import json

import httpx
import pytest
from fastapi.testclient import TestClient
from frontend.app import PRODUCTS, Settings, create_app

TOKEN = "test-token"
ORDER = {
    "id": "abc123",
    "product_id": "kubek",
    "quantity": 2,
    "created_at": "2026-10-22T12:00:00Z",
}


def make_client(handler) -> TestClient:
    settings = Settings(orders_api_token=TOKEN, orders_url="http://orders.test")
    app = create_app(settings, transport=httpx.MockTransport(handler))
    return TestClient(app)


def orders_ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(201, json=ORDER)


def test_lists_products():
    with make_client(orders_ok) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert {p["id"] for p in response.json()} == set(PRODUCTS)


def test_order_is_forwarded_to_orders_with_token():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json=ORDER)

    with make_client(handler) as client:
        response = client.post("/order", json={"product_id": "kubek", "quantity": 2})

    assert response.status_code == 201
    assert response.json()["id"] == "abc123"
    [request] = seen
    assert request.method == "POST"
    assert str(request.url) == "http://orders.test/orders"
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert json.loads(request.content) == {"product_id": "kubek", "quantity": 2}


def test_unknown_product_does_not_reach_orders():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("orders must not be called")

    with make_client(handler) as client:
        response = client.post("/order", json={"product_id": "rakieta"})
    assert response.status_code == 404


def raise_timeout(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("timed out", request=request)


def raise_connect_error(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused", request=request)


@pytest.mark.parametrize(
    "handler",
    [
        raise_timeout,
        raise_connect_error,
        lambda request: httpx.Response(
            401, json={"detail": "invalid or missing token"}
        ),
        lambda request: httpx.Response(500, text="Internal Server Error"),
        lambda request: httpx.Response(201, text="not json"),
    ],
    ids=["timeout", "connect-error", "401", "500", "invalid-body"],
)
def test_orders_failure_is_502(handler):
    with make_client(handler) as client:
        response = client.post("/order", json={"product_id": "kubek"})
    assert response.status_code == 502


def test_metrics_report_order_outcomes():
    with make_client(raise_timeout) as client:
        client.post("/order", json={"product_id": "kubek"})
        body = client.get("/metrics").text
    assert 'http_requests_total{method="POST",route="/order",status="502"}' in body


def test_settings_require_token(monkeypatch):
    monkeypatch.delenv("ORDERS_API_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="ORDERS_API_TOKEN"):
        Settings.from_env()
