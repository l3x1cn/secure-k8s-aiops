import httpx
import pandas as pd
import pytest
from aiops.features import fetch_features, max_gap_seconds
from aiops.prometheus import PrometheusClient

# Kontrakt z docs/architektura.md, nie z aiops.features: test łapie regułę albo kolumnę
# usuniętą lub przemianowaną.
CONTRACT = {
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
HTTP_COLUMNS = [
    "http_requests_rate1m",
    "http_errors_ratio_rate1m",
    "http_latency_p95_seconds_1m",
]


def fetch(prometheus, window) -> pd.DataFrame:
    transport = httpx.MockTransport(prometheus)
    with PrometheusClient("http://prometheus:9090", transport=transport) as client:
        return fetch_features(client, *window)


def recorded(prometheus, rule: str, service: str) -> list[float]:
    return [float(value) for _, value in prometheus.series(rule, service)["values"]]


def test_frame_has_contract_features_for_both_services_on_30s_grid(prometheus, window):
    frame = fetch(prometheus, window)

    assert frame.index.names == ["service", "timestamp"]
    assert list(frame.columns) == list(CONTRACT.values())
    grid = list(pd.date_range(*window, freq="30s"))
    for service in ("frontend", "orders"):
        per_service = frame.xs(service, level="service")
        assert list(per_service.index) == grid
        for rule, column in CONTRACT.items():
            assert per_service[column].tolist() == recorded(prometheus, rule, service)


def test_http_features_without_traffic_are_zero(prometheus, window):
    # orders przed pierwszym żądaniem: reguły http_* nie mają serii.
    for rule in (
        "service:http_requests:rate1m",
        "service:http_errors_ratio:rate1m",
        "service:http_latency_p95_seconds:1m",
    ):
        prometheus.drop_series(rule, "orders")
    # frontend bez żądań w oknie rate: udział błędów i p95 to 0/0, czyli NaN.
    for rule in (
        "service:http_errors_ratio:rate1m",
        "service:http_latency_p95_seconds:1m",
    ):
        series = prometheus.series(rule, "frontend")
        series["values"] = [[t, "NaN"] for t, _ in series["values"]]

    frame = fetch(prometheus, window)

    orders = frame.xs("orders", level="service")
    frontend = frame.xs("frontend", level="service")
    assert (orders[HTTP_COLUMNS] == 0).all().all()
    assert (frontend[HTTP_COLUMNS[1:]] == 0).all().all()
    assert frontend["http_requests_rate1m"].tolist() == recorded(
        prometheus, "service:http_requests:rate1m", "frontend"
    )
    assert max_gap_seconds(frame) == {"frontend": 0, "orders": 0}


@pytest.mark.parametrize(
    ("missing", "gap"),
    [([5, 6, 7], 90), ([0, 1], 60), ([-1], 30)],
    ids=["middle", "start", "end"],
)
def test_missing_evaluations_are_gaps(prometheus, window, missing, gap):
    series = prometheus.series("service:cpu_usage_ratio_of_limit", "orders")
    samples = series["values"]
    dropped = {k % len(samples) for k in missing}
    series["values"] = [s for k, s in enumerate(samples) if k not in dropped]

    frame = fetch(prometheus, window)

    cpu = frame.xs("orders", level="service")["cpu_usage_ratio_of_limit"]
    expected = pd.to_datetime(
        [samples[k][0] for k in sorted(dropped)], unit="s", utc=True
    )
    assert list(cpu[cpu.isna()].index) == list(expected)
    assert max_gap_seconds(frame) == {"frontend": 0, "orders": gap}
