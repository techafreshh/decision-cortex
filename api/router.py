"""System-1 question router: one of four routes plus a calibrated confidence.

``router_classify`` rides the typed :func:`api.llm.decide` wrapper with a
1-of-4 choice, so the label is constrained by the request's strict JSON schema
and a low-confidence classification escalates to the S2 model exactly as every
other ``decide()`` does. The call lands in the decision ledger via ``decide``.

The four routes are the PRD §7.1 ones: ``fact`` (stated in the corpus),
``decision-provenance`` (trace a decision to who decided/objected and on what
evidence), ``impact`` (what a decision touches), and ``out-of-graph`` (not
answerable from the rust-lang/rfcs decision graph). ``out-of-graph`` is the
router's contribution to the abstention path; acting on it is the answer
pipeline's job, not the router's.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from api import llm

ROUTE_LABELS: tuple[str, ...] = (
    "fact",
    "decision-provenance",
    "impact",
    "out-of-graph",
)

Route = Literal["fact", "decision-provenance", "impact", "out-of-graph"]

_ROUTER_PROMPT = (
    "You route questions about the rust-lang/rfcs decision corpus, a graph of "
    "RFC decisions, the people who proposed them, the discussion comments that "
    "evidenced them, and the decisions they supersede.\n"
    "Classify the question into exactly one route:\n"
    "- fact: its answer is stated in an RFC's own text, title, or status "
    "(for example which RFC introduced a language feature).\n"
    "- decision-provenance: it asks to trace a decision to its source — who "
    "decided, who objected or supported, or what discussion or commit evidences it.\n"
    "- impact: it asks what a decision touches, depends on, or would affect if "
    "revisited — its blast radius across related decisions, areas, and teams.\n"
    "- out-of-graph: it cannot be answered from the rust-lang/rfcs decision "
    "graph (a different project, an opinion, or a topic the corpus never decided).\n"
)


class _DecideFn(Protocol):
    """The ``decide`` seam; injected so tests never hit the network."""

    def __call__(
        self, prompt: str, *, one_of: Sequence[str]
    ) -> llm.DecideResult[str]: ...


@dataclass(frozen=True, slots=True)
class RouterResult:
    """A routing decision: the chosen label, its confidence, and escalation."""

    label: Route
    confidence: float
    escalated: bool


def router_classify(
    question: str, *, decide_fn: _DecideFn = llm.decide
) -> RouterResult:
    """Classify ``question`` into one of :data:`ROUTE_LABELS`."""
    result = decide_fn(f"{_ROUTER_PROMPT}Question: {question}", one_of=ROUTE_LABELS)
    return RouterResult(
        label=result.choice,  # type: ignore[arg-type]
        confidence=result.confidence,
        escalated=result.escalated,
    )
