"""Publiczna usługa sklepu: katalog produktów i składanie zamówień przez API `orders`."""

import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime

import httpx
from fastapi import FastAPI, HTTPException, Request, status
from observability import instrument
from pydantic import BaseModel, Field, ValidationError

SERVICE = "frontend"
ORDERS_TIMEOUT_SECONDS = 2.0

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Settings:
    orders_api_token: str
    orders_url: str = "http://orders:8080"
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "Settings":
        token = os.environ.get("ORDERS_API_TOKEN")
        if not token:
            raise RuntimeError("ORDERS_API_TOKEN is not set")
        return cls(
            orders_api_token=token,
            orders_url=os.environ.get("ORDERS_URL", cls.orders_url),
            log_level=os.environ.get("LOG_LEVEL", cls.log_level),
        )


class Product(BaseModel):
    id: str
    name: str
    price_pln: float


PRODUCTS = {
    p.id: p
    for p in (
        Product(id="kubek", name="Kubek z logo Kubernetes", price_pln=39.0),
        Product(id="koszulka", name="Koszulka „kubectl apply”", price_pln=89.0),
        Product(id="naklejki", name="Zestaw naklejek CNCF", price_pln=19.0),
        Product(id="bluza", name="Bluza z kapturem Cilium", price_pln=179.0),
        Product(id="czapka", name="Czapka Hubble", price_pln=59.0),
    )
}


class OrderRequest(BaseModel):
    product_id: str
    quantity: int = Field(default=1, ge=1, le=100)


class Order(BaseModel):
    id: str
    product_id: str
    quantity: int
    created_at: datetime


def create_app(
    settings: Settings, transport: httpx.AsyncBaseTransport | None = None
) -> FastAPI:
    """`transport` podmienia połączenie z orders w testach."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with httpx.AsyncClient(
            base_url=settings.orders_url,
            timeout=ORDERS_TIMEOUT_SECONDS,
            headers={"Authorization": f"Bearer {settings.orders_api_token}"},
            transport=transport,
        ) as client:
            app.state.orders = client
            yield

    app = FastAPI(
        title="frontend",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    instrument(app)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/")
    def list_products() -> list[Product]:
        return list(PRODUCTS.values())

    @app.post("/order", status_code=status.HTTP_201_CREATED)
    async def place_order(order_request: OrderRequest, request: Request) -> Order:
        if order_request.product_id not in PRODUCTS:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="unknown product")

        client: httpx.AsyncClient = request.app.state.orders
        try:
            response = await client.post("/orders", json=order_request.model_dump())
        except httpx.HTTPError as exc:
            logger.warning("orders request failed: %s", repr(exc))
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, detail="orders unavailable"
            ) from exc
        if response.status_code != status.HTTP_201_CREATED:
            logger.warning("orders responded with status %d", response.status_code)
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, detail="orders unavailable"
            )
        try:
            return Order.model_validate_json(response.content)
        except ValidationError as exc:
            logger.warning("orders returned an invalid order: %s", exc)
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, detail="orders unavailable"
            ) from exc

    return app
