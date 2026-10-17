"""Integration test for the answer stream against a real FalkorDB.

Marked ``integration``: run in CI by ``falkordb-integration.yml`` (a FalkorDB
service container with ``FALKORDB_HOST``/``FALKORDB_PORT`` set and
``OPENROUTER_API_KEY`` emptied) and skipped in offline runs. The graph is real
and the traversal is real; only the two model seams are injected, so this
proves the emitted sentences are cited by nodes that actually exist in the
graph.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from fakes import PipelineDecide

from api import answer, events, retrieval

FIXTURE = Path(__file__).resolve().parents[2] / "ingest" / "tests" / "fixtures" / "phase1"
GRAPH_NAME = "dc_ask_integration"
QUESTION = "What did the language team decide about trait objects, and who objected?"
TWO_SENTENCES = "RFC 200 introduced trait objects.\nBob objected to RFC 200."

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


def test_every_emitted_sentence_is_cited_by_a_real_node(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ingest import graph

    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    host, port = _target()
    _reset(host, port)
    asyncio.run(
        graph.ingest_snapshot(FIXTURE, host=host, port=port, graph_name=GRAPH_NAME)
    )
    reader = retrieval.FalkorDBGraphReader(host=host, port=port, graph_name=GRAPH_NAME)

    stream = list(
        answer.ask_events(
            QUESTION,
            reader=reader,
            embedder=None,
            decide_fn=PipelineDecide(),
            reason_fn=lambda prompt: TWO_SENTENCES,
        )
    )

    contents = [event for event in stream if event["type"] == events.TEXT_MESSAGE_CONTENT]
    assert [event["delta"] for event in contents] == ["RFC 200 introduced trait objects.", "Bob objected to RFC 200."]
    assert all(event["cited"] is True for event in contents)
    assert all(event["chips"] for event in contents)

    for event in contents:
        for chip in event["chips"]:
            rows = reader.query("MATCH (n {id: $id}) RETURN n.id", {"id": chip["id"]})
            assert rows == [[chip["id"]]]

    finished = stream[-1]
    assert finished["type"] == events.RUN_FINISHED
    assert finished["citation_count"] >= 1
    assert finished["abstention_required"] is False
