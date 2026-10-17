"""The answer pipeline and the ``POST /ask`` event stream.

``answer_question`` composes the graph primitives into one answer plan: the S1
router classifies the question, retrieval gathers evidence, S2 synthesis emits
the answer sentence by sentence, and the S1 claim gate maps each sentence to
the evidence that supports it. An ``out-of-graph`` route short-circuits before
synthesis, so it produces no text and always requires abstention.

``ask_events`` renders a plan as the frozen AG-UI event sequence
(:mod:`api.events`) for ``POST /ask``. Scripted scenarios are served from
:data:`api.cache.cache`: a cache hit replays the stored plan's tool-call and
text events and emits a fresh ledger summary, so the second call issues zero
S2 calls. Free questions always run live. #8 only sets
``abstention_required`` and flags uncited sentences; the abstention receipts
are #9's.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from api import events, llm
from api.cache import cache
from api.claim_gate import ClaimVerdict, claim_gate
from api.retrieval import (
    EvidenceNode,
    GraphReader,
    RetrievalResult,
    node_title,
    retrieve_evidence,
)
from api.router import Route, RouterResult, router_classify
from api.synthesis import synthesize

#: The four PRD §10 scripted scenarios and the question each one asks. The
#: questions are the PRD user stories U1–U3 plus the RFC 2394 gold question.
SCENARIOS: dict[str, str] = {
    "ask_corpus": (
        "What did the language team decide about trait objects, and who objected?"
    ),
    "prove_negative": (
        "Did Rust ever decide to require attachments in `unsafe` code?"
    ),
    "impact_tour": "What does the async/await decision touch?",
    "async_story": (
        "Which RFC introduced the `async`/`await` syntax for ergonomic "
        "asynchronous IO?"
    ),
}

_MESSAGE_ID = "answer"


class _DecideFn(Protocol):
    """The ``decide`` seam, shared by the router, retrieval, and gate."""

    def __call__(
        self,
        prompt: str,
        *,
        one_of: Sequence[str] | None = None,
        rating: tuple[int, int] | None = None,
        yes_no: bool | None = None,
    ) -> llm.DecideResult[str | int | bool]: ...


class _ReasonFn(Protocol):
    """The S2 ``reason`` seam; injected so tests never hit the network."""

    def __call__(self, prompt: str) -> str: ...


class _Embedder(Protocol):
    def __call__(self, text: str) -> llm.EmbeddingResult: ...


@dataclass(frozen=True, slots=True)
class AnswerPlan:
    """Everything one answer produced, enough to render or replay its events."""

    route: str
    route_confidence: float
    route_escalated: bool
    candidate_count: int
    rounds: int
    stopped_early: bool
    queries: tuple[str, ...]
    evidence_nodes: tuple[EvidenceNode, ...]
    sentences: tuple[str, ...]
    verdicts: tuple[ClaimVerdict, ...]
    citation_count: int
    claims_total: int
    claims_cited: int
    abstention_required: bool


def answer_question(
    question: str,
    *,
    reader: GraphReader | None = None,
    embedder: _Embedder | None = None,
    decide_fn: _DecideFn = llm.decide,
    reason_fn: _ReasonFn = llm.reason,
) -> AnswerPlan:
    """Run the full pipeline for ``question`` and return its plan."""
    route = router_classify(question, decide_fn=decide_fn)
    retrieval = retrieve_evidence(
        question,
        route.label,
        reader=reader,
        embedder=embedder,
        decide_fn=decide_fn,
    )
    if route.label == Route.OUT_OF_GRAPH:
        return _plan_without_text(route, retrieval)

    synthesis = synthesize(
        question, route.label, retrieval.evidence_nodes, reason_fn=reason_fn
    )
    verdicts = tuple(
        claim_gate(sentence, retrieval.evidence_nodes, decide_fn=decide_fn)
        for sentence in synthesis.sentences
    )
    claims_total = len(verdicts)
    claims_cited = sum(1 for verdict in verdicts if verdict.cited)
    citation_count = sum(len(verdict.evidence_ids) for verdict in verdicts)
    return AnswerPlan(
        route=route.label.value,
        route_confidence=route.confidence,
        route_escalated=route.escalated,
        candidate_count=retrieval.candidate_count,
        rounds=retrieval.rounds,
        stopped_early=retrieval.stopped_early,
        queries=retrieval.cypher,
        evidence_nodes=retrieval.evidence_nodes,
        sentences=synthesis.sentences,
        verdicts=verdicts,
        citation_count=citation_count,
        claims_total=claims_total,
        claims_cited=claims_cited,
        abstention_required=claims_cited < claims_total,
    )


def ask_events(
    question: str | None,
    scenario: str | None = None,
    *,
    reader: GraphReader | None = None,
    embedder: _Embedder | None = None,
    decide_fn: _DecideFn = llm.decide,
    reason_fn: _ReasonFn = llm.reason,
) -> Iterator[dict[str, Any]]:
    """Yield the AG-UI event stream for one ``POST /ask`` request."""
    before = _ledger_snapshot()
    resolved_question = SCENARIOS[scenario] if scenario is not None else (question or "")
    yield _event(
        events.RUN_STARTED, question=resolved_question, scenario=scenario
    )

    plan = cache.get(scenario) if scenario is not None else None
    if plan is None:
        plan = answer_question(
            resolved_question,
            reader=reader,
            embedder=embedder,
            decide_fn=decide_fn,
            reason_fn=reason_fn,
        )
        if scenario is not None:
            cache.put(scenario, plan)

    yield from _plan_events(plan)
    ledger = _ledger_delta(before)
    yield _event(events.LEDGER_UPDATE, ledger=ledger)
    yield _event(
        events.RUN_FINISHED,
        citation_count=plan.citation_count,
        claims_total=plan.claims_total,
        claims_cited=plan.claims_cited,
        abstention_required=plan.abstention_required,
        ledger=ledger,
    )


def _plan_without_text(route: RouterResult, retrieval: RetrievalResult) -> AnswerPlan:
    """The ``out-of-graph`` plan: evidence for receipts, but no synthesized text."""
    return AnswerPlan(
        route=route.label.value,
        route_confidence=route.confidence,
        route_escalated=route.escalated,
        candidate_count=retrieval.candidate_count,
        rounds=retrieval.rounds,
        stopped_early=retrieval.stopped_early,
        queries=retrieval.cypher,
        evidence_nodes=retrieval.evidence_nodes,
        sentences=(),
        verdicts=(),
        citation_count=0,
        claims_total=0,
        claims_cited=0,
        abstention_required=True,
    )


def _plan_events(plan: AnswerPlan) -> Iterator[dict[str, Any]]:
    """Render a plan's tool-call, Cypher, text, and faithfulness events."""
    node_by_id = {node.id: node for node in plan.evidence_nodes}
    yield from _tool_call(
        "router_classify",
        {"route": plan.route},
        {
            "route": plan.route,
            "confidence": plan.route_confidence,
            "escalated": plan.route_escalated,
        },
    )
    yield from _tool_call(
        "retrieve_evidence",
        {"route": plan.route},
        {
            "candidate_count": plan.candidate_count,
            "rounds": plan.rounds,
            "stopped_early": plan.stopped_early,
        },
    )
    yield _event(events.CYPHER_PREVIEW, queries=list(plan.queries))
    if plan.route != Route.OUT_OF_GRAPH:
        yield from _tool_call(
            "synthesize", {"route": plan.route}, {"sentences": len(plan.sentences)}
        )
        yield from _tool_call(
            "claim_gate",
            {"sentences": len(plan.sentences)},
            {"verdicts": [_verdict_payload(verdict) for verdict in plan.verdicts]},
        )
    yield _event(events.TEXT_MESSAGE_START, message_id=_MESSAGE_ID)
    for verdict in plan.verdicts:
        chips = [
            _chip(node_by_id[node_id])
            for node_id in verdict.evidence_ids
            if node_id in node_by_id
        ]
        yield _event(
            events.TEXT_MESSAGE_CONTENT,
            message_id=_MESSAGE_ID,
            delta=verdict.sentence,
            chips=chips,
            cited=verdict.cited,
        )
    yield _event(events.TEXT_MESSAGE_END, message_id=_MESSAGE_ID)
    yield _event(events.FAITHFULNESS_PENDING)


def _tool_call(
    tool_name: str, args: dict[str, Any], result: dict[str, Any]
) -> Iterator[dict[str, Any]]:
    yield _event(events.TOOL_CALL_START, tool_call_id=tool_name, tool_name=tool_name)
    yield _event(
        events.TOOL_CALL_ARGS,
        tool_call_id=tool_name,
        delta=json.dumps(args, separators=(",", ":")),
    )
    yield _event(events.TOOL_CALL_END, tool_call_id=tool_name)
    yield _event(events.TOOL_CALL_RESULT, tool_call_id=tool_name, result=result)


def _chip(node: EvidenceNode) -> dict[str, Any]:
    return {"id": node.id, "label": node.label, "title": node_title(node)}


def _verdict_payload(verdict: ClaimVerdict) -> dict[str, Any]:
    return {
        "sentence": verdict.sentence,
        "cited": verdict.cited,
        "confidence": verdict.confidence,
        "evidence_ids": list(verdict.evidence_ids),
    }


def _event(event_type: str, **fields: Any) -> dict[str, Any]:
    return {"type": event_type, **fields}


@dataclass(frozen=True, slots=True)
class _LedgerSnapshot:
    calls: int
    cost_usd: float


def _ledger_snapshot() -> _LedgerSnapshot:
    records = llm.ledger_records()
    return _LedgerSnapshot(
        calls=len(records), cost_usd=sum(record.cost_usd for record in records)
    )


def _ledger_delta(before: _LedgerSnapshot) -> dict[str, Any]:
    after = _ledger_snapshot()
    return {
        "calls": after.calls - before.calls,
        "cost_usd": round(after.cost_usd - before.cost_usd, 6),
        "total_calls": after.calls,
        "total_cost_usd": round(after.cost_usd, 6),
    }
