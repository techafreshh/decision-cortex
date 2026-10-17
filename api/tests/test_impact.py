"""Offline tests for the Impact Explorer blast-radius walk (``api/impact.py``).

A fake :class:`GraphReader` dispatches on the query shape — the indexed seed
lookup versus the undirected neighbor hop — so the BFS, its depth assignment,
edge dedupe, canonical direction, node cap, and schema pin are all exercised
with no graph and no network.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from api import impact, main
from api.main import app
from ingest import ontology


class ImpactReader:
    """Canned seed row plus per-origin neighbor rows."""

    def __init__(
        self,
        *,
        seed: list[Any] | None = None,
        neighbors: dict[str, list[tuple[Any, ...]]] | None = None,
    ) -> None:
        self.seed = seed
        self.neighbors = neighbors or {}
        self.calls: list[tuple[str, Any]] = []

    def query(self, cypher: str, params: Any = None) -> list[list[Any]]:
        self.calls.append((cypher, params))
        if "startNode(r).id" in cypher:
            rows: list[list[Any]] = []
            for origin in params["ids"]:
                for relation, src, dst, neighbor in self.neighbors.get(origin, []):
                    node_id, labels, props = neighbor
                    rows.append([origin, relation, {}, src, dst, node_id, labels, props])
            return rows
        if "MATCH (n:__Entity__ {id: $id})" in cypher:
            return [] if self.seed is None else [self.seed]
        raise AssertionError(f"unexpected cypher: {cypher}")


def decision(node_id: str, title: str) -> tuple[str, list[str], dict[str, Any]]:
    return node_id, ["Decision"], {"id": node_id, "title": title}


def person(node_id: str, handle: str) -> tuple[str, list[str], dict[str, Any]]:
    return node_id, ["Person"], {"id": node_id, "handle": handle}


def test_missing_seed_returns_none() -> None:
    assert impact.build_impact(ImpactReader(seed=None), "rfc:999") is None


def test_bfs_assigns_min_depth_and_dedupes_edges() -> None:
    reader = ImpactReader(
        seed=["Decision", {"id": "rfc:1", "title": "Seed"}],
        neighbors={
            "rfc:1": [
                ("AREA", "rfc:1", "area:async", ("area:async", ["Area"], {"name": "async"})),
                (
                    "PROPOSED_BY",
                    "rfc:1",
                    "person:alice",
                    ("person:alice", ["Person"], {"handle": "alice"}),
                ),
            ],
            "area:async": [
                ("AREA", "rfc:2", "area:async", decision("rfc:2", "Second")),
            ],
            "person:alice": [
                ("OBJECTED", "person:alice", "rfc:1", decision("rfc:1", "Seed")),
            ],
        },
    )

    result = impact.build_impact(reader, "rfc:1")

    assert result is not None
    assert result["seed"] == "rfc:1"
    depths = {node["id"]: node["depth"] for node in result["nodes"]}
    assert depths == {"rfc:1": 0, "area:async": 1, "person:alice": 1, "rfc:2": 2}
    names = {node["id"]: node["name"] for node in result["nodes"]}
    assert names["area:async"] == "async"
    assert names["person:alice"] == "alice"
    # The OBJECTED edge back to the already-visited seed is recorded once.
    edge_keys = [(edge["src"], edge["dst"], edge["type"]) for edge in result["edges"]]
    assert edge_keys.count(("person:alice", "rfc:1", "OBJECTED")) == 1
    assert ("rfc:1", "area:async", "AREA") in edge_keys
    assert result["evidence_types"] == ["AREA", "OBJECTED", "PROPOSED_BY"]
    assert result["truncated"] is False


def test_depth_limits_the_walk() -> None:
    reader = ImpactReader(
        seed=["Decision", {"id": "rfc:1", "title": "Seed"}],
        neighbors={
            "rfc:1": [("AREA", "rfc:1", "area:a", ("area:a", ["Area"], {"name": "a"}))],
            "area:a": [("AREA", "rfc:2", "area:a", decision("rfc:2", "Two"))],
        },
    )

    result = impact.build_impact(reader, "rfc:1", depth=1)

    assert result is not None
    assert {node["id"] for node in result["nodes"]} == {"rfc:1", "area:a"}


def test_node_cap_truncates_and_drops_dangling_edges(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(impact, "IMPACT_NODE_CAP", 2)
    reader = ImpactReader(
        seed=["Decision", {"id": "rfc:1", "title": "Seed"}],
        neighbors={
            "rfc:1": [
                ("PROPOSED_BY", "rfc:1", "person:a", person("person:a", "a")),
                ("PROPOSED_BY", "rfc:1", "person:b", person("person:b", "b")),
            ]
        },
    )

    result = impact.build_impact(reader, "rfc:1")

    assert result is not None
    assert result["truncated"] is True
    assert len(result["nodes"]) == 2
    # The edge to the cap-skipped person is dropped, not left dangling.
    assert all(
        edge["src"] in {"rfc:1", "person:a"} and edge["dst"] in {"rfc:1", "person:a"}
        for edge in result["edges"]
    )


def test_endpoint_returns_the_impact_subgraph(monkeypatch: pytest.MonkeyPatch) -> None:
    reader = ImpactReader(
        seed=["Decision", {"id": "rfc:1", "title": "Seed"}],
        neighbors={
            "rfc:1": [
                ("AREA", "rfc:1", "area:a", ("area:a", ["Area"], {"name": "a"})),
            ]
        },
    )
    monkeypatch.setattr(main, "connect_from_env", lambda: reader)

    with TestClient(app) as client:
        response = client.get("/graph/impact/rfc:1")

    assert response.status_code == 200
    assert response.json()["seed"] == "rfc:1"
    assert {node["id"] for node in response.json()["nodes"]} == {"rfc:1", "area:a"}


def test_endpoint_returns_404_for_an_unknown_seed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "connect_from_env", lambda: ImpactReader(seed=None))

    with TestClient(app) as client:
        response = client.get("/graph/impact/rfc:999")

    assert response.status_code == 404
    assert "rfc:999" in response.json()["detail"]


def test_relations_match_the_schema() -> None:
    declared = {relation.label for relation in ontology.SCHEMA.relations}

    assert set(impact.IMPACT_RELATIONS) <= declared
    assert set(impact.IMPACT_RELATIONS) == {
        "ABOUT",
        "AREA",
        "RELATES",
        "SUPERSEDES",
        "ASSOCIATED_TEAM",
        "PROPOSED_BY",
        "OBJECTED",
        "SUPPORTED",
        "MODERATED",
    }
    assert {"EVIDENCED_BY", "HAS_VERSION", "MEMBER_OF"}.isdisjoint(impact.IMPACT_RELATIONS)
