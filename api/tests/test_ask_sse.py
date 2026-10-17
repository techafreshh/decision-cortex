"""Offline tests for the ``POST /ask`` SSE endpoint.

``api.answer.retrieve_evidence`` and ``llm._post_chat_completion`` are
substituted, so the endpoint streams a full event sequence with no graph and no
network.
"""

from __future__ import annotations

import json
import threading

import pytest
from fakes import DispatchOpenRouter, evidence_node
from fastapi.testclient import TestClient

from api import answer, events, llm, retrieval
from api.cache import cache
from api.main import app

ENV_VARS = ("OPENROUTER_API_KEY", "DECIDE_MODEL_SLUG", "REASON_MODEL_SLUG", "SPEND_CAP_USD")

TWO_SENTENCES = "One.\nTwo."


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_VARS:
        monkeypatch.setenv(name, "")
    with llm._ledger_lock:
        llm._ledger.clear()
    cache.clear()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    def fake_retrieve(question, route, **kwargs):
        return retrieval.RetrievalResult(
            evidence_nodes=(
                evidence_node("Decision", "rfc:200", title="Trait objects"),
                evidence_node(
                    "Message",
                    "message:5001",
                    text_ref="https://github.com/rust-lang/rfcs/pull/200#issuecomment-5001",
                ),
            ),
            query_path=(),
            candidate_count=2,
            rounds=1,
            stopped_early=True,
            cypher=("CALL db.idx.fulltext.queryNodes('Decision',$q) YIELD node, score RETURN node, score",),
        )

    monkeypatch.setattr(answer, "retrieve_evidence", fake_retrieve)
    monkeypatch.setattr(
        llm, "_post_chat_completion", DispatchOpenRouter(reason_text=TWO_SENTENCES)
    )
    return TestClient(app)


def parse_sse(body: str) -> list[dict]:
    parsed: list[dict] = []
    for block in body.split("\n\n"):
        block = block.strip("\n")
        if not block:
            continue
        lines = block.split("\n")
        event_type = lines[0].removeprefix("event: ")
        data = json.loads(lines[1].removeprefix("data: "))
        assert data["type"] == event_type
        parsed.append(data)
    return parsed


def test_stream_emits_the_frozen_event_sequence(client: TestClient) -> None:
    response = client.post("/ask", json={"question": "Who objected to trait objects?"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    stream = parse_sse(response.text)

    assert stream[0]["type"] == events.RUN_STARTED
    assert stream[0]["question"] == "Who objected to trait objects?"
    assert stream[-1]["type"] == events.RUN_FINISHED
    assert stream[-1]["citation_count"] == 2
    assert stream[-1]["claims_total"] == 2
    assert stream[-1]["abstention_required"] is False
    assert stream[-1]["ledger"]["calls"] > 0
    assert stream[-1]["ledger"]["total_calls"] == stream[-1]["ledger"]["calls"]

    tool_calls = [event["tool_name"] for event in stream if event["type"] == events.TOOL_CALL_START]
    assert tool_calls == ["router_classify", "retrieve_evidence", "synthesize", "claim_gate"]

    contents = [event for event in stream if event["type"] == events.TEXT_MESSAGE_CONTENT]
    assert [event["delta"] for event in contents] == ["One.", "Two."]
    assert all(event["cited"] is True for event in contents)
    assert all(event["chips"] for event in contents)
    assert contents[0]["chips"][0]["id"] == "rfc:200"

    assert any(event["type"] == events.CYPHER_PREVIEW for event in stream)
    assert any(event["type"] == events.FAITHFULNESS_PENDING for event in stream)


def test_scripted_scenario_ignores_the_question(client: TestClient) -> None:
    response = client.post(
        "/ask", json={"scenario": "ask_corpus", "question": "ignored"}
    )

    assert response.status_code == 200
    stream = parse_sse(response.text)
    assert stream[0]["question"] == answer.SCENARIOS["ask_corpus"]
    assert stream[0]["scenario"] == "ask_corpus"


def test_unknown_scenario_is_rejected(client: TestClient) -> None:
    response = client.post("/ask", json={"scenario": "nope"})

    assert response.status_code == 400
    assert "nope" in response.json()["detail"]


def test_missing_question_and_scenario_is_rejected(client: TestClient) -> None:
    assert client.post("/ask", json={}).status_code == 400
    assert client.post("/ask", json={"question": "   "}).status_code == 400


def test_ledger_events_carry_this_runs_records(client: TestClient) -> None:
    response = client.post("/ask", json={"question": "Who objected to trait objects?"})
    stream = parse_sse(response.text)

    ledger_event = next(event for event in stream if event["type"] == events.LEDGER_UPDATE)
    ledger = ledger_event["ledger"]
    records = ledger["records"]
    assert records
    assert ledger["calls"] == len(records)
    for record in records:
        assert set(record) == {
            "input_digest",
            "choice",
            "confidence",
            "model",
            "latency_ms",
            "cost_usd",
            "escalated",
        }

    assert stream[-1]["ledger"]["records"] == records


def test_ledger_records_do_not_leak_across_concurrent_runs(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A concurrent run's row must never be attributed to this run's footer."""
    foreign = llm.LedgerRecord(
        input_digest="foreign",
        choice="yes",
        confidence=0.5,
        model="foreign-model",
        latency_ms=1,
        cost_usd=0.0,
        escalated=False,
    )

    def fake_retrieve(question, route, **kwargs):
        appender = threading.Thread(target=llm.ledger_append, args=(foreign,))
        appender.start()
        appender.join()
        return retrieval.RetrievalResult(
            evidence_nodes=(evidence_node("Decision", "rfc:200", title="Trait objects"),),
            query_path=(),
            candidate_count=1,
            rounds=1,
            stopped_early=True,
            cypher=(),
        )

    monkeypatch.setattr(answer, "retrieve_evidence", fake_retrieve)

    response = client.post("/ask", json={"question": "Who objected to trait objects?"})
    stream = parse_sse(response.text)
    ledger = next(event for event in stream if event["type"] == events.LEDGER_UPDATE)["ledger"]

    assert "foreign-model" not in [record["model"] for record in ledger["records"]]
    assert ledger["calls"] == len(ledger["records"])
