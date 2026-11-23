"""Eksport cech ML z Prometheusa do pliku Parquet (T20).

Opcje: `uv run python -m aiops.export --help`; przykład w README („Dane i cechy”).
Prometheus z hosta: `make prometheus` (port-forward na localhost:9090) w drugim
terminalu. Ramkę opisuje aiops.features; katalog aiops/data/ jest poza git.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

import httpx

from aiops.features import fetch_features, max_gap_seconds
from aiops.prometheus import PrometheusClient, PrometheusError

DEFAULT_PROMETHEUS_URL = "http://localhost:9090"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m aiops.export",
        description="Eksport cech ML (reguły service:*) z Prometheusa do Parquet.",
    )
    parser.add_argument(
        "--from",
        dest="start",
        type=_aware_datetime,
        required=True,
        metavar="ISO",
        help="początek, ISO 8601 ze strefą, np. 2026-11-23T08:00:00Z",
    )
    parser.add_argument(
        "--to",
        dest="end",
        type=_aware_datetime,
        required=True,
        metavar="ISO",
        help="koniec, ISO 8601 ze strefą",
    )
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="plik .parquet, np. aiops/data/baseline.parquet",
    )
    parser.add_argument(
        "--prometheus-url",
        default=DEFAULT_PROMETHEUS_URL,
        help="adres Prometheusa (domyślnie port-forward z make prometheus)",
    )
    return parser


def main(
    argv: Sequence[str] | None = None, transport: httpx.BaseTransport | None = None
) -> int:
    """`transport` podmienia połączenia HTTP w testach."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.end <= args.start:
        parser.error("--to must be later than --from")

    try:
        with PrometheusClient(args.prometheus_url, transport=transport) as client:
            frame = fetch_features(client, args.start, args.end)
    except PrometheusError as exc:
        print(exc, file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(args.out)
    timestamps = frame.index.get_level_values("timestamp")
    summary = {
        "out": str(args.out),
        "from": timestamps.min().isoformat(),
        "to": timestamps.max().isoformat(),
        "rows": {
            service: int(count)
            for service, count in frame.groupby(level="service").size().items()
        },
        "features": len(frame.columns),
        "max_gap_seconds": max_gap_seconds(frame),
    }
    print(json.dumps(summary))
    return 0


def _aware_datetime(value: str) -> datetime:
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"expected ISO 8601 time, got {value!r}"
        ) from None
    if moment.tzinfo is None:
        raise argparse.ArgumentTypeError(
            f"expected time with timezone (e.g. Z), got {value!r}"
        )
    return moment


if __name__ == "__main__":
    sys.exit(main())
