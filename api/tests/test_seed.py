from collections.abc import Mapping
from typing import Any

from api import seed
from api.retrieval import FalkorDBConnection


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
        self.calls: list[str] = []

    def query(
        self, cypher: str, params: Mapping[str, Any] | None = None
    ) -> list[list[Any]]:
        self.calls.append(cypher)
        if self._fail:
            raise ConnectionError("no database reachable")
        return self._rows.get(cypher, [])


def _rows(decisions: int, edges: int) -> dict[str, list[list[Any]]]:
    return {
        seed._DECISION_COUNT_QUERY: [[decisions]],
        seed._EDGE_COUNT_QUERY: [[edges]],
    }


def test_graph_is_seeded_true_when_decisions_and_edges_exist() -> None:
    assert seed.graph_is_seeded(_Reader(_rows(3, 12))) is True


def test_graph_is_seeded_false_when_empty() -> None:
    assert seed.graph_is_seeded(_Reader(_rows(0, 0))) is False


def test_graph_is_seeded_false_when_decisions_have_no_edges() -> None:
    # A load killed after ``upsert_nodes`` but before ``upsert_relationships``
    # leaves Decisions with no edges; that partial graph is not seeded.
    assert seed.graph_is_seeded(_Reader(_rows(3, 0))) is False


def test_graph_is_seeded_false_when_the_query_raises() -> None:
    assert seed.graph_is_seeded(_Reader(fail=True)) is False


def test_seed_if_empty_skips_a_seeded_graph(monkeypatch: Any) -> None:
    loaded: list[dict[str, Any]] = []
    monkeypatch.setattr(seed, "_load_snapshot", lambda **kwargs: loaded.append(kwargs))

    result = seed.seed_if_empty(
        reader=_Reader(_rows(5, 20)),
        snapshot_dir="snapshot",
        host="db",
        port=6379,
        graph_name="g",
    )

    assert result is False
    assert loaded == []


def test_seed_if_empty_reloads_a_partial_graph(monkeypatch: Any) -> None:
    # The regression: a node-only graph re-runs the idempotent loader.
    loaded: list[dict[str, Any]] = []
    monkeypatch.setattr(seed, "_load_snapshot", lambda **kwargs: loaded.append(kwargs))

    result = seed.seed_if_empty(
        reader=_Reader(_rows(5, 0)),
        snapshot_dir="snapshot",
        host="db",
        port=6379,
        graph_name="g",
    )

    assert result is True
    assert loaded == [
        {"snapshot_dir": "snapshot", "host": "db", "port": 6379, "graph_name": "g"}
    ]


def test_seed_if_empty_loads_an_empty_graph_once(monkeypatch: Any) -> None:
    loaded: list[dict[str, Any]] = []
    monkeypatch.setattr(seed, "_load_snapshot", lambda **kwargs: loaded.append(kwargs))

    result = seed.seed_if_empty(
        reader=_Reader(_rows(0, 0)),
        snapshot_dir="snap",
        host="db",
        port=6380,
        graph_name="g",
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
    monkeypatch.setattr(seed, "connect_from_env", lambda: _Reader(_rows(0, 0)))
    loaded: list[dict[str, Any]] = []
    monkeypatch.setattr(seed, "_load_snapshot", lambda **kwargs: loaded.append(kwargs))

    assert seed.main() == 0
    assert loaded == [
        {"snapshot_dir": "snapshots", "host": "db", "port": 6380, "graph_name": "g"}
    ]
    assert "seeded snapshot" in capsys.readouterr().out
