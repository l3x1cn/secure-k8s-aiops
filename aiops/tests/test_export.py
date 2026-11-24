import json

import httpx
import pandas as pd
import pytest
from aiops.export import main
from aiops.features import fetch_features
from aiops.prometheus import PrometheusClient

URL = "http://prometheus:9090"


def run(handler, *args: str) -> int:
    return main(
        ["--prometheus-url", URL, *args], transport=httpx.MockTransport(handler)
    )


def test_export_writes_frame_to_parquet_and_prints_summary(
    prometheus, window, tmp_path, capsys
):
    start, end = window
    out = tmp_path / "data" / "baseline.parquet"

    code = run(
        prometheus,
        "--from",
        start.isoformat(),
        "--to",
        end.isoformat(),
        "--out",
        str(out),
    )

    assert code == 0
    with PrometheusClient(URL, transport=httpx.MockTransport(prometheus)) as client:
        expected = fetch_features(client, start, end)
    pd.testing.assert_frame_equal(pd.read_parquet(out), expected)
    steps = len(pd.date_range(start, end, freq="30s"))
    assert json.loads(capsys.readouterr().out) == {
        "out": str(out),
        "from": start.isoformat(),
        "to": end.isoformat(),
        "rows": {"frontend": steps, "orders": steps},
        "features": 9,
        "max_gap_seconds": {"frontend": 0, "orders": 0},
    }


def unexpected(request: httpx.Request) -> httpx.Response:
    pytest.fail(f"unexpected request {request.url}")


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2026-11-23T08:00:00", "2026-11-23T10:00:00Z"),
        ("2026-11-23T10:00:00Z", "2026-11-23T10:00:00Z"),
        ("wczoraj", "2026-11-23T10:00:00Z"),
    ],
    ids=["without-timezone", "empty-range", "not-iso"],
)
def test_invalid_range_is_rejected_without_request(tmp_path, start, end):
    out = tmp_path / "baseline.parquet"

    with pytest.raises(SystemExit):
        run(unexpected, "--from", start, "--to", end, "--out", str(out))

    assert not out.exists()


def test_prometheus_error_is_reported_without_file(window, tmp_path, capsys):
    def reject(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"status": "error", "errorType": "bad_data", "error": "parse error"},
        )

    start, end = window
    out = tmp_path / "baseline.parquet"

    code = run(
        reject, "--from", start.isoformat(), "--to", end.isoformat(), "--out", str(out)
    )

    assert code == 1
    err = capsys.readouterr().err
    assert "400" in err and "bad_data" in err
    assert not out.exists()


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (httpx.Response(502, text="<html>Bad Gateway</html>"), ["502", "Bad Gateway"]),
        (httpx.Response(401, json={"error": "unauthorized"}), ["401", "unauthorized"]),
        (httpx.Response(200, json=["not", "an", "object"]), ["200", '["not"']),
    ],
    ids=["body-not-json", "error-without-error-type", "json-not-object"],
)
def test_unusual_error_response_is_reported_without_file(
    window, tmp_path, capsys, response, expected
):
    start, end = window
    out = tmp_path / "baseline.parquet"

    code = run(
        lambda request: response,
        "--from",
        start.isoformat(),
        "--to",
        end.isoformat(),
        "--out",
        str(out),
    )

    assert code == 1
    err = capsys.readouterr().err
    assert all(part in err for part in expected)
    assert not out.exists()


def test_unreachable_prometheus_exits_with_error(window, tmp_path, capsys):
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused", request=request)

    start, end = window
    out = tmp_path / "baseline.parquet"

    code = run(
        refuse, "--from", start.isoformat(), "--to", end.isoformat(), "--out", str(out)
    )

    assert code == 1
    assert "unreachable" in capsys.readouterr().err
    assert not out.exists()
