"""Nagrywa odpowiedzi Prometheusa dla testów aiops: fixtures/query_range.json.

Na klastrze z make up, gdy Locust działa od co najmniej 15 min, a w ostatnich 10 min
nie było awarii (S1–S7), skoku ruchu ani testów z tests/:

    mise exec -- uv run --locked python aiops/tests/fixtures/record.py

Nagrywa ostatnie pełne 10 min (21 kroków) zapytania aiops.features.feature_query każdej
reguły. Zapytania idą przez proxy API serwera (kubectl get --raw), jak w
tests/observability/test_metrics.py. Zmiana feature_query wymaga nowego nagrania.
"""

import json
import math
import os
import subprocess
import time
import urllib.parse
from pathlib import Path

from aiops.features import FEATURES, SERVICES, STEP_SECONDS, feature_query

KUBE_CONTEXT = os.environ.get("KUBE_CONTEXT", "kind-secure-k8s-aiops")
PROMETHEUS_PROXY = (
    "/api/v1/namespaces/monitoring/services/prometheus-operated:9090/proxy"
)
WINDOW_SECONDS = 600
OUT = Path(__file__).with_name("query_range.json")


def query_range(query: str, start: int, end: int) -> dict:
    params = {"query": query, "start": start, "end": end, "step": STEP_SECONDS}
    path = f"{PROMETHEUS_PROXY}/api/v1/query_range?" + urllib.parse.urlencode(params)
    result = subprocess.run(
        ["kubectl", "--context", KUBE_CONTEXT, "get", "--raw", path],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return json.loads(result.stdout)


def main() -> None:
    # Krok sprzed minuty: ewaluacja reguł z końca okna jest już zapisana.
    end = int(time.time()) // STEP_SECONDS * STEP_SECONDS - 60
    start = end - WINDOW_SECONDS
    steps = WINDOW_SECONDS // STEP_SECONDS + 1
    rules = {}
    for rule in FEATURES:
        query = feature_query(rule)
        response = query_range(query, start, end)
        result = response["data"]["result"]
        services = sorted(series["metric"]["service"] for series in result)
        if services != sorted(SERVICES):
            raise SystemExit(f"{rule}: series {services}, expected {sorted(SERVICES)}")
        for series in result:
            values = [float(value) for _, value in series["values"]]
            if len(values) != steps or not all(map(math.isfinite, values)):
                raise SystemExit(
                    f"{rule} {series['metric']['service']}: {len(values)} samples, "
                    f"expected {steps} finite"
                )
        rules[rule] = {"query": query, "response": response}
    recording = {"start": start, "end": end, "step": STEP_SECONDS, "rules": rules}
    OUT.write_text(json.dumps(recording, indent=1) + "\n")
    print(f"{OUT}: {start}–{end}")


if __name__ == "__main__":
    main()
