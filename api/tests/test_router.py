"""Offline unit tests for the System-1 question router.

Every test substitutes the ``_post_chat_completion`` seam, so no HTTP call and
no API key are ever needed (``OPENROUTER_API_KEY`` is pinned empty).
"""

from __future__ import annotations

import json

import pytest

from api import llm, router

ENV_VARS = ("OPENROUTER_API_KEY", "DECIDE_MODEL_SLUG", "REASON_MODEL_SLUG", "SPEND_CAP_USD")


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_VARS:
        monkeypatch.setenv(name, "")
    with llm._ledger_lock:
        llm._ledger.clear()


class FakeOpenRouter:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = list(responses)
        self.payloads: list[dict[str, object]] = []

    def __call__(self, payload: dict[str, object]) -> dict[str, object]:
        self.payloads.append(payload)
        return self.responses.pop(0)


def completion(content: str) -> dict[str, object]:
    return {"choices": [{"message": {"content": content}}]}


def decision(choice: str, confidence: float) -> str:
    return json.dumps({"choice": choice, "confidence": confidence})


def test_router_classify_returns_a_label_and_confidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeOpenRouter([completion(decision("decision-provenance", 0.83))])
    monkeypatch.setattr(llm, "_post_chat_completion", fake)

    result = router.router_classify("What did the language team decide about trait objects?")

    assert result.label == "decision-provenance"
    assert result.label in router.ROUTE_LABELS
    assert 0.0 <= result.confidence <= 1.0
    assert result.escalated is False


def test_router_request_constrains_the_choice_to_the_four_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeOpenRouter([completion(decision("fact", 0.9))])
    monkeypatch.setattr(llm, "_post_chat_completion", fake)

    router.router_classify("Which RFC introduced async/await?")

    response_format = fake.payloads[0]["response_format"]
    assert isinstance(response_format, dict)
    json_schema = response_format["json_schema"]
    assert isinstance(json_schema, dict)
    schema = json_schema["schema"]
    assert isinstance(schema, dict)
    assert schema["properties"]["choice"]["enum"] == list(router.ROUTE_LABELS)


def test_router_classify_appends_exactly_one_ledger_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeOpenRouter([completion(decision("impact", 0.7))])
    monkeypatch.setattr(llm, "_post_chat_completion", fake)

    router.router_classify("What touches async/await?")

    records = llm.ledger_records()
    assert len(records) == 1
    assert records[0].choice == "impact"
    assert records[0].confidence == 0.7


def test_router_classify_escalates_low_confidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DECIDE_MODEL_SLUG", "test/decider")
    monkeypatch.setenv("REASON_MODEL_SLUG", "test/reasoner")
    fake = FakeOpenRouter(
        [completion(decision("fact", 0.2)), completion(decision("out-of-graph", 0.9))]
    )
    monkeypatch.setattr(llm, "_post_chat_completion", fake)

    result = router.router_classify("unclear question")

    assert result.label == "out-of-graph"
    assert result.escalated is True
    assert [record.escalated for record in llm.ledger_records()] == [True, True]
