"""Offline behavior tests for the Phase-1 graph payload builder.

No FalkorDB, no network, no LLM: the pure builder is exercised against the
committed corpus and a tiny fixture, and the ontology constraint is pinned.
The IO path (:func:`ingest.graph.load_payload`) is covered by the integration
tests instead.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from ingest import graph
from ingest.embeddings import DecisionEmbeddings

REPO_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = REPO_ROOT / "snapshot"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "phase1"

FIXTURE_NODE_IDS = {
    "area:A-trait-objects",
    "commit:abc123",
    "concept:trait-objects",
    "docversion:100",
    "docversion:200",
    "message:5001",
    "message:5002",
    "person:alice",
    "person:bob",
    "person:carol",
    "rfc:100",
    "rfc:200",
    "rfc:300",
    "team:T-lang",
}

FIXTURE_EDGES = {
    ("ABOUT", "rfc:200", "concept:trait-objects"),
    ("AREA", "rfc:200", "area:A-trait-objects"),
    ("ASSOCIATED_TEAM", "rfc:100", "team:T-lang"),
    ("ASSOCIATED_TEAM", "rfc:200", "team:T-lang"),
    ("EVIDENCED_BY", "rfc:100", "docversion:100"),
    ("EVIDENCED_BY", "rfc:200", "commit:abc123"),
    ("EVIDENCED_BY", "rfc:200", "docversion:200"),
    ("EVIDENCED_BY", "rfc:200", "message:5001"),
    ("EVIDENCED_BY", "rfc:200", "message:5002"),
    ("HAS_VERSION", "rfc:100", "docversion:100"),
    ("HAS_VERSION", "rfc:200", "docversion:200"),
    ("OBJECTED", "person:bob", "rfc:200"),
    ("PROPOSED_BY", "rfc:100", "person:alice"),
    ("PROPOSED_BY", "rfc:200", "person:alice"),
    ("PROPOSED_BY", "rfc:300", "person:carol"),
    ("SUPERSEDES", "rfc:300", "rfc:200"),
}


def _decision(rfc: int, **overrides: Any) -> dict[str, Any]:
    record = {
        "rfc": rfc,
        "title": f"RFC {rfc}",
        "status": "accepted",
        "proposed_on": "2014-01-01T00:00:00Z",
        "decided_on": "2014-02-01T00:00:00Z",
        "supersedes_rfc": None,
        "madr_link": None,
        "author": "alice",
        "url": f"https://github.com/rust-lang/rfcs/pull/{rfc}",
        "labels": [],
    }
    record.update(overrides)
    return record


def _node_ids(payload: graph.Payload) -> set[str]:
    return {node.id for node in payload.nodes}


def _edges(payload: graph.Payload) -> set[tuple[str, str, str]]:
    return {(edge.type, edge.src, edge.dst) for edge in payload.edges}


def test_build_payload_fixture_shape() -> None:
    payload = graph.payload_from_snapshot(FIXTURE)

    graph.validate_payload(payload)
    assert _node_ids(payload) == FIXTURE_NODE_IDS
    assert _edges(payload) == FIXTURE_EDGES

    by_id = {node.id: node for node in payload.nodes}
    assert by_id["rfc:200"].properties["status"] == "accepted"
    assert by_id["message:5002"].properties["truncated"] is True
    assert by_id["commit:abc123"].properties["message"] == "Add RFC 200"


def test_doc_version_sha_is_content_hash() -> None:
    payload = graph.payload_from_snapshot(FIXTURE)
    by_id = {node.id: node for node in payload.nodes}

    content = "# Trait objects\n\nBoxed trait objects use dynamic dispatch.\n"
    assert by_id["docversion:200"].properties["sha"] == hashlib.sha256(
        content.encode("utf-8")
    ).hexdigest()
    assert by_id["docversion:200"].properties["content_ref"] == (
        "https://github.com/rust-lang/rfcs/pull/200"
    )

    assert "docversion:300" not in by_id


def test_supersedes_only_when_target_present() -> None:
    decisions = [_decision(300, supersedes_rfc=200)]
    payload = graph.build_payload(decisions, [], [])

    assert ("SUPERSEDES", "rfc:300", "rfc:200") not in _edges(payload)

    with_target = graph.build_payload([_decision(200), _decision(300, supersedes_rfc=200)], [], [])
    assert ("SUPERSEDES", "rfc:300", "rfc:200") in _edges(with_target)


def test_stance_and_concept_enrichment() -> None:
    payload = graph.build_payload(
        [_decision(200)],
        [],
        [],
        concepts=[{"rfc": 200, "key": "trait-objects", "name": "trait objects"}],
        stances=[
            {
                "rfc": 200,
                "handle": "bob",
                "stance": "OBJECTED",
                "evidence": "https://example.test/comment/1",
                "confidence": 0.8,
            }
        ],
    )

    graph.validate_payload(payload)
    assert _node_ids(payload) >= {"concept:trait-objects", "person:bob", "rfc:200"}
    about = [edge for edge in payload.edges if edge.type == "ABOUT"]
    assert about == [graph.Edge("rfc:200", "concept:trait-objects", "ABOUT", {})]
    stance = [edge for edge in payload.edges if edge.type == "OBJECTED"]
    assert stance == [
        graph.Edge(
            "person:bob",
            "rfc:200",
            "OBJECTED",
            {"evidence": "https://example.test/comment/1", "confidence": 0.8},
        )
    ]


def test_ids_namespaced_no_collision() -> None:
    payload = graph.build_payload([_decision(200, author="200")], [], [])

    ids = _node_ids(payload)
    assert {"person:200", "rfc:200"} <= ids
    assert graph.person_id("200") != graph.decision_id(200)


def test_validate_payload_rejects_bad_label() -> None:
    payload = graph.Payload(nodes=(graph.Node("x:1", "Bogus", {}),), edges=())

    with pytest.raises(ValueError, match="unknown entity label"):
        graph.validate_payload(payload)


def test_validate_payload_rejects_bad_pattern() -> None:
    payload = graph.Payload(
        nodes=(
            graph.Node("rfc:1", "Decision", {}),
            graph.Node("person:a", "Person", {}),
        ),
        edges=(graph.Edge("rfc:1", "person:a", "SUPERSEDES", {}),),
    )

    with pytest.raises(ValueError, match="not an allowed pattern"):
        graph.validate_payload(payload)


def test_validate_payload_rejects_missing_endpoint() -> None:
    payload = graph.Payload(
        nodes=(graph.Node("rfc:1", "Decision", {}),),
        edges=(graph.Edge("rfc:1", "person:ghost", "PROPOSED_BY", {}),),
    )

    with pytest.raises(ValueError, match="missing endpoint"):
        graph.validate_payload(payload)


def test_committed_corpus_builds_expected_counts() -> None:
    payload = graph.payload_from_snapshot(SNAPSHOT)

    graph.validate_payload(payload)
    assert len(payload.nodes) == 28_483
    assert len(payload.edges) == 31_938

    labels = {}
    for node in payload.nodes:
        labels[node.label] = labels.get(node.label, 0) + 1
    assert labels == {
        "Decision": 2_309,
        "Person": 1_272,
        "Message": 21_623,
        "Commit": 2_451,
        "DocVersion": 642,
        "Team": 20,
        "Area": 166,
    }

    types = {}
    for edge in payload.edges:
        types[edge.type] = types.get(edge.type, 0) + 1
    assert types == {
        "PROPOSED_BY": 2_309,
        "EVIDENCED_BY": 25_821,
        "HAS_VERSION": 642,
        "ASSOCIATED_TEAM": 1_554,
        "AREA": 1_609,
        "SUPERSEDES": 3,
    }


def test_validate_payload_rejects_undeclared_property() -> None:
    payload = graph.Payload(
        nodes=(graph.Node("rfc:1", "Decision", {"rfc": 1, "url": "x"}),),
        edges=(),
    )

    with pytest.raises(ValueError, match="undeclared properties"):
        graph.validate_payload(payload)


class _StubStore:
    """Minimal ``GraphStore`` stand-in for the index-creation path."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[str] = []

    async def query_raw(self, cypher: str) -> None:
        self.calls.append(cypher)
        if self.error is not None:
            raise self.error


def test_ensure_id_indexes_tolerates_already_indexed() -> None:
    store = _StubStore(RuntimeError("Attribute 'id' is already indexed"))

    asyncio.run(graph._ensure_id_indexes(store))

    assert store.calls == [
        f"CREATE INDEX FOR (n:{label}) ON (n.id)"
        for label in graph._id_index_labels()
    ]


def test_ensure_id_indexes_propagates_other_errors() -> None:
    store = _StubStore(RuntimeError("connection reset"))

    with pytest.raises(RuntimeError, match="connection reset"):
        asyncio.run(graph._ensure_id_indexes(store))


def _stub_sdk(
    monkeypatch: pytest.MonkeyPatch,
    *,
    node_count: int,
    edge_count: int,
    calls: list[tuple[str, Any]] | None = None,
) -> None:
    """Replace the SDK IO surface ``load_payload`` imports at call time."""

    import graphrag_sdk
    import graphrag_sdk.core.models as sdk_models

    class _FakeConnection:
        def __init__(self, config: Any) -> None:
            self.config = config

        async def close(self) -> None:
            return None

    class _FakeStore:
        def __init__(self, connection: Any) -> None:
            self.connection = connection

        async def query_raw(self, cypher: str, params: Any = None) -> None:
            if calls is not None:
                calls.append((cypher, params))

        async def upsert_nodes(self, nodes: list[Any]) -> int:
            return node_count

        async def upsert_relationships(self, relationships: list[Any]) -> int:
            return edge_count

    monkeypatch.setattr(graphrag_sdk, "FalkorDBConnection", _FakeConnection)
    monkeypatch.setattr(graphrag_sdk, "GraphStore", _FakeStore)
    monkeypatch.setattr(sdk_models, "GraphNode", lambda **kwargs: kwargs)
    monkeypatch.setattr(sdk_models, "GraphRelationship", lambda **kwargs: kwargs)


def _two_node_payload() -> graph.Payload:
    return graph.build_payload([_decision(1)], [], [])


def test_load_payload_raises_on_node_shortfall(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _two_node_payload()
    _stub_sdk(monkeypatch, node_count=0, edge_count=0)

    with pytest.raises(RuntimeError, match="node load shortfall"):
        asyncio.run(
            graph.load_payload(payload, host="h", port=1, graph_name="g")
        )


def test_load_payload_raises_on_edge_shortfall(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _two_node_payload()
    _stub_sdk(monkeypatch, node_count=len(payload.nodes), edge_count=0)

    with pytest.raises(RuntimeError, match="edge load shortfall"):
        asyncio.run(
            graph.load_payload(payload, host="h", port=1, graph_name="g")
        )


def test_load_payload_writes_embeddings_and_retrieval_indexes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EMBEDDING_MODEL_SLUG", "test/model")
    monkeypatch.setenv("EMBEDDING_DIMENSION", "3")
    payload = graph.build_payload([_decision(1), _decision(2)], [], [])
    calls: list[tuple[str, Any]] = []
    _stub_sdk(monkeypatch, node_count=len(payload.nodes), edge_count=len(payload.edges), calls=calls)

    result = asyncio.run(
        graph.load_payload(
            payload,
            host="h",
            port=1,
            graph_name="g",
            embeddings=DecisionEmbeddings(
                model="test/model",
                dimension=3,
                vectors={1: [0.1, 0.2, 0.3], 2: [0.4, 0.5, 0.6]},
            ),
        )
    )

    assert result.embedded_count == 2
    statements = [cypher for cypher, _ in calls]
    assert "CREATE FULLTEXT INDEX FOR (n:Decision) ON (n.title)" in statements
    assert any(
        "CREATE VECTOR INDEX" in cypher and "dimension:3" in cypher for cypher in statements
    )
    embedding_writes = [
        params
        for cypher, params in calls
        if "SET d.embedding = vecf32(item.vector)" in cypher
    ]
    assert len(embedding_writes) == 1
    assert embedding_writes[0]["batch"] == [
        {"id": "rfc:1", "vector": [0.1, 0.2, 0.3]},
        {"id": "rfc:2", "vector": [0.4, 0.5, 0.6]},
    ]


def test_ingest_snapshot_loads_committed_embeddings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("EMBEDDING_MODEL_SLUG", "test/model")
    monkeypatch.setenv("EMBEDDING_DIMENSION", "2")
    snapshot = tmp_path / "snapshot"
    shutil.copytree(FIXTURE, snapshot)
    (snapshot / "decision-embeddings.jsonl").write_text(
        '{"model":"test/model","dimension":2}\n'
        + "".join(
            json.dumps({"rfc": rfc, "vector": [float(rfc), 1.0]}) + "\n"
            for rfc in (100, 200, 300)
        ),
        encoding="utf-8",
    )
    payload = graph.payload_from_snapshot(snapshot)
    calls: list[tuple[str, Any]] = []
    _stub_sdk(
        monkeypatch,
        node_count=len(payload.nodes),
        edge_count=len(payload.edges),
        calls=calls,
    )

    result = asyncio.run(
        graph.ingest_snapshot(snapshot, host="h", port=1, graph_name="g")
    )

    assert result.embedded_count == 3
    assert any(
        "CREATE VECTOR INDEX" in cypher and "dimension:2" in cypher
        for cypher, _ in calls
    )


def test_load_payload_rejects_embeddings_from_another_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EMBEDDING_MODEL_SLUG", "test/model")
    monkeypatch.setenv("EMBEDDING_DIMENSION", "3")
    payload = graph.build_payload([_decision(1)], [], [])

    with pytest.raises(ValueError, match="query embedder"):
        asyncio.run(
            graph.load_payload(
                payload,
                host="h",
                port=1,
                graph_name="g",
                embeddings=DecisionEmbeddings(
                    model="other/model", dimension=3, vectors={1: [0.1, 0.2, 0.3]}
                ),
            )
        )


def test_load_payload_rejects_embeddings_of_another_dimension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EMBEDDING_MODEL_SLUG", "test/model")
    monkeypatch.setenv("EMBEDDING_DIMENSION", "3")
    payload = graph.build_payload([_decision(1)], [], [])

    with pytest.raises(ValueError, match="query embedder"):
        asyncio.run(
            graph.load_payload(
                payload,
                host="h",
                port=1,
                graph_name="g",
                embeddings=DecisionEmbeddings(
                    model="test/model", dimension=2, vectors={1: [0.1, 0.2]}
                ),
            )
        )


def test_load_payload_without_embeddings_creates_no_vector_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _two_node_payload()
    calls: list[tuple[str, Any]] = []
    _stub_sdk(monkeypatch, node_count=len(payload.nodes), edge_count=len(payload.edges), calls=calls)

    result = asyncio.run(graph.load_payload(payload, host="h", port=1, graph_name="g"))

    assert result.embedded_count == 0
    assert not any("VECTOR INDEX" in cypher for cypher, _ in calls)
    assert not any("vecf32" in cypher for cypher, _ in calls)


def test_load_payload_rejects_embedding_for_unknown_rfc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _two_node_payload()
    _stub_sdk(monkeypatch, node_count=len(payload.nodes), edge_count=0)

    with pytest.raises(ValueError, match="not in the payload"):
        asyncio.run(
            graph.load_payload(
                payload,
                host="h",
                port=1,
                graph_name="g",
                embeddings=DecisionEmbeddings(
                    model="test/model", dimension=2, vectors={999: [0.1, 0.2]}
                ),
            )
        )


def test_decision_embeddings_reject_mixed_dimensions() -> None:
    with pytest.raises(ValueError, match="lengths"):
        DecisionEmbeddings(
            model="test/model", dimension=2, vectors={1: [0.1, 0.2], 2: [0.3]}
        )
