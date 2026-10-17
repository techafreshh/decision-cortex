"""Offline tests for the scripted-scenario response cache."""

from __future__ import annotations

import pytest
from fakes import DispatchOpenRouter, provenance_reader

from api import events, llm
from api.answer import AnswerPlan, ask_events
from api.cache import ScenarioCache, cache

ENV_VARS = ("OPENROUTER_API_KEY", "DECIDE_MODEL_SLUG", "REASON_MODEL_SLUG", "SPEND_CAP_USD")

TWO_SENTENCES = "One.\nTwo."


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_VARS:
        monkeypatch.setenv(name, "")
    with llm._ledger_lock:
        llm._ledger.clear()
    cache.clear()


def empty_plan() -> AnswerPlan:
    return AnswerPlan(
        route="fact",
        route_confidence=0.9,
        route_escalated=False,
        candidate_count=0,
        rounds=0,
        stopped_early=False,
        queries=(),
        evidence_nodes=(),
        sentences=(),
        verdicts=(),
        citation_count=0,
        claims_total=0,
        claims_cited=0,
        abstention_required=True,
    )


def ledger_event(stream: list[dict]) -> dict:
    return next(event for event in stream if event["type"] == events.LEDGER_UPDATE)


def test_cache_put_get_clear() -> None:
    scenario_cache = ScenarioCache()
    plan = empty_plan()

    assert scenario_cache.get("ask_corpus") is None
    scenario_cache.put("ask_corpus", plan)
    assert scenario_cache.get("ask_corpus") is plan
    scenario_cache.clear()
    assert scenario_cache.get("ask_corpus") is None


def test_second_scripted_call_issues_no_s2_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatcher = DispatchOpenRouter(reason_text=TWO_SENTENCES)
    monkeypatch.setattr(llm, "_post_chat_completion", dispatcher)

    first = list(ask_events(None, "ask_corpus", reader=provenance_reader()))
    second = list(ask_events(None, "ask_corpus", reader=provenance_reader()))

    assert dispatcher.reason_calls == 1
    assert ledger_event(first)["ledger"]["calls"] > 0
    assert ledger_event(second)["ledger"]["calls"] == 0
    assert second[-1]["type"] == events.RUN_FINISHED
    assert second[-1]["citation_count"] == first[-1]["citation_count"]


def test_free_questions_are_never_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    dispatcher = DispatchOpenRouter(reason_text=TWO_SENTENCES)
    monkeypatch.setattr(llm, "_post_chat_completion", dispatcher)

    list(ask_events("Who objected to trait objects?", reader=provenance_reader()))
    list(ask_events("Who objected to trait objects?", reader=provenance_reader()))

    assert dispatcher.reason_calls == 2
