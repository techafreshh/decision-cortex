"""Integration test for graph-native retrieval against a real FalkorDB.

Marked ``integration``: run in CI by ``falkordb-integration.yml`` (a FalkorDB
service container with ``FALKORDB_HOST``/``FALKORDB_PORT`` set and
``OPENROUTER_API_KEY`` emptied) and skipped in offline runs. The fixture graph
carries no embeddings, so the vector seed is skipped and this exercises the
full-text seed plus the real multi-hop traversal with zero LLM calls.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Sequence
from pathlib import Path

import pytest

from api import llm, retrieval, router
from ingest import graph
from ingest.embeddings import DecisionEmbeddings

FIXTURE = Path(__file__).resolve().parents[2] / "ingest" / "tests" / "fixtures" / "phase1"
GRAPH_NAME = "dc_retrieval_integration"
QUESTION = "What did the language team decide about trait objects, and who objected?"

pytestmark = pytest.mark.integration


def _target() -> tuple[str, int]:
    host = os.environ.get("FALKORDB_HOST")
    port = os.environ.get("FALKORDB_PORT")
    if not host or not port:
        pytest.skip("FALKORDB_HOST/FALKORDB_PORT unset; integration needs a FalkorDB")
    return host, int(port)


def _reset(host: str, port: int) -> None:
    from falkordb import FalkorDB

    FalkorDB(host=host, port=port).select_graph(GRAPH_NAME).query(
        "MATCH (n) DETACH DELETE n"
    )


def _sufficient(_prompt: str, *, yes_no: bool) -> llm.DecideResult[bool]:
    return llm.DecideResult(choice=False, confidence=0.9, escalated=False)


def _route_decision_provenance(
    _prompt: str, *, one_of: Sequence[str]
) -> llm.DecideResult[str]:
    return llm.DecideResult(choice="decision-provenance", confidence=0.9, escalated=False)


def test_decision_provenance_question_retrieves_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    host, port = _target()
    _reset(host, port)
    asyncio.run(
        graph.ingest_snapshot(FIXTURE, host=host, port=port, graph_name=GRAPH_NAME)
    )

    reader = retrieval.FalkorDBGraphReader(
        host=host, port=port, graph_name=GRAPH_NAME
    )
    route = router.router_classify(QUESTION, decide_fn=_route_decision_provenance)
    assert route.label == "decision-provenance"
    result = retrieval.retrieve_evidence(
        QUESTION,
        route.label,
        reader=reader,
        embedder=None,
        decide_fn=_sufficient,
        max_rounds=2,
    )

    assert result.candidate_count >= 1
    assert result.query_path
    assert "rfc:200" in {node.id for node in result.evidence_nodes}
    assert retrieval.QueryStep("query", "SEED_FULLTEXT", "rfc:200") in result.query_path
    assert retrieval.QueryStep("person:bob", "OBJECTED", "rfc:200") in result.query_path


def _vector_embedder(vector: list[float]):
    def _embed(_text: str) -> llm.EmbeddingResult:
        return llm.EmbeddingResult(vector=vector, latency_ms=1, cost_usd=0.0)

    return _embed


def test_vector_seed_finds_the_nearest_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setenv("EMBEDDING_DIMENSION", "4")
    host, port = _target()
    _reset(host, port)
    payload = graph.payload_from_snapshot(FIXTURE)
    graph.validate_payload(payload)
    embeddings = DecisionEmbeddings(
        model=llm.embedding_model_slug(),
        dimension=4,
        vectors={
            100: [1.0, 0.0, 0.0, 0.0],
            200: [0.0, 1.0, 0.0, 0.0],
            300: [0.0, 0.0, 1.0, 0.0],
        },
    )
    asyncio.run(
        graph.load_payload(
            payload, host=host, port=port, graph_name=GRAPH_NAME, embeddings=embeddings
        )
    )

    reader = retrieval.FalkorDBGraphReader(host=host, port=port, graph_name=GRAPH_NAME)
    result = retrieval.retrieve_evidence(
        "zzz-no-fulltext-match",
        "fact",
        reader=reader,
        embedder=_vector_embedder([0.0, 1.0, 0.0, 0.0]),
        decide_fn=_sufficient,
        max_rounds=0,
    )

    vector_seeds = {node.id for node in result.evidence_nodes if node.source == "vector"}
    assert "rfc:200" in vector_seeds
    nearest = next(node for node in result.evidence_nodes if node.id == "rfc:200")
    assert nearest.score == 0.0
    assert retrieval.QueryStep("query", "SEED_VECTOR", "rfc:200") in result.query_path
