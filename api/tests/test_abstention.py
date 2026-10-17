"""Offline tests for the abstention receipts, came-close trail, and stream event.

No network and no graph: the retrieval result is hand-built and both model seams
are injected, so the receipt math and the ``record_abstention`` placement are
proven deterministically.
"""

from __future__ import annotations

import pytest
from fakes import DispatchOpenRouter, provenance_reader

from api import answer, events, llm, retrieval
from api.abstention import (
    CAME_CLOSE_LIMIT,
    AbstentionTrigger,
    record_abstention,
)

ENV_VARS = ("OPENROUTER_API_KEY", "DECIDE_MODEL_SLUG", "REASON_MODEL_SLUG", "SPEND_CAP_USD")


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_VARS:
        monkeypatch.setenv(name, "")
    with llm._ledger_lock:
        llm._ledger.clear()


def _node(
    node_id: str,
    *,
    label: str = "Decision",
    source: str = "fulltext",
    score: float | None = 1.0,
    title: str | None = None,
) -> retrieval.EvidenceNode:
    properties: dict[str, object] = {"id": node_id}
    if title is not None:
        properties["title"] = title
    return retrieval.EvidenceNode(
        id=node_id, label=label, properties=properties, source=source, score=score
    )


def _result(
    nodes: list[retrieval.EvidenceNode], steps: list[retrieval.QueryStep]
) -> retrieval.RetrievalResult:
    return retrieval.RetrievalResult(
        evidence_nodes=tuple(nodes),
        query_path=tuple(steps),
        candidate_count=len(nodes),
        rounds=1,
        stopped_early=True,
    )


def test_receipt_reports_nodes_chains_and_matches() -> None:
    result = _result(
        [
            _node("rfc:200", source="fulltext", score=3.0),
            _node("message:5001", label="Message", source="traversal", score=None),
        ],
        [
            retrieval.QueryStep("query", "SEED_FULLTEXT", "rfc:200"),
            retrieval.QueryStep("rfc:200", "EVIDENCED_BY", "message:5001"),
        ],
    )

    receipt = record_abstention(
        "Did Rust do X?",
        result,
        trigger=AbstentionTrigger.OUT_OF_GRAPH,
        claims_cited=0,
    )

    assert receipt.nodes_searched == 2
    assert receipt.evidence_chains == 1
    assert receipt.matches == 0


def test_evidence_chains_excludes_seed_steps() -> None:
    result = _result(
        [_node("rfc:200", source="fulltext", score=3.0)],
        [retrieval.QueryStep("query", "SEED_FULLTEXT", "rfc:200")],
    )

    receipt = record_abstention(
        "Did Rust do X?",
        result,
        trigger=AbstentionTrigger.OUT_OF_GRAPH,
        claims_cited=0,
    )

    assert receipt.evidence_chains == 0


def test_came_close_ranks_seed_decisions_by_normalized_relevance() -> None:
    result = _result(
        [
            _node("rfc:v1", source="vector", score=0.0, title="nearest"),
            _node("rfc:v2", source="vector", score=0.2, title="third"),
            _node("rfc:f2", source="fulltext", score=0.9, title="second"),
            _node("rfc:f1", source="fulltext", score=0.5, title="fourth"),
            _node("rfc:f3", source="fulltext", score=0.1, title="fifth"),
            _node("rfc:t1", source="traversal", score=None, title="reached by hop"),
            _node("message:m1", label="Message", source="fulltext", score=5.0),
        ],
        [],
    )

    receipt = record_abstention(
        "Did Rust do X?",
        result,
        trigger=AbstentionTrigger.OUT_OF_GRAPH,
        claims_cited=0,
    )

    assert len(receipt.came_close) == CAME_CLOSE_LIMIT
    assert [entry.id for entry in receipt.came_close] == ["rfc:v1", "rfc:f2", "rfc:v2"]
    assert receipt.came_close[0].title == "nearest"
    assert receipt.came_close[0].label == "Decision"


def test_came_close_ties_break_on_ascending_id() -> None:
    result = _result(
        [
            _node("rfc:b", source="fulltext", score=0.5),
            _node("rfc:a", source="fulltext", score=0.5),
        ],
        [],
    )

    receipt = record_abstention(
        "Did Rust do X?",
        result,
        trigger=AbstentionTrigger.OUT_OF_GRAPH,
        claims_cited=0,
    )

    assert [entry.id for entry in receipt.came_close] == ["rfc:a", "rfc:b"]


def test_came_close_is_empty_without_seed_decisions() -> None:
    result = _result(
        [
            _node("rfc:t1", source="traversal", score=None),
            _node("message:m1", label="Message", source="fulltext", score=1.0),
        ],
        [],
    )

    receipt = record_abstention(
        "Did Rust do X?",
        result,
        trigger=AbstentionTrigger.OUT_OF_GRAPH,
        claims_cited=0,
    )

    assert receipt.came_close == ()


def test_abstention_appends_one_costless_ledger_row() -> None:
    result = _result(
        [_node("rfc:200", source="fulltext", score=3.0)],
        [retrieval.QueryStep("query", "SEED_FULLTEXT", "rfc:200")],
    )

    record_abstention(
        "Did Rust do X?",
        result,
        trigger=AbstentionTrigger.OUT_OF_GRAPH,
        claims_cited=0,
    )

    records = llm.ledger_records()
    assert len(records) == 1
    row = records[0]
    assert row.model == "abstention:out-of-graph"
    assert row.choice == 0
    assert row.confidence is None
    assert row.cost_usd == 0.0
    assert row.escalated is False


def test_only_a_true_negative_or_partial_answer_emits_a_card() -> None:
    assert AbstentionTrigger.OUT_OF_GRAPH.emits_card is True
    assert AbstentionTrigger.UNCITED.emits_card is True
    assert AbstentionTrigger.UNGROUNDED.emits_card is False


def test_ledger_row_is_named_after_its_trigger() -> None:
    result = _result([_node("rfc:200", source="fulltext", score=3.0)], [])

    for trigger in AbstentionTrigger:
        with llm._ledger_lock:
            llm._ledger.clear()
        record_abstention(
            "Did Rust do X?", result, trigger=trigger, claims_cited=1
        )
        assert llm.ledger_records()[0].model == f"abstention:{trigger.value}"


def test_no_record_stream_emits_record_abstention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        llm,
        "_post_chat_completion",
        DispatchOpenRouter(reason_text="", route="out-of-graph"),
    )

    stream = list(answer.ask_events("Did Rust do X?", reader=provenance_reader()))

    tool_starts = [
        event["tool_call_id"]
        for event in stream
        if event["type"] == events.TOOL_CALL_START
    ]
    assert tool_starts == ["router_classify", "retrieve_evidence", "record_abstention"]

    result = next(
        event
        for event in stream
        if event["type"] == events.TOOL_CALL_RESULT
        and event["tool_call_id"] == "record_abstention"
    )
    assert set(result["result"]) == {
        "nodes_searched",
        "evidence_chains",
        "matches",
        "came_close",
    }
    assert result["result"]["matches"] == 0
    assert result["result"]["nodes_searched"] == 3
    assert result["result"]["evidence_chains"] == 2
    assert result["result"]["came_close"] == [
        {"id": "rfc:200", "label": "Decision", "title": "rfc:200"}
    ]

    text_end = next(
        index for index, event in enumerate(stream) if event["type"] == events.TEXT_MESSAGE_END
    )
    abstention = next(
        index
        for index, event in enumerate(stream)
        if event["type"] == events.TOOL_CALL_RESULT
        and event["tool_call_id"] == "record_abstention"
    )
    faithfulness = next(
        index
        for index, event in enumerate(stream)
        if event["type"] == events.FAITHFULNESS_PENDING
    )
    assert text_end < abstention < faithfulness


def test_cited_answer_emits_no_record_abstention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        llm,
        "_post_chat_completion",
        DispatchOpenRouter(reason_text="One.\nTwo.", gate_choice="e0"),
    )

    stream = list(
        answer.ask_events("Who objected to trait objects?", reader=provenance_reader())
    )

    tool_starts = [
        event["tool_call_id"]
        for event in stream
        if event["type"] == events.TOOL_CALL_START
    ]
    assert tool_starts == ["router_classify", "retrieve_evidence", "synthesize", "claim_gate"]
    assert not any(
        event["type"] == events.TOOL_CALL_RESULT
        and event["tool_call_id"] == "record_abstention"
        for event in stream
    )
    assert stream[-1]["abstention_required"] is False


@pytest.mark.parametrize(
    ("route", "claims_cited", "expected"),
    [
        (answer.Route.OUT_OF_GRAPH, 0, AbstentionTrigger.OUT_OF_GRAPH),
        (answer.Route.OUT_OF_GRAPH, 3, AbstentionTrigger.OUT_OF_GRAPH),
        (answer.Route.FACT, 1, AbstentionTrigger.UNCITED),
        (answer.Route.FACT, 0, AbstentionTrigger.UNGROUNDED),
    ],
)
def test_abstention_trigger_classification(
    route: answer.Route, claims_cited: int, expected: AbstentionTrigger
) -> None:
    assert answer._abstention_trigger(route, claims_cited) is expected


def test_partial_citation_plan_carries_the_cited_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        llm,
        "_post_chat_completion",
        DispatchOpenRouter(
            reason_text="One.\nTwo.", route="fact", gate_choices=["e0", "none"]
        ),
    )

    plan = answer.answer_question(
        "Who objected to trait objects?", reader=provenance_reader()
    )

    assert plan.claims_total == 2
    assert plan.claims_cited == 1
    assert plan.abstention_required is True
    assert plan.abstention is not None
    assert plan.abstention.trigger is AbstentionTrigger.UNCITED
    assert plan.abstention.matches == 1


def test_ungrounded_plan_carries_the_ungrounded_trigger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        llm,
        "_post_chat_completion",
        DispatchOpenRouter(reason_text="", route="fact"),
    )

    plan = answer.answer_question(
        "Who objected to trait objects?", reader=provenance_reader()
    )

    assert plan.abstention_required is True
    assert plan.abstention is not None
    assert plan.abstention.trigger is AbstentionTrigger.UNGROUNDED
    assert plan.abstention.trigger.emits_card is False


def test_partial_citation_emits_card_with_the_cited_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        llm,
        "_post_chat_completion",
        DispatchOpenRouter(
            reason_text="One.\nTwo.", route="fact", gate_choices=["e0", "none"]
        ),
    )

    stream = list(
        answer.ask_events("Who objected to trait objects?", reader=provenance_reader())
    )

    result = next(
        event
        for event in stream
        if event["type"] == events.TOOL_CALL_RESULT
        and event["tool_call_id"] == "record_abstention"
    )
    assert result["result"]["matches"] == 1
    assert result["result"]["came_close"] == [
        {"id": "rfc:200", "label": "Decision", "title": "rfc:200"}
    ]
    assert stream[-1]["abstention_required"] is True
    assert stream[-1]["claims_total"] == 2
    assert stream[-1]["claims_cited"] == 1


def test_ungrounded_in_graph_run_abstains_without_a_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        llm,
        "_post_chat_completion",
        DispatchOpenRouter(
            reason_text="One.\nTwo.", route="fact", gate_choices=["none", "none"]
        ),
    )

    stream = list(
        answer.ask_events("Who objected to trait objects?", reader=provenance_reader())
    )

    assert not any(
        event["type"] == events.TOOL_CALL_RESULT
        and event["tool_call_id"] == "record_abstention"
        for event in stream
    )
    assert stream[-1]["abstention_required"] is True
    assert stream[-1]["claims_total"] == 2
    assert stream[-1]["claims_cited"] == 0
