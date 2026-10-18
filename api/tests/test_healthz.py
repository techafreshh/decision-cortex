from collections.abc import Mapping
from typing import Any

from fastapi.testclient import TestClient

from api import seed
from api.main import app


class _Reader:
    """A ``GraphReader`` double keyed by query, or one that always raises."""

    def __init__(
        self,
        rows: Mapping[str, list[list[Any]]] | None = None,
        *,
        fail: bool = False,
    ) -> None:
        self._rows = rows or {}
        self._fail = fail

    def query(
        self, cypher: str, params: Mapping[str, Any] | None = None
    ) -> list[list[Any]]:
        if self._fail:
            raise ConnectionError("no database reachable")
        return self._rows.get(cypher, [])


def _rows(decisions: int, edges: int) -> dict[str, list[list[Any]]]:
    return {
        seed._DECISION_COUNT_QUERY: [[decisions]],
        seed._EDGE_COUNT_QUERY: [[edges]],
    }


def test_healthz_is_ok_without_a_database(monkeypatch: Any) -> None:
    monkeypatch.setattr("api.main.connect_from_env", lambda: _Reader(fail=True))
    with TestClient(app) as client:
        response = client.get("/healthz")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body == {"status": "ok", "seeded": False}


def test_healthz_reports_a_seeded_graph(monkeypatch: Any) -> None:
    monkeypatch.setattr("api.main.connect_from_env", lambda: _Reader(_rows(3, 12)))
    with TestClient(app) as client:
        response = client.get("/healthz")

        assert response.status_code == 200
        assert response.json() == {"status": "ok", "seeded": True}


def test_healthz_reports_a_partial_graph_as_unseeded(monkeypatch: Any) -> None:
    monkeypatch.setattr("api.main.connect_from_env", lambda: _Reader(_rows(3, 0)))
    with TestClient(app) as client:
        response = client.get("/healthz")

        assert response.status_code == 200
        assert response.json() == {"status": "ok", "seeded": False}
