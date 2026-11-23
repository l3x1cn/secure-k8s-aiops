"""Klient zapytań zakresowych HTTP API Prometheusa (`GET /api/v1/query_range`).

Z hosta: http://localhost:9090 (`make prometheus`); w klastrze (T24):
http://prometheus-operated.monitoring.svc:9090.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Self

import httpx
import pandas as pd

REQUEST_TIMEOUT_SECONDS = 30.0


class PrometheusError(Exception):
    """Prometheus nieosiągalny albo odpowiedź API inna niż sukces."""


@dataclass(frozen=True)
class RangeSeries:
    """Seria wyniku zapytania: etykiety i próbki.

    `values`: float64 z indeksem czasu UTC; wartość "NaN" z API (np. 0/0) to NaN.
    """

    labels: dict[str, str]
    values: pd.Series


class PrometheusClient:
    def __init__(self, url: str, transport: httpx.BaseTransport | None = None) -> None:
        """`transport` podmienia połączenia HTTP w testach."""
        self._client = httpx.Client(
            base_url=url, timeout=REQUEST_TIMEOUT_SECONDS, transport=transport
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def query_range(
        self, query: str, start: datetime, end: datetime, step_seconds: int
    ) -> list[RangeSeries]:
        params = {
            "query": query,
            "start": start.timestamp(),
            "end": end.timestamp(),
            "step": step_seconds,
        }
        try:
            response = self._client.get("/api/v1/query_range", params=params)
        except httpx.HTTPError as exc:
            raise PrometheusError(f"prometheus unreachable: {exc!r}") from exc
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.is_error or body.get("status") != "success":
            detail = (
                f"{body['errorType']}: {body['error']}"
                if "error" in body
                else response.text
            )
            raise PrometheusError(
                f"prometheus responded {response.status_code}: {detail}"
            )
        return [_range_series(item) for item in body["data"]["result"]]


def _range_series(item: dict) -> RangeSeries:
    index = pd.to_datetime([t for t, _ in item["values"]], unit="s", utc=True)
    values = pd.Series(
        [float(v) for _, v in item["values"]], index=index, dtype="float64"
    )
    return RangeSeries(labels=item["metric"], values=values)
