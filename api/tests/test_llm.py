"""Offline unit tests for the OpenRouter decide()/reason() wrappers.

Every test substitutes the ``_post_chat_completion`` seam, so no HTTP call
and no API key are ever needed (``OPENROUTER_API_KEY`` is pinned empty).
"""

import hashlib
import json

import pytest
from pydantic import ValidationError

from api import llm

ENV_VARS = (
    "OPENROUTER_API_KEY",
    "DECIDE_MODEL_SLUG",
    "REASON_MODEL_SLUG",
    "SPEND_CAP_USD",
)

LEDGER_FIELDS = [
    "input_digest",
    "choice",
    "confidence",
    "model",
    "latency_ms",
    "cost_usd",
    "escalated",
]


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_VARS:
        monkeypatch.setenv(name, "")
    with llm._ledger_lock:
        llm._ledger.clear()


class FakeOpenRouter:
    """Replaces the HTTP seam with canned completions and records payloads."""

    def __init__(self, responses: list[dict[str, object] | Exception]) -> None:
        self.responses = list(responses)
        self.payloads: list[dict[str, object]] = []

    def __call__(self, payload: dict[str, object]) -> dict[str, object]:
        self.payloads.append(payload)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def completion(content: str, cost: float | None = None) -> dict[str, object]:
    data: dict[str, object] = {"choices": [{"message": {"content": content}}]}
    if cost is not None:
        data["usage"] = {"cost": cost}
    return data


def decision_content(choice: object, confidence: float) -> str:
    return json.dumps({"choice": choice, "confidence": confidence})


def test_decide_one_of_returns_typed_choice_and_ledgers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DECIDE_MODEL_SLUG", "test/decider")
    fake = FakeOpenRouter([completion(decision_content("impact", 0.9), cost=0.0007)])
    monkeypatch.setattr(llm, "_post_chat_completion", fake)

    result = llm.decide(
        "Which route?",
        one_of=["fact", "decision-provenance", "impact", "out-of-graph"],
    )

    assert result == llm.DecideResult(choice="impact", confidence=0.9, escalated=False)
    assert [p["model"] for p in fake.payloads] == ["test/decider"]
    response_format = fake.payloads[0]["response_format"]
    assert isinstance(response_format, dict)
    assert response_format["type"] == "json_schema"
    json_schema = response_format["json_schema"]
    assert isinstance(json_schema, dict)
    assert json_schema["strict"] is True
    schema = json_schema["schema"]
    assert isinstance(schema, dict)
    assert schema["properties"]["choice"]["enum"] == [
        "fact",
        "decision-provenance",
        "impact",
        "out-of-graph",
    ]
    assert fake.payloads[0]["temperature"] == 0.0

    records = llm.ledger_records()
    assert len(records) == 1
    record = records[0]
    assert list(record.model_dump()) == LEDGER_FIELDS
    expected_digest = hashlib.sha256(b"test/decider\x1fWhich route?").hexdigest()
    assert record.input_digest == expected_digest
    assert record.choice == "impact"
    assert record.confidence == 0.9
    assert record.model == "test/decider"
    assert isinstance(record.latency_ms, int) and record.latency_ms >= 0
    assert record.cost_usd == 0.0007
    assert record.escalated is False


@pytest.mark.parametrize(
    "shape",
    [
        llm._OneOf(labels=("fact", "impact")),
        llm._Rating(minimum=0, maximum=5),
        llm._YesNo(),
    ],
)
def test_typed_decision_schema_closes_the_object_for_strict_mode(shape: object) -> None:
    response_format = llm._json_schema_response_format(llm._choice_model(shape))
    json_schema = response_format["json_schema"]
    assert isinstance(json_schema, dict)
    assert json_schema["strict"] is True
    schema = json_schema["schema"]
    assert isinstance(schema, dict)
    assert schema["additionalProperties"] is False


def test_decide_rating_rejects_out_of_range_then_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeOpenRouter(
        [
            completion(json.dumps({"choice": 7, "confidence": 0.8})),
            completion(decision_content(3, 0.7), cost=0.0),
        ]
    )
    monkeypatch.setattr(llm, "_post_chat_completion", fake)

    result = llm.decide("Rate relevance of the async RFC", rating=(0, 5))

    assert result == llm.DecideResult(choice=3, confidence=0.7, escalated=False)
    assert [p["model"] for p in fake.payloads] == [
        llm.FALLBACK_MODEL_SLUG,
        llm.FALLBACK_MODEL_SLUG,
    ]
    records = llm.ledger_records()
    assert len(records) == 2
    assert records[0].choice == '{"choice": 7, "confidence": 0.8}'
    assert records[0].confidence is None
    assert records[0].escalated is False
    assert records[1].choice == 3
    assert records[1].model == llm.FALLBACK_MODEL_SLUG


def test_decide_yes_no_returns_bool_choice(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeOpenRouter([completion(decision_content(True, 0.9))])
    monkeypatch.setattr(llm, "_post_chat_completion", fake)

    result = llm.decide("Is this sentence cited?", yes_no=True)

    assert result == llm.DecideResult(choice=True, confidence=0.9, escalated=False)
    assert isinstance(result.choice, bool)
    record = llm.ledger_records()[0]
    assert record.choice is True
    assert record.model == llm.FALLBACK_MODEL_SLUG


def test_decide_rejects_persistently_malformed_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    garbage = "the router is clearly impact, trust me"
    fake = FakeOpenRouter([completion(garbage), completion(garbage)])
    monkeypatch.setattr(llm, "_post_chat_completion", fake)

    with pytest.raises(llm.ModelOutputError):
        llm.decide("route?", one_of=["fact", "impact"])

    assert len(fake.payloads) == 2
    records = llm.ledger_records()
    assert [record.choice for record in records] == [garbage, garbage]
    assert all(record.confidence is None for record in records)


def test_low_confidence_decide_escalates_to_reason_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DECIDE_MODEL_SLUG", "test/decider")
    monkeypatch.setenv("REASON_MODEL_SLUG", "test/reasoner")
    fake = FakeOpenRouter(
        [
            completion(decision_content("fact", 0.2), cost=0.001),
            completion(decision_content("out-of-graph", 0.95), cost=0.002),
        ]
    )
    monkeypatch.setattr(llm, "_post_chat_completion", fake)

    result = llm.decide(
        "who objected?", one_of=["fact", "decision-provenance", "impact", "out-of-graph"]
    )

    assert result == llm.DecideResult(choice="out-of-graph", confidence=0.95, escalated=True)
    assert [p["model"] for p in fake.payloads] == ["test/decider", "test/reasoner"]
    records = llm.ledger_records()
    assert [record.escalated for record in records] == [True, True]
    assert [record.model for record in records] == ["test/decider", "test/reasoner"]


def test_decide_at_threshold_confidence_does_not_escalate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeOpenRouter([completion(decision_content("fact", 0.6))])
    monkeypatch.setattr(llm, "_post_chat_completion", fake)

    result = llm.decide("route?", one_of=["fact", "impact"])

    assert result.escalated is False
    assert len(fake.payloads) == 1
    assert len(llm.ledger_records()) == 1


def test_reason_returns_synthesis_and_ledgers_without_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REASON_MODEL_SLUG", "test/reasoner")
    fake = FakeOpenRouter([completion("RFC 2191 supersedes RFC 590.", cost=0.003)])
    monkeypatch.setattr(llm, "_post_chat_completion", fake)

    text = llm.reason("Summarize the supersede chain for trait objects")

    assert text == "RFC 2191 supersedes RFC 590."
    assert [p["model"] for p in fake.payloads] == ["test/reasoner"]
    assert "response_format" not in fake.payloads[0]
    assert "temperature" not in fake.payloads[0]
    record = llm.ledger_records()[0]
    assert list(record.model_dump()) == LEDGER_FIELDS
    assert record.choice == "RFC 2191 supersedes RFC 590."
    assert record.confidence is None
    assert record.escalated is False
    assert record.model == "test/reasoner"


def test_reason_defaults_to_the_fallback_slug(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeOpenRouter([completion("Synthesis.")])
    monkeypatch.setattr(llm, "_post_chat_completion", fake)

    assert llm.reason("Synthesize") == "Synthesis."
    assert [p["model"] for p in fake.payloads] == [llm.FALLBACK_MODEL_SLUG]


def test_ledger_append_writes_seven_typed_fields() -> None:
    returned = llm.ledger_append(
        llm.LedgerRecord(
            input_digest="0" * 64,
            choice="decision-provenance",
            confidence=0.4,
            model="test/model",
            latency_ms=88,
            cost_usd=0.0,
            escalated=False,
        )
    )

    stored = llm.ledger_records()[-1]
    assert stored is returned
    dumped = stored.model_dump()
    assert list(dumped) == LEDGER_FIELDS
    assert isinstance(dumped["input_digest"], str)
    assert isinstance(dumped["choice"], str)
    assert isinstance(dumped["confidence"], float)
    assert isinstance(dumped["model"], str)
    assert isinstance(dumped["latency_ms"], int)
    assert isinstance(dumped["cost_usd"], float)
    assert isinstance(dumped["escalated"], bool)
    with pytest.raises(ValidationError):
        llm.LedgerRecord(
            input_digest="0" * 64,
            choice="x",
            confidence=1.5,
            model="test/model",
            latency_ms=88,
            cost_usd=0.0,
            escalated=False,
        )


def test_spend_cap_refuses_new_calls_and_records_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm.ledger_append(
        llm.LedgerRecord(
            input_digest="1" * 64,
            choice="seed",
            confidence=None,
            model="test/model",
            latency_ms=1,
            cost_usd=10.0,
            escalated=False,
        )
    )
    fake = FakeOpenRouter([])
    monkeypatch.setattr(llm, "_post_chat_completion", fake)

    with pytest.raises(llm.SpendCapExceededError):
        llm.reason("blocked before any HTTP call")

    assert fake.payloads == []
    assert len(llm.ledger_records()) == 1


class _FakeResponse:
    def __init__(self, data: object, error: Exception | None = None) -> None:
        self._data = data
        self._error = error

    def raise_for_status(self) -> None:
        if self._error is not None:
            raise self._error

    def json(self) -> object:
        return self._data


def test_post_chat_completion_targets_openrouter_with_bearer_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-123")
    sent: list[dict[str, object]] = []

    def fake_post(url: str, *, headers: dict[str, str], json: object, timeout: float) -> _FakeResponse:
        sent.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return _FakeResponse({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(llm.httpx, "post", fake_post)

    data = llm._post_chat_completion({"model": "m", "messages": []})

    assert data == {"choices": [{"message": {"content": "ok"}}]}
    assert sent[0]["url"] == llm.OPENROUTER_URL
    assert sent[0]["headers"] == {
        "Authorization": "Bearer sk-test-123",
        "Content-Type": "application/json",
    }
    assert sent[0]["json"] == {"model": "m", "messages": []}
    assert sent[0]["timeout"] == llm._REQUEST_TIMEOUT_S


def test_post_chat_completion_requires_an_api_key() -> None:
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        llm._post_chat_completion({"model": "m"})


def test_post_chat_completion_rejects_a_non_object_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-123")
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: _FakeResponse(["nope"]))

    with pytest.raises(llm.ModelOutputError):
        llm._post_chat_completion({"model": "m"})

DECISIONS_ENV_VARS = (*ENV_VARS, "DECIDE_API")


def _decisions_body(
    model: str = "perplexity/pplx-decider-flash-v1.2", **answers: object
) -> dict[str, object]:
    return {
        "model": model,
        "answers": answers,
        "usage": {"input_tokens": 120, "output_tokens": 1, "cost": 0.0000016},
    }


def test_decisions_api_enabled_parses_the_lane(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DECIDE_API", raising=False)
    assert llm.decisions_api_enabled() is False
    monkeypatch.setenv("DECIDE_API", "decisions")
    assert llm.decisions_api_enabled() is True
    monkeypatch.setenv("DECIDE_API", "chat")
    assert llm.decisions_api_enabled() is False


def test_decide_via_decisions_one_of_maps_choice_and_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DECIDE_API", "decisions")
    monkeypatch.setenv("DECIDE_MODEL_SLUG", "perplexity/pplx-decider-flash-v1.2")
    sent: list[dict[str, object]] = []

    def fake_post(payload: dict[str, object]) -> dict[str, object]:
        sent.append(payload)
        return _decisions_body(
            q={
                    "type": "choice",
                    "choice": "decision-provenance",
                    "probabilities": {"fact": 0.01, "decision-provenance": 0.99},
                    "confidence": 0.99,
                }
        )

    monkeypatch.setattr(llm, "_post_decisions", fake_post)

    result = llm.decide(
        "Route the question.", one_of=["fact", "decision-provenance"],
        criteria={"fact": "stated in corpus", "decision-provenance": "objections"},
    )

    assert result.choice == "decision-provenance"
    assert result.confidence == pytest.approx(0.99)
    assert result.escalated is False
    questions = sent[0]["questions"]
    assert questions["q"]["type"] == "choice"
    assert questions["q"]["criteria"] == {
        "fact": "stated in corpus", "decision-provenance": "objections"
    }
    # The run's ledger row carries the real per-call cost from the endpoint.
    rows = [r for r in llm.ledger_records() if r.model.startswith("perplexity/")]
    assert len(rows) == 1
    assert rows[0].cost_usd == pytest.approx(0.0000016)
    assert rows[0].escalated is False


def test_decide_via_decisions_yes_no_reads_the_noul_probability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DECIDE_API", "decisions")

    def fake_post(payload: dict[str, object]) -> dict[str, object]:
        noul = 0.7 if payload["state"] == {"prompt": "round 1: is it enough?"} else 0.35
        return _decisions_body(q={"type": "noul", "noul": noul})

    monkeypatch.setattr(llm, "_post_decisions", fake_post)

    yes = llm.decide("round 1: is it enough?", yes_no=True)
    no = llm.decide("round 2: is it enough?", yes_no=False)

    assert yes.choice is True and yes.confidence == pytest.approx(0.7)
    assert no.choice is False and no.confidence == pytest.approx(0.65)


def test_decide_via_decisions_score_clamps_to_the_scale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DECIDE_API", "decisions")

    def fake_post(payload: dict[str, object]) -> dict[str, object]:
        return _decisions_body(q={"type": "score", "score": 8.6, "confidence": 0.9})

    monkeypatch.setattr(llm, "_post_decisions", fake_post)

    result = llm.decide("rate relevance", rating=(0, 5))

    assert result.choice == 5
    assert result.confidence == pytest.approx(0.9)


def test_decisions_failure_ladder_lands_on_the_chat_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DECIDE_API", "decisions")

    def broken(payload: dict[str, object]) -> dict[str, object]:
        raise llm.ModelOutputError("decisions endpoint returned 500: down")

    chat_calls: list[dict[str, object]] = []

    def fake_chat(payload: dict[str, object]) -> dict[str, object]:
        chat_calls.append(payload)
        return {
            "choices": [
                {"message": {"content": json.dumps({"choice": "impact", "confidence": 0.9})}}
            ]
        }

    monkeypatch.setattr(llm, "_post_decisions", broken)
    monkeypatch.setattr(llm, "_post_chat_completion", fake_chat)

    result = llm.decide("Route.", one_of=["fact", "impact"])

    assert result.choice == "impact"
    assert len(chat_calls) == 1
    rows = llm.ledger_records()
    assert rows[-1].model == llm.FALLBACK_MODEL_SLUG
    assert rows[-1].choice == "impact"
    # The failed decisions lane must not bill anything to the ledger.
    assert all("decisions endpoint" not in str(row.choice) for row in rows)
