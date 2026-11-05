"""Wewnętrzne API zamówień. Każdy endpoint /orders wymaga tokenu z Secretu `orders-api-token`.

Przy FAULTS_ENABLED=true dochodzą endpointy /faults/* (orders.faults).
"""

import hmac
import os
import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from observability import instrument
from pydantic import BaseModel, Field

from orders.faults import FaultController, crash_process, fault_router

SERVICE = "orders"


@dataclass(frozen=True)
class Settings:
    api_token: str
    # Limit magazynu w pamięci: stały ruch z Locusta nie może powoli zjadać pamięci,
    # bo pamięć poda jest cechą detekcji anomalii (scenariusz S2).
    max_orders: int = 10_000
    log_level: str = "INFO"
    faults_enabled: bool = False
    fault_token: str | None = None
    # Limit i zużycie pamięci kontenera dla awarii memory (cgroup v2).
    cgroup_dir: Path = Path("/sys/fs/cgroup")

    def __post_init__(self) -> None:
        if self.faults_enabled and not self.fault_token:
            raise ValueError("FAULT_TOKEN is required when FAULTS_ENABLED=true")

    @classmethod
    def from_env(cls) -> "Settings":
        token = os.environ.get("ORDERS_API_TOKEN")
        if not token:
            raise RuntimeError("ORDERS_API_TOKEN is not set")
        return cls(
            api_token=token,
            max_orders=int(os.environ.get("MAX_ORDERS", cls.max_orders)),
            log_level=os.environ.get("LOG_LEVEL", cls.log_level),
            faults_enabled=os.environ.get("FAULTS_ENABLED") == "true",
            fault_token=os.environ.get("FAULT_TOKEN") or None,
        )


class OrderIn(BaseModel):
    product_id: str = Field(min_length=1, max_length=64)
    quantity: int = Field(ge=1, le=100)


class Order(OrderIn):
    id: str
    created_at: datetime


def create_app(
    settings: Settings, crash: Callable[[], None] = crash_process
) -> FastAPI:
    """`crash` podmienia zakończenie procesu przy awarii crash w testach."""
    app = FastAPI(title="orders", docs_url=None, redoc_url=None, openapi_url=None)
    instrument(app)

    # Najstarsze zamówienia wypadają po przekroczeniu max_orders.
    store: OrderedDict[str, Order] = OrderedDict()
    expected_token = settings.api_token.encode()
    bearer = HTTPBearer(auto_error=False)

    def require_token(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> None:
        if credentials is None or not hmac.compare_digest(
            credentials.credentials.encode(), expected_token
        ):
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                detail="invalid or missing token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    orders_dependencies = [Depends(require_token)]
    if settings.faults_enabled and settings.fault_token:
        faults = FaultController(settings.cgroup_dir)
        app.include_router(fault_router(faults, settings.fault_token, crash))
        # Zależność trasy, nie middleware: 500 i opóźnienie widzi wtedy instrument()
        # z etykietą route, tak jak prawdziwą awarię.
        orders_dependencies.append(Depends(faults.apply))

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post(
        "/orders",
        status_code=status.HTTP_201_CREATED,
        dependencies=orders_dependencies,
    )
    async def create_order(order_in: OrderIn) -> Order:
        order = Order(
            id=uuid.uuid4().hex, created_at=datetime.now(UTC), **order_in.model_dump()
        )
        store[order.id] = order
        while len(store) > settings.max_orders:
            store.popitem(last=False)
        return order

    @app.get("/orders/{order_id}", dependencies=orders_dependencies)
    async def get_order(order_id: str) -> Order:
        order = store.get(order_id)
        if order is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="order not found")
        return order

    return app
