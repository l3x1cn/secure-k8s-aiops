"""Kontrakt metryk i logów z docs/architektura.md, wspólny dla wszystkich usług."""

import json
import logging
import sys
import time
from datetime import UTC, datetime
from typing import IO

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

__all__ = ["JsonFormatter", "instrument", "setup_logging"]

# Ścieżki techniczne (sondy, scrape Prometheusa) nie trafiają do metryk ani logów żądań:
# stały ruch sond zaniżałby udział błędów i zaszumiał cechy ML.
_UNOBSERVED_ROUTES = frozenset({"/healthz", "/metrics"})
# Żądania, które nie pasują do żadnej trasy; jedna etykieta zamiast surowych ścieżek.
_UNMATCHED_ROUTE = "unmatched"
# Granica 0.3 s pokrywa się z progiem alertu HighLatency.
_DURATION_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0, 2.0, 5.0)

HTTP_REQUESTS = Counter(
    "http_requests",
    "Obsłużone żądania HTTP",
    ["method", "route", "status"],
)
HTTP_REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "Czas obsługi żądania HTTP",
    ["method", "route"],
    buckets=_DURATION_BUCKETS,
)

_CONTRACT_LEVELS = {"CRITICAL": "ERROR"}

logger = logging.getLogger("observability.http")


class JsonFormatter(logging.Formatter):
    """Jedna linia JSON na zdarzenie z polami kontraktu; brakujące pola mają wartość null."""

    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": _CONTRACT_LEVELS.get(record.levelname, record.levelname),
            "service": self.service,
            "route": getattr(record, "route", None),
            "status": getattr(record, "status", None),
            "duration_ms": getattr(record, "duration_ms", None),
            "msg": record.getMessage(),
        }
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def setup_logging(
    service: str, level: str = "INFO", stream: IO[str] | None = None
) -> None:
    """Kieruje wszystkie logi procesu (także uvicorn) na stdout w formacie JSON."""
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
    # httpx loguje każde wywołanie na INFO; wywołania między usługami są już w logu żądania.
    logging.getLogger("httpx").setLevel(logging.WARNING)


def instrument(app: FastAPI) -> None:
    """Dodaje metryki i logi każdego żądania oraz endpoint /metrics."""

    @app.middleware("http")
    async def observe(request: Request, call_next):
        start = time.perf_counter()
        exc_info = None
        try:
            response = await call_next(request)
        # Każdy nieobsłużony wyjątek ma zostać policzony i zalogowany jako 500.
        except Exception as exc:  # noqa: BLE001
            exc_info = exc
            response = JSONResponse(
                {"detail": "Internal Server Error"}, status_code=500
            )
        duration = time.perf_counter() - start

        matched = request.scope.get("route")
        route = getattr(matched, "path", _UNMATCHED_ROUTE)
        if route in _UNOBSERVED_ROUTES:
            return response

        status = response.status_code
        HTTP_REQUESTS.labels(request.method, route, str(status)).inc()
        HTTP_REQUEST_DURATION.labels(request.method, route).observe(duration)
        level = (
            logging.ERROR
            if status >= 500
            else logging.WARNING
            if status >= 400
            else logging.INFO
        )
        logger.log(
            level,
            "%s %s",
            request.method,
            request.url.path,
            exc_info=exc_info,
            extra={
                "route": route,
                "status": status,
                "duration_ms": round(duration * 1000, 2),
            },
        )
        return response

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
