"""Integration tests for the abstention receipts against a real FalkorDB.

Marked ``integration``: run in CI by ``falkordb-integration.yml`` (a FalkorDB
service container with ``FALKORDB_HOST``/``FALKORDB_PORT`` set and
``OPENROUTER_API_KEY`` emptied) and skipped in offline runs. The real snapshot
is ingested once for the module, and only the two model seams are injected, so
the receipts count nodes and name came-close proposals that actually exist in
the graph.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import pytest
from fakes import PipelineDecide

from api import answer, events, retrieval

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / "snapshot"
QUESTIONS = ROOT / "verification" / "questions.jsonl"
GRAPH_NAME = "dc_abstention_integration"
NO_RECORD_COUNT = 10
NLL_RFC = 2094

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


def _questions() -> list[dict[str, Any]]:
    with QUESTIONS.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


@pytest.fixture(scope="module")
def reader() -> retrieval.FalkorDBGraphReader:
    from ingest import graph

    host, port = _target()
    previous = os.environ.get("OPENROUTER_API_KEY")
    os.environ["OPENROUTER_API_KEY"] = ""
    try:
        _reset(host, port)
        asyncio.run(
            graph.ingest_snapshot(SNAPSHOT, host=host, port=port, graph_name=GRAPH_NAME)
        )
        yield retrieval.FalkorDBGraphReader(host=host, port=port, graph_name=GRAPH_NAME)
    finally:
        if previous is None:
            os.environ.pop("OPENROUTER_API_KEY", None)
        else:
            os.environ["OPENROUTER_API_KEY"] = previous


def _stream(
    reader: retrieval.FalkorDBGraphReader,
    question: str,
    decide: PipelineDecide,
    *,
    reason_text: str = "This unsupported sentence must be flagged.",
) -> list[dict[str, Any]]:
    return list(
        answer.ask_events(
            question,
            reader=reader,
            embedder=None,
            decide_fn=decide,
            reason_fn=lambda prompt: reason_text,
        )
    )


def _abstention_card(stream: list[dict[str, Any]]) -> dict[str, Any]:
    return next(
        event["result"]
        for event in stream
        if event["type"] == events.TOOL_CALL_RESULT
        and event["tool_call_id"] == "record_abstention"
    )


def test_no_record_questions_abstain_with_receipts(
    reader: retrieval.FalkorDBGraphReader,
) -> None:
    no_record = [entry for entry in _questions() if entry["type"] == "no_record"]
    assert len(no_record) == NO_RECORD_COUNT

    for entry in no_record:
        stream = _stream(reader, entry["question"], PipelineDecide(route="out-of-graph"))
        finished = stream[-1]
        assert finished["type"] == events.RUN_FINISHED
        assert finished["abstention_required"] is True
        card = _abstention_card(stream)
        assert card["matches"] == 0
        assert isinstance(card["nodes_searched"], int)
        assert isinstance(card["evidence_chains"], int)
        assert card["nodes_searched"] >= 0


def test_ungrounded_claim_abstains_without_a_card(
    reader: retrieval.FalkorDBGraphReader,
) -> None:
    """An in-graph run whose every claim is uncited abstains but shows no card.

    This is the R1 guard on the real graph: a failed gate (or a failed model
    call) must not render as a confident "no record" verdict.
    """
    stream = _stream(
        reader,
        "What did the language team decide about trait objects, and who objected?",
        PipelineDecide(route="fact", gate="none"),
    )

    assert stream[-1]["abstention_required"] is True
    assert not any(
        event["type"] == events.TOOL_CALL_RESULT
        and event["tool_call_id"] == "record_abstention"
        for event in stream
    )


def test_partial_citation_emits_card_with_a_match(
    reader: retrieval.FalkorDBGraphReader,
) -> None:
    """A run that cites one of two sentences abstains and still shows a card."""
    stream = _stream(
        reader,
        "What did the language team decide about trait objects, and who objected?",
        PipelineDecide(route="fact", gate_choices=["e0", "none"]),
        reason_text=(
            "Trait objects let values of different types share a vtable.\n"
            "This unsupported sentence must be flagged."
        ),
    )

    assert stream[-1]["abstention_required"] is True
    card = _abstention_card(stream)
    assert card["matches"] == 1
    assert card["nodes_searched"] >= 1


def test_came_close_names_real_nodes(reader: retrieval.FalkorDBGraphReader) -> None:
    stream = _stream(
        reader, answer.SCENARIOS["prove_negative"], PipelineDecide(route="out-of-graph")
    )

    card = _abstention_card(stream)
    assert card["came_close"]
    for entry in card["came_close"]:
        rows = reader.query("MATCH (n {id: $id}) RETURN n.id", {"id": entry["id"]})
        assert rows == [[entry["id"]]]
        assert entry["label"] == "Decision"


def test_gold_question_does_not_abstain(reader: retrieval.FalkorDBGraphReader) -> None:
    question = next(
        entry["question"] for entry in _questions() if entry.get("expected_rfc") == NLL_RFC
    )
    stream = _stream(reader, question, PipelineDecide(route="fact", gate="e0"))

    finished = stream[-1]
    assert finished["abstention_required"] is False
    assert finished["citation_count"] >= 1
    assert not any(
        event["type"] == events.TOOL_CALL_RESULT
        and event["tool_call_id"] == "record_abstention"
        for event in stream
    )
