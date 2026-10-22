import pytest
from fastapi.testclient import TestClient
from orders.app import Settings, create_app

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
ORDER = {"product_id": "kubek", "quantity": 2}


@pytest.fixture
def client():
    return TestClient(create_app(Settings(api_token=TOKEN)))


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer wrong-token"},
        {"Authorization": f"Basic {TOKEN}"},
        {"Authorization": f"Bearer {TOKEN}x"},
    ],
    ids=["missing", "wrong", "not-bearer", "token-prefix"],
)
def test_orders_reject_requests_without_valid_token(client, headers):
    created = client.post("/orders", json=ORDER, headers=headers)
    fetched = client.get("/orders/any", headers=headers)
    assert created.status_code == fetched.status_code == 401
    assert created.headers["WWW-Authenticate"] == "Bearer"


def test_created_order_can_be_fetched(client):
    created = client.post("/orders", json=ORDER, headers=AUTH)
    assert created.status_code == 201
    order = created.json()
    assert order["product_id"] == "kubek" and order["quantity"] == 2

    fetched = client.get(f"/orders/{order['id']}", headers=AUTH)
    assert fetched.status_code == 200
    assert fetched.json() == order


def test_unknown_order_is_404(client):
    assert client.get("/orders/missing", headers=AUTH).status_code == 404


@pytest.mark.parametrize(
    "body", [{"product_id": "kubek", "quantity": 0}, {"quantity": 1}]
)
def test_invalid_order_is_rejected(client, body):
    assert client.post("/orders", json=body, headers=AUTH).status_code == 422


def test_store_evicts_oldest_orders_over_limit():
    client = TestClient(create_app(Settings(api_token=TOKEN, max_orders=2)))
    ids = [
        client.post("/orders", json=ORDER, headers=AUTH).json()["id"] for _ in range(3)
    ]
    assert client.get(f"/orders/{ids[0]}", headers=AUTH).status_code == 404
    assert all(
        client.get(f"/orders/{i}", headers=AUTH).status_code == 200 for i in ids[1:]
    )


def test_metrics_report_orders_routes(client):
    client.post("/orders", json=ORDER, headers=AUTH)
    client.post("/orders", json=ORDER)
    body = client.get("/metrics").text
    assert 'http_requests_total{method="POST",route="/orders",status="201"}' in body
    assert 'http_requests_total{method="POST",route="/orders",status="401"}' in body


def test_settings_require_token(monkeypatch):
    monkeypatch.delenv("ORDERS_API_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="ORDERS_API_TOKEN"):
        Settings.from_env()
