"""CLI fault-runner: awarie w orders (S1–S5) i skok ruchu na frontend (S6).

Kontener w loadgen czeka bezczynnie (`fault-runner idle`), a polecenia
uruchamia `kubectl exec`. Scenariusze opisuje docs/architektura.md.
"""

import argparse
import asyncio
import itertools
import json
import os
import signal
import sys
import time
from collections import Counter
from collections.abc import Awaitable, Sequence
from pathlib import Path

import httpx

FAULTS = ("cpu", "memory", "errors", "latency", "crash")
DEFAULT_ORDERS_URL = "http://orders.shop.svc:8080"
DEFAULT_FRONTEND_URL = "http://frontend.shop.svc:8080"
DEFAULT_TOKEN_FILE = "/var/run/secrets/fault-token/token"
REQUEST_TIMEOUT_SECONDS = 5.0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fault-runner", description="Kontrolowane awarie i skoki ruchu."
    )
    parser.add_argument(
        "--orders-url", default=os.environ.get("ORDERS_URL", DEFAULT_ORDERS_URL)
    )
    parser.add_argument(
        "--frontend-url", default=os.environ.get("FRONTEND_URL", DEFAULT_FRONTEND_URL)
    )
    parser.add_argument(
        "--token-file",
        type=Path,
        default=Path(os.environ.get("FAULT_TOKEN_FILE", DEFAULT_TOKEN_FILE)),
        help="plik z tokenem X-Fault-Token (Secret fault-token)",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    fault = commands.add_parser("fault", help="uruchom awarię w orders")
    fault.add_argument("name", choices=FAULTS)
    fault.add_argument("--seconds", type=int, help="czas awarii (domyślnie z orders)")
    fault.add_argument(
        "--param",
        action="append",
        default=[],
        type=_key_value,
        metavar="K=V",
        help="parametr awarii, np. ratio=0.5, ms=500, target_ratio=0.9",
    )

    commands.add_parser("stop", help="zakończ bieżącą awarię")

    spike = commands.add_parser("spike", help="skok ruchu na frontend")
    spike.add_argument("--users", type=_positive_int, required=True)
    spike.add_argument("--seconds", type=_positive_int, required=True)
    spike.add_argument(
        "--wait", type=float, default=1.0, help="przerwa użytkownika między cyklami (s)"
    )

    commands.add_parser("idle", help="czekaj na SIGTERM (proces główny kontenera)")

    return parser


def main(
    argv: Sequence[str] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> int:
    """`transport` podmienia połączenia HTTP w testach."""
    args = build_parser().parse_args(argv)

    match args.command:
        case "idle":
            return idle()
        case "spike":
            summary = asyncio.run(
                spike(args.frontend_url, args.users, args.seconds, args.wait, transport)
            )
            print(json.dumps(summary))
            return 0
        case "fault":
            params = dict(args.param)
            if args.seconds is not None:
                params["seconds"] = str(args.seconds)
            path = f"/faults/{args.name}"
        case _:
            params = {}
            path = "/faults/stop"

    try:
        token = args.token_file.read_text().strip()
    except OSError as exc:
        print(f"cannot read fault token: {exc}", file=sys.stderr)
        return 1

    return asyncio.run(_post_fault(args.orders_url, path, params, token, transport))


async def _post_fault(
    orders_url: str,
    path: str,
    params: dict[str, str],
    token: str,
    transport: httpx.AsyncBaseTransport | None,
) -> int:
    async with httpx.AsyncClient(
        base_url=orders_url, timeout=REQUEST_TIMEOUT_SECONDS, transport=transport
    ) as client:
        try:
            response = await client.post(
                path, params=params, headers={"X-Fault-Token": token}
            )
        except httpx.HTTPError as exc:
            print(f"orders unreachable: {exc!r}", file=sys.stderr)
            return 1

    if response.is_error:
        print(
            f"orders responded {response.status_code}: {response.text}", file=sys.stderr
        )
        return 1

    print(response.text)

    return 0


async def spike(
    frontend_url: str,
    users: int,
    seconds: int,
    wait: float,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, int]:
    """`users` równoległych użytkowników: lista produktów, potem zamówienie.

    Zwraca liczbę odpowiedzi według statusu; `error` to brak odpowiedzi.
    """
    statuses: Counter[str] = Counter()
    deadline = time.monotonic() + seconds

    async def send(call: Awaitable[httpx.Response]) -> httpx.Response | None:
        try:
            response = await call
        except httpx.HTTPError:
            statuses["error"] += 1
            return None
        statuses[str(response.status_code)] += 1
        return response

    async def user(client: httpx.AsyncClient, number: int) -> None:
        # Kolejni użytkownicy zaczynają od różnych produktów.
        cycle = itertools.count(number)
        while time.monotonic() < deadline:
            listing = await send(client.get("/"))
            if listing is not None and listing.is_success:
                ids = [product["id"] for product in listing.json()]
                if ids:
                    order = {"product_id": ids[next(cycle) % len(ids)], "quantity": 1}
                    await send(client.post("/order", json=order))
            await asyncio.sleep(min(wait, max(0.0, deadline - time.monotonic())))

    limits = httpx.Limits(max_connections=users)
    async with httpx.AsyncClient(
        base_url=frontend_url,
        timeout=REQUEST_TIMEOUT_SECONDS,
        limits=limits,
        transport=transport,
    ) as client:
        await asyncio.gather(*(user(client, n) for n in range(users)))

    return dict(sorted(statuses.items()))


def idle() -> int:
    # Proces o PID 1 ignoruje SIGTERM bez własnej obsługi, a kubelet czekałby wtedy
    # cały terminationGracePeriodSeconds.
    stop_signals = {signal.SIGTERM, signal.SIGINT}
    signal.pthread_sigmask(signal.SIG_BLOCK, stop_signals)
    signal.sigwait(stop_signals)

    return 0


def _key_value(value: str) -> tuple[str, str]:
    key, sep, val = value.partition("=")
    if not sep or not key:
        raise argparse.ArgumentTypeError(f"expected K=V, got {value!r}")
    return key, val


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number
