"""Offline unit tests for graph-native retrieval and the sufficiency stop.

A fake :class:`GraphReader` returns canned rows and a fake ``decide_fn`` /
embedder keep every test off the network (``OPENROUTER_API_KEY`` is pinned
empty, so the default embedder resolves to ``None``).
"""

from __future__ import annotations

from typing import Any

import pytest

from api import llm, retrieval
from ingest import ontology

ENV_VARS = ("OPENROUTER_API_KEY", "DECIDE_MODEL_SLUG", "REASON_MODEL_SLUG", "SPEND_CAP_USD")


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_VARS:
        monkeypatch.setenv(name, "")
    with llm._ledger_lock:
        llm._ledger.clear()


def node(label: str, node_id: str, **properties: Any) -> dict[str, Any]:
    return {"id": node_id, "label": label, "properties": {"id": node_id, **properties}}


class FakeReader:
    """Dispatches on the query shape; each field is canned rows."""

    def __init__(
        self,
        *,
        vector: list[tuple[str, float]] | None = None,
        fulltext: list[tuple[str, float]] | None = None,
        out: dict[str, list[tuple[str, dict[str, Any]]]] | None = None,
        incoming: dict[str, list[tuple[str, dict[str, Any]]]] | None = None,
        vector_error: Exception | None = None,
    ) -> None:
        self.vector = vector or []
        self.fulltext = fulltext or []
        self.out = out or {}
        self.incoming = incoming or {}
        self.vector_error = vector_error
        self.calls: list[tuple[str, Any]] = []

    def query(self, cypher: str, params: Any = None) -> list[list[Any]]:
        self.calls.append((cypher, params))
        if "vector.queryNodes" in cypher:
            if self.vector_error is not None:
                raise self.vector_error
            return [[node("Decision", nid), score] for nid, score in self.vector]
        if "fulltext.queryNodes" in cypher:
            return [[node("Decision", nid), score] for nid, score in self.fulltext]
        if "MATCH (d:Decision)-[r]->(n)" in cypher:
            rows: list[list[Any]] = []
            for did in params["ids"]:
                rows.extend([did, relation, value] for relation, value in self.out.get(did, []))
            return rows
        if "MATCH (n)-[r]->(d:Decision)" in cypher:
            rows = []
            for did in params["ids"]:
                rows.extend(
                    [value, relation, did] for relation, value in self.incoming.get(did, [])
                )
            return rows
        raise AssertionError(f"unexpected cypher: {cypher}")

    def called(self, marker: str) -> bool:
        return any(marker in cypher for cypher, _ in self.calls)


def decide(answer: bool):
    def _decide(prompt: str, *, yes_no: bool, criteria=None) -> llm.DecideResult[bool]:
        return llm.DecideResult(choice=answer, confidence=0.9, escalated=False)

    return _decide


def fake_embedder(vector: list[float]):
    def _embed(text: str) -> llm.EmbeddingResult:
        return llm.EmbeddingResult(vector=vector, latency_ms=5, cost_usd=0.0001)

    return _embed


def test_fulltext_seed_and_expansion_build_evidence_and_path() -> None:
    reader = FakeReader(
        fulltext=[("rfc:200", 6.0), ("rfc:100", 2.0)],
        out={
            "rfc:200": [
                ("EVIDENCED_BY", node("Message", "message:5001")),
                ("PROPOSED_BY", node("Person", "person:alice")),
            ]
        },
        incoming={"rfc:200": [("OBJECTED", node("Person", "person:bob"))]},
    )

    result = retrieval.retrieve_evidence(
        "What did the language team decide about trait objects?",
        "decision-provenance",
        reader=reader,
        decide_fn=decide(False),
        max_rounds=1,
    )

    assert {n.id for n in result.evidence_nodes} == {
        "rfc:200",
        "rfc:100",
        "message:5001",
        "person:alice",
        "person:bob",
    }
    assert result.candidate_count == 5
    assert result.rounds == 1
    assert result.stopped_early is False
    assert result.query_path
    assert retrieval.QueryStep("query", "SEED_FULLTEXT", "rfc:200") in result.query_path
    assert retrieval.QueryStep("person:bob", "OBJECTED", "rfc:200") in result.query_path
    assert not reader.called("vector.queryNodes")
    assert any(retrieval._OUT_QUERY in query for query in result.cypher)
    assert any(retrieval._IN_QUERY in query for query in result.cypher)


def test_fulltext_seed_respects_top_k_and_ranks_by_score() -> None:
    reader = FakeReader(fulltext=[("rfc:1", 1.0), ("rfc:2", 5.0), ("rfc:3", 3.0)])

    result = retrieval.retrieve_evidence(
        "trait objects",
        "decision-provenance",
        reader=reader,
        decide_fn=decide(False),
        max_rounds=0,
        top_k=2,
    )

    assert {node.id for node in result.evidence_nodes} == {"rfc:2", "rfc:3"}


def test_vector_seed_skipped_when_no_embedder() -> None:
    reader = FakeReader(fulltext=[("rfc:200", 3.0)])

    result = retrieval.retrieve_evidence(
        "trait objects",
        "decision-provenance",
        reader=reader,
        embedder=None,
        decide_fn=decide(True),
        max_rounds=0,
    )

    assert not reader.called("vector.queryNodes")
    assert result.candidate_count == 1


def test_default_embedder_resolves_from_the_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    assert retrieval._resolve_embedder(None) is llm.embed_query

    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    assert retrieval._resolve_embedder(None) is None


def test_vector_seed_used_and_merged_with_fulltext() -> None:
    reader = FakeReader(vector=[("rfc:200", 0.0)], fulltext=[("rfc:200", 5.0)])

    result = retrieval.retrieve_evidence(
        "trait objects",
        "decision-provenance",
        reader=reader,
        embedder=fake_embedder([0.1, 0.2]),
        decide_fn=decide(True),
        max_rounds=0,
    )

    assert reader.called("vector.queryNodes")
    assert result.candidate_count == 1
    assert any(retrieval._VECTOR_QUERY in query for query in result.cypher)
    seed = result.evidence_nodes[0]
    assert seed.source == "vector"
    assert retrieval.QueryStep("query", "SEED_VECTOR", "rfc:200") in result.query_path
    assert retrieval.QueryStep("query", "SEED_FULLTEXT", "rfc:200") not in result.query_path


def test_absent_vector_index_is_an_empty_seed_not_an_error() -> None:
    reader = FakeReader(
        fulltext=[("rfc:200", 3.0)],
        vector_error=Exception("Attempted to access undefined attribute"),
    )

    result = retrieval.retrieve_evidence(
        "trait objects",
        "decision-provenance",
        reader=reader,
        embedder=fake_embedder([0.1, 0.2]),
        decide_fn=decide(True),
        max_rounds=0,
    )

    assert result.candidate_count == 1
    assert result.evidence_nodes[0].source == "fulltext"


def test_sufficiency_true_stops_after_one_round() -> None:
    reader = FakeReader(
        fulltext=[("rfc:200", 3.0)],
        out={"rfc:200": [("SUPERSEDES", node("Decision", "rfc:300"))]},
    )

    result = retrieval.retrieve_evidence(
        "trait objects",
        "decision-provenance",
        reader=reader,
        decide_fn=decide(True),
        max_rounds=3,
    )

    assert result.rounds == 1
    assert result.stopped_early is True


def test_sufficiency_false_runs_to_max_rounds() -> None:
    reader = FakeReader(
        fulltext=[("rfc:200", 3.0)],
        out={
            "rfc:200": [("SUPERSEDES", node("Decision", "rfc:300"))],
            "rfc:300": [("SUPERSEDES", node("Decision", "rfc:400"))],
        },
    )

    result = retrieval.retrieve_evidence(
        "trait objects",
        "decision-provenance",
        reader=reader,
        decide_fn=decide(False),
        max_rounds=2,
    )

    assert result.rounds == 2
    assert result.stopped_early is False
    assert {n.id for n in result.evidence_nodes} >= {"rfc:200", "rfc:300", "rfc:400"}


def test_incoming_supersession_promotes_a_decision_into_the_next_frontier() -> None:
    reader = FakeReader(
        fulltext=[("rfc:200", 3.0)],
        incoming={"rfc:200": [("SUPERSEDES", node("Decision", "rfc:300"))]},
        out={"rfc:300": [("SUPERSEDES", node("Decision", "rfc:400"))]},
    )

    result = retrieval.retrieve_evidence(
        "trait objects",
        "impact",
        reader=reader,
        decide_fn=decide(False),
        max_rounds=2,
    )

    assert result.rounds == 2
    assert {n.id for n in result.evidence_nodes} >= {"rfc:200", "rfc:300", "rfc:400"}
    assert retrieval.QueryStep("rfc:300", "SUPERSEDES", "rfc:200") in result.query_path
    assert retrieval.QueryStep("rfc:300", "SUPERSEDES", "rfc:400") in result.query_path


def test_retrieve_evidence_appends_one_ledger_record(monkeypatch: pytest.MonkeyPatch) -> None:
    reader = FakeReader(fulltext=[("rfc:200", 3.0)])
    monkeypatch.setattr(
        llm,
        "_post_chat_completion",
        lambda payload: {"choices": [{"message": {"content": '{"choice": true, "confidence": 0.9}'}}]},
    )

    result = retrieval.retrieve_evidence(
        "trait objects",
        "decision-provenance",
        reader=reader,
        decide_fn=llm.decide,
        max_rounds=1,
    )

    retrieval_rows = [
        record
        for record in llm.ledger_records()
        if record.model == "retrieval:graph-native"
    ]
    assert len(retrieval_rows) == 1
    row = retrieval_rows[0]
    assert row.choice == result.candidate_count
    assert row.confidence is None
    assert row.escalated is False


def test_retrieval_ledger_row_carries_the_query_embedding_trace() -> None:
    reader = FakeReader(fulltext=[("rfc:200", 3.0)])

    retrieval.retrieve_evidence(
        "trait objects",
        "decision-provenance",
        reader=reader,
        embedder=fake_embedder([0.1, 0.2]),
        decide_fn=decide(True),
        max_rounds=0,
    )

    rows = [record for record in llm.ledger_records() if record.model == "retrieval:graph-native"]
    assert len(rows) == 1
    assert rows[0].latency_ms == 5
    assert rows[0].cost_usd == 0.0001


def test_vector_query_failure_that_is_not_a_missing_index_raises() -> None:
    reader = FakeReader(
        fulltext=[("rfc:200", 3.0)],
        vector_error=RuntimeError("connection refused"),
    )

    with pytest.raises(RuntimeError, match="connection refused"):
        retrieval.retrieve_evidence(
            "trait objects",
            "decision-provenance",
            reader=reader,
            embedder=fake_embedder([0.1, 0.2]),
            decide_fn=decide(True),
            max_rounds=0,
        )


def test_fulltext_terms_drop_stopwords_and_dedupe() -> None:
    terms = retrieval._fulltext_terms(
        "What did the language team decide about trait objects, and who objected?"
    )

    assert terms == ["language", "team", "decide", "about", "trait", "objects", "objected"]


def test_sufficiency_facts_reduce_the_gathered_graph() -> None:
    evidence = {
        "rfc:200": retrieval.EvidenceNode(
            id="rfc:200", label="Decision", properties={}, source="vector", score=0.25
        ),
        "rfc:100": retrieval.EvidenceNode(
            id="rfc:100", label="Decision", properties={}, source="fulltext", score=0.4
        ),
        "person:bob": retrieval.EvidenceNode(
            id="person:bob", label="Person", properties={}, source="traversal", score=None
        ),
    }
    path = [
        retrieval.QueryStep("query", "SEED_VECTOR", "rfc:200"),
        retrieval.QueryStep("query", "SEED_FULLTEXT", "rfc:100"),
        retrieval.QueryStep("person:bob", "OBJECTED", "rfc:200"),
    ]

    facts = retrieval._sufficiency_facts("q", "decision-provenance", evidence, path, 1, 2)

    assert facts.candidate_count == 3
    assert facts.decision_count == 2
    assert facts.evidence_type_counts == {"OBJECTED": 1}
    assert facts.top_score == pytest.approx(0.75)
    assert facts.seed_count == 2


def test_connection_from_env_reads_the_falkordb_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FALKORDB_HOST", "graph.internal")
    monkeypatch.setenv("FALKORDB_PORT", "7000")
    monkeypatch.setenv("FALKORDB_GRAPH", "cortex")

    connection = retrieval.connection_from_env()

    assert connection == retrieval.FalkorDBConnection(
        host="graph.internal", port=7000, graph_name="cortex"
    )


def test_sufficiency_stop_returns_the_boolean_choice() -> None:
    facts = retrieval.SufficiencyFacts(
        question="q",
        route="fact",
        candidate_count=1,
        decision_count=1,
        evidence_type_counts={},
        top_score=0.5,
        seed_count=1,
        round_index=1,
        max_rounds=2,
    )

    assert retrieval.sufficiency_stop(facts, decide_fn=decide(True)) is True
    assert retrieval.sufficiency_stop(facts, decide_fn=decide(False)) is False


def test_retrieval_relations_match_the_schema() -> None:
    decision_out = {
        relation.label
        for relation in ontology.SCHEMA.relations
        if any(src == "Decision" for src, _ in relation.patterns)
    }
    decision_in = {
        relation.label
        for relation in ontology.SCHEMA.relations
        if any(dst == "Decision" for _, dst in relation.patterns)
    }

    assert set(retrieval._OUT_RELATIONS) == decision_out
    assert set(retrieval._IN_RELATIONS) == decision_in


def test_node_title_properties_match_the_schema() -> None:
    declared = {
        entity.label: {prop.name for prop in entity.properties}
        for entity in ontology.SCHEMA.entities
    }

    assert set(retrieval._DISPLAY_PROPERTIES) == set(declared)
    for label, property_name in retrieval._DISPLAY_PROPERTIES.items():
        assert property_name in declared[label]
