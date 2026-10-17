"""Offline tests for the System-1 per-sentence claim gate."""

from __future__ import annotations

from fakes import evidence_node

from api import llm
from api.claim_gate import claim_gate

EVIDENCE = (
    evidence_node("Decision", "rfc:200", title="Trait objects"),
    evidence_node("Message", "message:5001", title="I object"),
)


def verdict(choice: str, *, confidence: float = 0.8, escalated: bool = False):
    def decide(prompt: str, *, one_of):
        assert "e0" in one_of and "none" in one_of
        return llm.DecideResult(choice=choice, confidence=confidence, escalated=escalated)

    return claim_gate("A sentence.", EVIDENCE, decide_fn=decide)


def test_gate_maps_the_chosen_label_to_a_real_evidence_id() -> None:
    result = verdict("e1")

    assert result.cited is True
    assert result.evidence_ids == ("message:5001",)
    assert result.confidence == 0.8
    assert result.escalated is False


def test_gate_none_is_uncited_but_keeps_the_confidence() -> None:
    result = verdict("none", confidence=0.7)

    assert result.cited is False
    assert result.evidence_ids == ()
    assert result.confidence == 0.7


def test_gate_propagates_escalation() -> None:
    assert verdict("e0", escalated=True).escalated is True


def test_gate_without_evidence_never_calls_the_model() -> None:
    def decide(prompt: str, *, one_of):
        raise AssertionError("the gate must not call the model with no evidence")

    result = claim_gate("A sentence.", (), decide_fn=decide)

    assert result.cited is False
    assert result.evidence_ids == ()
    assert result.confidence is None


def test_gate_treats_unusable_model_output_as_uncited() -> None:
    def decide(prompt: str, *, one_of):
        raise llm.ModelOutputError("not schema-valid")

    result = claim_gate("A sentence.", EVIDENCE, decide_fn=decide)

    assert result.cited is False
    assert result.confidence is None
    assert result.escalated is False


def test_gate_prompt_labels_every_evidence_node() -> None:
    prompts: list[str] = []

    def decide(prompt: str, *, one_of):
        prompts.append(prompt)
        return llm.DecideResult(choice="e0", confidence=0.9, escalated=False)

    claim_gate("Who objected?", EVIDENCE, decide_fn=decide)

    assert "[e0] Decision rfc:200: Trait objects" in prompts[0]
    assert "[e1] Message message:5001: I object" in prompts[0]
