"""System-1 claim gate: map one answer sentence to the evidence supporting it.

The PRD §7.1 gate is "per answer sentence: supported by which evidence? — y/n +
confidence". A boolean alone cannot say *which* node, and the citation chips
need the node id, so the gate asks one ``decide()`` question per sentence over
the retrieved evidence: the labels are positional (``e0``, ``e1``, …) plus
``none``, and the chosen label maps back to a real node id. ``none`` is the
y/n "no" branch. The call lands in the ledger via ``decide``.

A flaky gate must not crash the answer stream: an unusable model output is
recorded as an uncited sentence (``confidence=None``), which flags the sentence
and routes the answer to abstention rather than shipping an unsupported claim.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from api import evidence_text, llm
from api.retrieval import EvidenceNode, evidence_line

#: Bounded evidence excerpt carried into the gate prompt. The gate runs once
#: per sentence over every candidate, so its excerpt is tighter than the
#: synthesis one (:mod:`api.synthesis`) — enough text to recognize the
#: supporting node, not enough for one message body to dominate the choice.
GATE_TEXT_LIMIT = 240


class _DecideFn(Protocol):
    """The ``decide`` seam; injected so tests never hit the network."""

    def __call__(
        self, prompt: str, *, one_of: Sequence[str]
    ) -> llm.DecideResult[str]: ...


@dataclass(frozen=True, slots=True)
class ClaimVerdict:
    """One sentence's gate result: cited (and by which nodes) or not."""

    sentence: str
    cited: bool
    confidence: float | None
    evidence_ids: tuple[str, ...]
    escalated: bool


def claim_gate(
    sentence: str,
    evidence: Sequence[EvidenceNode],
    *,
    decide_fn: _DecideFn = llm.decide,
) -> ClaimVerdict:
    """Return whether ``sentence`` is supported, and by which evidence nodes."""
    if not evidence:
        return _uncited(sentence, confidence=None, escalated=False)

    labels = [f"e{index}" for index in range(len(evidence))] + ["none"]
    try:
        result = decide_fn(_gate_prompt(sentence, evidence), one_of=labels)
    except llm.ModelOutputError:
        return _uncited(sentence, confidence=None, escalated=False)

    if result.choice == "none":
        return _uncited(sentence, confidence=result.confidence, escalated=result.escalated)

    index = int(result.choice[1:])
    return ClaimVerdict(
        sentence=sentence,
        cited=True,
        confidence=result.confidence,
        evidence_ids=(evidence[index].id,),
        escalated=result.escalated,
    )


def _uncited(
    sentence: str, *, confidence: float | None, escalated: bool
) -> ClaimVerdict:
    return ClaimVerdict(
        sentence=sentence,
        cited=False,
        confidence=confidence,
        evidence_ids=(),
        escalated=escalated,
    )


def _gate_prompt(sentence: str, evidence: Sequence[EvidenceNode]) -> str:
    lines = "\n".join(
        f"[e{index}] {_grounded_line(node)}" for index, node in enumerate(evidence)
    )
    return (
        "You decide whether a sentence from an answer about the rust-lang/rfcs "
        "decision corpus is supported by one of the retrieved evidence nodes.\n"
        "Reply with the label of the single node that best supports the "
        "sentence, or none if no node supports it.\n"
        f"Sentence: {sentence}\n"
        "Evidence:\n"
        f"{lines}\n"
    )


def _grounded_line(node: EvidenceNode) -> str:
    """The evidence line plus a bounded snippet of its real snapshot text.

    The gate picks the node that supports the sentence; matching against the
    referenced debate text (``api.evidence_text``) pins the choice to the
    record's content instead of a permalink the model cannot judge.
    """
    text = evidence_text.evidence_text(node)
    if text is None:
        return evidence_line(node)
    return f"{evidence_line(node)}\n    text: {text[:GATE_TEXT_LIMIT]}"
