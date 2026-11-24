import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

# Odpowiedzi GET /api/v1/query_range nagrane na klastrze przez fixtures/record.py
# (ruch Locust, 10 min, krok 30 s): zapytanie aiops.features.feature_query
# każdej z 9 reguł service:*.
RECORDING = Path(__file__).parent / "fixtures" / "query_range.json"


class FakePrometheus:
    """Odtwarza nagranie: odpowiada tylko na nagrane zapytanie, okno i krok.

    Inne zapytanie dostaje 400, jak niepoprawne zapytanie w Prometheusie.
    """

    def __init__(self, recording: dict) -> None:
        self.window = (recording["start"], recording["end"], recording["step"])
        self.rules = copy.deepcopy(recording["rules"])

    def __call__(self, request: httpx.Request) -> httpx.Response:
        params = request.url.params
        asked = (float(params["start"]), float(params["end"]), float(params["step"]))
        for entry in self.rules.values():
            if params["query"] == entry["query"] and asked == self.window:
                return httpx.Response(200, json=entry["response"])
        return httpx.Response(
            400,
            json={"status": "error", "errorType": "bad_data", "error": "not recorded"},
        )

    def series(self, rule: str, service: str) -> dict:
        """Nagrana seria reguły dla usługi; test może ją zmienić przed zapytaniem."""
        result = self.rules[rule]["response"]["data"]["result"]
        return next(item for item in result if item["metric"]["service"] == service)

    def drop_series(self, rule: str, service: str) -> None:
        result = self.rules[rule]["response"]["data"]["result"]
        result.remove(self.series(rule, service))


@pytest.fixture(scope="session")
def recording() -> dict:
    return json.loads(RECORDING.read_text())


@pytest.fixture
def prometheus(recording: dict) -> FakePrometheus:
    return FakePrometheus(recording)


@pytest.fixture
def window(recording: dict) -> tuple[datetime, datetime]:
    return (
        datetime.fromtimestamp(recording["start"], UTC),
        datetime.fromtimestamp(recording["end"], UTC),
    )
