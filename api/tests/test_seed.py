from collections.abc import Mapping
from typing import Any

from api import seed
from api.retrieval import FalkorDBConnection


class _Reader:
    """A ``GraphReader`` double: canned rows, or a query that raises."""

    def __init__(self, rows: list[list[Any]] | None = None) -> None:
        self._rows = rows
        self.calls: list[str] = []

    def query(
        self, cypher: str, params: Mapping[str, Any] | None = None
    ) -> list[list[Any]]:
        self.calls.append(cypher)
        if self._rows is None:
            raise ConnectionError("no database reachable")
        return self._rows


def test_graph_is_seeded_true_when_a_decision_exists() -> None:
    assert seed.graph_is_seeded(_Reader([[3]])) is True


def test_graph_is_seeded_false_when_empty() -> None:
    assert seed.graph_is_seeded(_Reader([[0]])) is False


def test_graph_is_seeded_false_when_the_query_raises() -> None:
    assert seed.graph_is_seeded(_Reader()) is False


def test_seed_if_empty_skips_a_seeded_graph() -> None:
    loaded: list[dict[str, Any]] = []
    result = seed.seed_if_empty(
        reader=_Reader([[5]]),
        snapshot_dir="snapshot",
        host="db",
        port=6379,
        graph_name="g",
        load=lambda **kwargs: loaded.append(kwargs),
    )

    assert result is False
    assert loaded == []


def test_seed_if_empty_loads_an_empty_graph_once() -> None:
    loaded: list[dict[str, Any]] = []
    result = seed.seed_if_empty(
        reader=_Reader([[0]]),
        snapshot_dir="snap",
        host="db",
        port=6380,
        graph_name="g",
        load=lambda **kwargs: loaded.append(kwargs),
    )

    assert result is True
    assert loaded == [
        {"snapshot_dir": "snap", "host": "db", "port": 6380, "graph_name": "g"}
    ]


def test_main_honors_the_environment(monkeypatch: Any, capsys: Any) -> None:
    monkeypatch.setenv("SNAPSHOT_DIR", "snapshots")
    monkeypatch.setattr(
        seed,
        "connection_from_env",
        lambda: FalkorDBConnection(host="db", port=6380, graph_name="g"),
    )
    monkeypatch.setattr(seed, "connect_from_env", lambda: _Reader([[0]]))
    loaded: list[dict[str, Any]] = []
    monkeypatch.setattr(seed, "_load_snapshot", lambda **kwargs: loaded.append(kwargs))

    assert seed.main() == 0
    assert loaded == [
        {"snapshot_dir": "snapshots", "host": "db", "port": 6380, "graph_name": "g"}
    ]
    assert "seeded snapshot" in capsys.readouterr().out
