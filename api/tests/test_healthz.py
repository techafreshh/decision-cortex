from collections.abc import Mapping
from typing import Any

from fastapi.testclient import TestClient

from api.main import app


class _Reader:
    """A ``GraphReader`` double: canned rows, or a query that raises."""

    def __init__(self, rows: list[list[Any]] | None = None) -> None:
        self._rows = rows

    def query(
        self, cypher: str, params: Mapping[str, Any] | None = None
    ) -> list[list[Any]]:
        if self._rows is None:
            raise ConnectionError("no database reachable")
        return self._rows


def test_healthz_is_ok_without_a_database(monkeypatch: Any) -> None:
    monkeypatch.setattr("api.main.connect_from_env", lambda: _Reader())
    with TestClient(app) as client:
        response = client.get("/healthz")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body == {"status": "ok", "seeded": False}


def test_healthz_reports_a_seeded_graph(monkeypatch: Any) -> None:
    monkeypatch.setattr("api.main.connect_from_env", lambda: _Reader([[3]]))
    with TestClient(app) as client:
        response = client.get("/healthz")

        assert response.status_code == 200
        assert response.json() == {"status": "ok", "seeded": True}
