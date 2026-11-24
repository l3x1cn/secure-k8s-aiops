"""Ramka cech ML z reguł nagrywających service:*.

Kontrakt: docs/architektura.md, „Kontrakt metryk i logów”. Ta sama ramka służy
eksportowi danych (T20), treningowi modelu (T23) i detektorowi (T24).
"""

from datetime import UTC, datetime

import pandas as pd

from aiops.prometheus import PrometheusClient

SERVICES = ("frontend", "orders")
# Krok grupy reguł `service` w deploy/observability/recording-rules.yaml.
STEP_SECONDS = 30
# Reguła nagrywająca → kolumna ramki: nazwa bez `service:`, `:` zamienione na `_`
# (te same nazwy co w aiops/notebooks/01-prototyp.ipynb).
FEATURES = {
    "service:cpu_usage_ratio_of_limit": "cpu_usage_ratio_of_limit",
    "service:memory_working_set_ratio_of_limit": "memory_working_set_ratio_of_limit",
    "service:network_rx_bytes:rate1m": "network_rx_bytes_rate1m",
    "service:network_tx_bytes:rate1m": "network_tx_bytes_rate1m",
    "service:http_requests:rate1m": "http_requests_rate1m",
    "service:http_errors_ratio:rate1m": "http_errors_ratio_rate1m",
    "service:http_latency_p95_seconds:1m": "http_latency_p95_seconds_1m",
    "service:restarts:increase5m": "restarts_increase5m",
    "service:policy_drops:rate1m": "policy_drops_rate1m",
}
FEATURE_COLUMNS = list(FEATURES.values())
# Bez ruchu HTTP reguły http_* nie mają serii (przed pierwszym żądaniem usługi)
# albo mają NaN (0/0): brak żądań to 0 żądań/s, 0 błędów i 0 s odpowiedzi,
# a nie luka w danych.
ZERO_WITHOUT_TRAFFIC = [
    "http_requests_rate1m",
    "http_errors_ratio_rate1m",
    "http_latency_p95_seconds_1m",
]


def feature_query(rule: str) -> str:
    """Ostatnia ewaluacja reguły w oknie (t − 30 s, t].

    Reguły liczą się co 30 s, więc okno zawiera dokładnie jedną ewaluację. Jej brak daje
    NaN zamiast wartości sprzed kilku minut z 5-minutowego lookbacku zwykłego selektora.
    """
    return f'last_over_time({rule}{{namespace="shop"}}[{STEP_SECONDS}s])'


def fetch_features(
    client: PrometheusClient, start: datetime, end: datetime
) -> pd.DataFrame:
    """Cechy obu usług co STEP_SECONDS od `start` do `end` (UTC, ułamki sekund obcięte).

    Indeks: MultiIndex (service, timestamp), dla każdej usługi pełna siatka kroków.
    Kolumny: FEATURE_COLUMNS (float64). Brak ewaluacji reguły to NaN, poza
    ZERO_WITHOUT_TRAFFIC.
    """
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start and end must be timezone-aware")
    start = start.astimezone(UTC).replace(microsecond=0)
    end = end.astimezone(UTC).replace(microsecond=0)
    grid = pd.date_range(start, end, freq=f"{STEP_SECONDS}s", name="timestamp")
    found: dict[str, dict[str, pd.Series]] = {service: {} for service in SERVICES}
    for rule, column in FEATURES.items():
        for series in client.query_range(feature_query(rule), start, end, STEP_SECONDS):
            service = series.labels.get("service")
            if service in found:
                found[service][column] = series.values
    frame = pd.concat(
        {
            service: pd.DataFrame(
                by_column, index=grid, columns=FEATURE_COLUMNS, dtype="float64"
            )
            for service, by_column in found.items()
        },
        names=["service"],
    )
    frame[ZERO_WITHOUT_TRAFFIC] = frame[ZERO_WITHOUT_TRAFFIC].fillna(0.0)
    return frame


def max_gap_seconds(frame: pd.DataFrame) -> dict[str, int]:
    """Najdłuższa luka każdej usługi w sekundach: kolejne kroki bez którejś cechy."""
    gaps = {}
    for service in SERVICES:
        incomplete = frame.xs(service, level="service").isna().any(axis=1)
        longest = run = 0
        for missing in incomplete:
            run = run + 1 if missing else 0
            longest = max(longest, run)
        gaps[service] = longest * STEP_SECONDS
    return gaps
