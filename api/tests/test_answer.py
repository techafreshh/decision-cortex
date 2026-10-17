"""Offline tests for the composed answer pipeline (``answer_question``).

The graph is a fake reader and both model seams are injected, so the pipeline
runs end to end with no network and no API key.
"""

from __future__ import annotations

import pytest
from fakes import PipelineDecide, provenance_reader

from api import llm
from api.answer import SCENARIOS, answer_question

ENV_VARS = ("OPENROUTER_API_KEY", "DECIDE_MODEL_SLUG", "REASON_MODEL_SLUG", "SPEND_CAP_USD")

TWO_SENTENCES = "One.\nTwo."


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_VARS:
        monkeypatch.setenv(name, "")
    with llm._ledger_lock:
        llm._ledger.clear()


def test_scenarios_are_the_four_prd_buttons() -> None:
    assert set(SCENARIOS) == {"ask_corpus", "prove_negative", "impact_tour", "async_story"}


def test_fully_cited_answer_is_not_an_abstention() -> None:
    plan = answer_question(
        "Who objected to trait objects?",
        reader=provenance_reader(),
        decide_fn=PipelineDecide(),
        reason_fn=lambda prompt: TWO_SENTENCES,
    )

    assert plan.sentences == ("One.", "Two.")
    assert plan.claims_total == 2
    assert plan.claims_cited == 2
    assert plan.citation_count == 2
    assert plan.abstention_required is False
    assert all(verdict.cited for verdict in plan.verdicts)


def test_an_uncited_sentence_requires_abstention() -> None:
    plan = answer_question(
        "Who objected to trait objects?",
        reader=provenance_reader(),
        decide_fn=PipelineDecide(gate="none"),
        reason_fn=lambda prompt: TWO_SENTENCES,
    )

    assert plan.claims_total == 2
    assert plan.claims_cited == 0
    assert plan.citation_count == 0
    assert plan.abstention_required is True


def test_out_of_graph_short_circuits_before_synthesis() -> None:
    def reason(prompt: str) -> str:
        raise AssertionError("out-of-graph must not synthesize text")

    plan = answer_question(
        "What is the capital of France?",
        reader=provenance_reader(),
        decide_fn=PipelineDecide(route="out-of-graph"),
        reason_fn=reason,
    )

    assert plan.route == "out-of-graph"
    assert plan.sentences == ()
    assert plan.claims_total == 0
    assert plan.abstention_required is True


def test_the_plan_carries_the_executed_cypher_for_the_preview() -> None:
    plan = answer_question(
        "Who objected to trait objects?",
        reader=provenance_reader(),
        decide_fn=PipelineDecide(),
        reason_fn=lambda prompt: TWO_SENTENCES,
    )

    assert any("fulltext.queryNodes" in query for query in plan.queries)
