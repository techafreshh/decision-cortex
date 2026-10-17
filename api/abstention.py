"""The negative-proof path: compile abstention receipts and a came-close trail.

``record_abstention`` is the PRD §7.1 tool that packages a negative verdict. It
reads the retrieval result the answer pipeline already produced and returns an
:class:`AbstentionReceipt` for the web ``NoRecordCard``: how many nodes were
searched, how many evidence chains were walked, how many claims matched (zero
only for a true negative), and up to :data:`CAME_CLOSE_LIMIT` real decisions the
search reached without answering the question.

An abstention is classified by :class:`AbstentionTrigger`. ``out-of-graph`` (a
true negative) and ``uncited`` (a partial answer whose gate left some key claim
uncited) warrant the card; ``ungrounded`` — an in-graph run that grounded *no*
claim, whether the synthesis came back empty or the gate cited none of its
sentences (a failed model call lands here too) — abstains and ledgers a row but
emits no card, so a model failure is never rendered as a confident "no record"
verdict.

The came-close trail is deliberately narrow. Only *seed* Decisions count — the
nodes retrieval started from — because a node reached by traversal was found
*through* a seed, so it did not itself "come close". Entries are ranked by
normalized relevance (a vector cosine distance inverted to a similarity; a
full-text score as-is) and tie-broken by ascending id, and every entry is built
from a node already in the retrieval result. The trail can never name a node the
search did not actually find, so it cannot fabricate a near-miss.

Each call appends one decision-ledger row named after its trigger, carrying the
match count as its choice and no cost — an abstention is not an LLM call.
Appending here, at plan-build time, keeps a cached scenario replay at zero new
ledger rows: ``ask_events`` only computes on a cache miss.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from api import llm
from api.retrieval import SEED_RELATIONS, EvidenceNode, RetrievalResult, node_title

#: Most "close proposals" the trail surfaces; enough to show a near-miss
#: without turning the card into a second page of search results.
CAME_CLOSE_LIMIT = 3

#: Seed sources whose Decisions are candidates for the came-close trail.
_SEED_SOURCES = ("vector", "fulltext")


class AbstentionTrigger(StrEnum):
    """Why an answer abstained; selects the ledger label and whether the card emits.

    ``OUT_OF_GRAPH`` is the router's true negative. ``UNCITED`` is a partial
    answer: synthesis produced claims and the gate grounded some but not all of
    them. Both are contract abstentions and emit the ``NoRecordCard``.
    ``UNGROUNDED`` is an in-graph run with no grounded claim at all — an empty
    synthesis, or a gate that cited none of the sentences (including a failed
    model call). It still abstains and still ledgers a row, but emits no card.
    """

    OUT_OF_GRAPH = "out-of-graph"
    UNCITED = "uncited"
    UNGROUNDED = "ungrounded"

    @property
    def emits_card(self) -> bool:
        """Whether this trigger warrants the ``NoRecordCard``."""
        return self is not AbstentionTrigger.UNGROUNDED


@dataclass(frozen=True, slots=True)
class CameClose:
    """One real decision the search reached but that did not answer the question."""

    id: str
    label: str
    title: str


@dataclass(frozen=True, slots=True)
class AbstentionReceipt:
    """One abstention: the NoRecordCard payload plus the trigger that caused it."""

    nodes_searched: int
    evidence_chains: int
    matches: int
    came_close: tuple[CameClose, ...]
    trigger: AbstentionTrigger


def record_abstention(
    question: str,
    retrieval: RetrievalResult,
    *,
    trigger: AbstentionTrigger,
    claims_cited: int,
) -> AbstentionReceipt:
    """Compile and ledger the receipts for one abstention.

    ``nodes_searched`` is the candidate evidence count; ``evidence_chains`` is
    the number of traversed (non-seed) query-path steps; ``matches`` is the
    cited-claim count; ``came_close`` is the ranked seed-Decision trail. The
    ledger row is named ``abstention:<trigger>``.
    """
    receipt = AbstentionReceipt(
        nodes_searched=retrieval.candidate_count,
        evidence_chains=sum(
            1 for step in retrieval.query_path if step.relation not in SEED_RELATIONS
        ),
        matches=claims_cited,
        came_close=_came_close(retrieval.evidence_nodes),
        trigger=trigger,
    )
    _append_abstention_ledger(question, receipt.matches, trigger)
    return receipt


def _came_close(nodes: Sequence[EvidenceNode]) -> tuple[CameClose, ...]:
    seeds = [
        node
        for node in nodes
        if node.label == "Decision" and node.source in _SEED_SOURCES
    ]
    ranked = sorted(seeds, key=lambda node: (-_normalized_relevance(node), node.id))
    return tuple(
        CameClose(id=node.id, label=node.label, title=node_title(node))
        for node in ranked[:CAME_CLOSE_LIMIT]
    )


def _normalized_relevance(node: EvidenceNode) -> float:
    """Seed relevance on one scale: a vector distance becomes cosine similarity."""
    score = node.score if node.score is not None else 0.0
    return 1.0 - score if node.source == "vector" else score


def _append_abstention_ledger(
    question: str, matches: int, trigger: AbstentionTrigger
) -> None:
    llm.ledger_append(
        llm.LedgerRecord(
            input_digest=hashlib.sha256(question.encode("utf-8")).hexdigest(),
            choice=matches,
            confidence=None,
            model=f"abstention:{trigger.value}",
            latency_ms=0,
            cost_usd=0.0,
            escalated=False,
        )
    )
