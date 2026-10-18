"""System-2 answer synthesis: one self-contained factual sentence per line.

``synthesize`` calls :func:`api.llm.reason` (the locked S2 wrapper, which
returns the model's text verbatim and appends one S2 ledger row) with a prompt
that lists the retrieved evidence and demands the answer as one factual
sentence per line, with no preamble, bullets, or markdown. The reply is split
into sentences for the per-sentence claim gate; every emitted sentence is a
claim, because the prompt forbids filler.

Splitting is newline-first. A model that ignores the format and writes a single
prose line still yields sentences, via a sentence-boundary fallback that only
runs when the whole reply has no newline — so a numbered or bulleted reply is
never mangled by abbreviation heuristics.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from api import evidence_text, llm
from api.retrieval import EvidenceNode, evidence_line

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_BULLET_RE = re.compile(r"^(?:[-*\u2022]|\d+[.)])\s+")


class _ReasonFn(Protocol):
    """The S2 ``reason`` seam; injected so tests never hit the network."""

    def __call__(self, prompt: str) -> str: ...


@dataclass(frozen=True, slots=True)
class SynthesisResult:
    sentences: tuple[str, ...]


def synthesize(
    question: str,
    route: str,
    evidence: Sequence[EvidenceNode],
    *,
    reason_fn: _ReasonFn = llm.reason,
) -> SynthesisResult:
    """Synthesize an answer over ``evidence`` and split it into sentences."""
    text = reason_fn(_synthesis_prompt(question, route, evidence))
    return SynthesisResult(sentences=_split_sentences(text))


def _synthesis_prompt(
    question: str, route: str, evidence: Sequence[EvidenceNode]
) -> str:
    lines = "\n".join(
        _grounded_evidence_line(index, node)
        for index, node in enumerate(evidence)
    )
    return (
        "You answer questions about the rust-lang/rfcs decision corpus, a graph "
        "of RFC decisions, the discussion comments that evidenced them, and the "
        "people involved.\n"
        "Write the answer as self-contained factual sentences, exactly one per "
        "line. Do not use bullets, numbering, markdown, or any preamble. State "
        "only facts supported by the evidence listed below.\n"
        f"Question: {question}\n"
        f"Route: {route}\n"
        "Evidence:\n"
        f"{lines or '(none)'}\n"
    )


def _grounded_evidence_line(index: int, node: EvidenceNode) -> str:
    """The positional evidence line, plus the node's real text when the
    committed snapshot holds it.

    The graph stores refs, never bodies, so the pinnable ``evidence_line`` is a
    permalink; the prompt grounds it with the bounded snapshot text
    (:mod:`api.evidence_text`) — a synthesis model asked to quote the debate
    gets the debate, not a URL. The ``[eN]`` label stays first so the line is
    sliceable by the same positional contract the claim gate uses.
    """
    text = evidence_text.evidence_text(node)
    if text is None:
        return f"[e{index}] {evidence_line(node)}"
    return f"[e{index}] {evidence_line(node)}\n    text: {text}"


def _split_sentences(text: str) -> tuple[str, ...]:
    stripped = text.strip()
    if not stripped:
        return ()
    if "\n" not in stripped:
        parts = _SENTENCE_RE.split(stripped)
        return tuple(part.strip() for part in parts if part.strip())
    sentences: list[str] = []
    for line in stripped.splitlines():
        cleaned = _BULLET_RE.sub("", line.strip()).strip()
        if cleaned:
            sentences.append(cleaned)
    return tuple(sentences)
