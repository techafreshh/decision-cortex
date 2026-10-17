"""Offline tests for System-2 synthesis and its sentence splitting.

Every test injects ``reason_fn`` or substitutes ``_post_chat_completion``, so
no HTTP call and no API key are needed (``OPENROUTER_API_KEY`` is pinned empty).
"""

from __future__ import annotations

import pytest
from fakes import DispatchOpenRouter, evidence_node

from api import llm, synthesis

ENV_VARS = ("OPENROUTER_API_KEY", "DECIDE_MODEL_SLUG", "REASON_MODEL_SLUG", "SPEND_CAP_USD")

EVIDENCE = (evidence_node("Decision", "rfc:200", title="Trait objects"),)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_VARS:
        monkeypatch.setenv(name, "")
    with llm._ledger_lock:
        llm._ledger.clear()


def reason(text: str):
    return lambda prompt: text


def test_synthesize_splits_one_sentence_per_line() -> None:
    result = synthesis.synthesize(
        "q", "fact", EVIDENCE, reason_fn=reason("A. B.\nC. D.")
    )

    assert result.sentences == ("A. B.", "C. D.")


def test_synthesize_drops_blank_lines_and_bullet_markers() -> None:
    result = synthesis.synthesize(
        "q", "fact", EVIDENCE, reason_fn=reason("\n- First.\n* Second.\n\n")
    )

    assert result.sentences == ("First.", "Second.")


def test_synthesize_falls_back_to_sentence_boundaries_on_one_line() -> None:
    result = synthesis.synthesize(
        "q", "fact", EVIDENCE, reason_fn=reason("One. Two? Three!")
    )

    assert result.sentences == ("One.", "Two?", "Three!")


def test_synthesize_returns_no_sentences_for_an_empty_completion() -> None:
    result = synthesis.synthesize("q", "fact", EVIDENCE, reason_fn=reason("  \n "))

    assert result.sentences == ()


def test_synthesize_lists_evidence_in_the_prompt() -> None:
    prompts: list[str] = []

    def capture(prompt: str) -> str:
        prompts.append(prompt)
        return "Sentence."

    synthesis.synthesize("Who objected?", "decision-provenance", EVIDENCE, reason_fn=capture)

    assert "[e0] Decision rfc:200: Trait objects" in prompts[0]
    assert "Who objected?" in prompts[0]
    assert "one per line" in prompts[0]


def test_synthesize_appends_exactly_one_s2_ledger_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        llm, "_post_chat_completion", DispatchOpenRouter(reason_text="Sentence.", reason_cost=0.004)
    )

    synthesis.synthesize("q", "fact", EVIDENCE, reason_fn=llm.reason)

    records = llm.ledger_records()
    assert len(records) == 1
    assert records[0].choice == "Sentence."
    assert records[0].confidence is None
    assert records[0].cost_usd == 0.004
