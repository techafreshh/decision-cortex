"""Graph-native evidence retrieval and the System-1 recall-sufficiency stop.

``retrieve_evidence`` seeds candidate Decisions from two FalkorDB indexes — a
vector index over committed ``Decision.embedding`` values and a full-text index
over ``Decision.title`` — then walks the PRD §15.3 relations out of the seeds,
one bounded hop per round, recording every seed and traversed edge as the query
path. After each expansion round it asks ``sufficiency_stop`` whether the
evidence gathered so far is enough; a ``True`` ends the walk early.

The vector seed is optional: when no embedder is configured (no
``OPENROUTER_API_KEY``, which is how CI runs) retrieval degrades to full-text
plus traversal, so the real FalkorDB path is exercised with zero LLM calls.

``sufficiency_stop`` is a System-1 ``decide()`` gate over concrete retrieval
facts (candidate and decision counts, traversed relation counts, the best seed
score, and the expansion round) — not a hard-coded count — so the graph shapes
the stop the way PRD §6.2 requires. Its own ``decide()`` call lands in the
ledger; ``retrieve_evidence`` appends one more row carrying the embedding
call's cost/latency and the candidate count.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from api import llm

#: Outgoing §15.3 relations that start at a Decision. ``api`` ships without
#: ``ingest`` (the wheel packages ``api`` only), so this cannot be derived from
#: ``ontology.SCHEMA`` at runtime; ``test_retrieval_relations_match_the_schema``
#: pins it to the canonical schema instead.
_OUT_RELATIONS = (
    "EVIDENCED_BY",
    "PROPOSED_BY",
    "ABOUT",
    "ASSOCIATED_TEAM",
    "AREA",
    "HAS_VERSION",
    "SUPERSEDES",
)
#: §15.3 relations whose target is the Decision (stance edges plus supersession).
_IN_RELATIONS = ("OBJECTED", "SUPPORTED", "MODERATED", "SUPERSEDES")
#: Query-path relations marking a seed node rather than a traversed §15.3 edge.
SEED_RELATIONS = ("SEED_VECTOR", "SEED_FULLTEXT")

_OUT_QUERY = (
    "MATCH (d:Decision)-[r]->(n) "
    "WHERE d.id IN $ids AND type(r) IN $rels "
    "RETURN d.id, type(r), n"
)
_IN_QUERY = (
    "MATCH (n)-[r]->(d:Decision) "
    "WHERE d.id IN $ids AND type(r) IN $rels "
    "RETURN n, type(r), d.id"
)
_VECTOR_QUERY = (
    "CALL db.idx.vector.queryNodes('Decision','embedding',$k,vecf32($vector)) "
    "YIELD node, score RETURN node, score"
)
_FULLTEXT_QUERY = (
    "CALL db.idx.fulltext.queryNodes('Decision',$q) "
    "YIELD node, score RETURN node, score"
)

#: Substrings that mean the vector index (or its property) is not there yet.
_MISSING_INDEX_HINTS = (
    "undefined attribute",
    "no such index",
    "index not found",
    "does not exist",
)

_WORD_RE = re.compile(r"\w+")

#: Common English words dropped from the full-text seed. The index does not
#: ignore them, so leaving them in would OR-match unrelated titles on "the"
#: and "and" and crowd out the content words that carry the question.
_STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "but", "by", "did", "do",
        "does", "for", "from", "had", "has", "have", "how", "in", "is", "it",
        "its", "of", "on", "or", "that", "the", "their", "then", "there",
        "these", "they", "this", "to", "was", "were", "what", "when", "where",
        "which", "who", "why", "will", "with",
    }
)

DEFAULT_MAX_ROUNDS = 2
DEFAULT_TOP_K = 5

_RETRIEVAL_MODEL = "retrieval:graph-native"

#: Per-option descriptions for the sufficiency gate's Decisions lane: the
#: criterion *is* the stop rule, so the typed question self-describes.
SUFFICIENCY_CRITERIA = {
    "true": "Evidence gathered is sufficient to answer — stop expanding.",
    "false": "One more traversal hop is likely to add evidence the answer needs.",
}


class GraphReader(Protocol):
    """The FalkorDB read seam; tests inject a fake returning plain rows."""

    def query(
        self, cypher: str, params: Mapping[str, Any] | None = None
    ) -> list[list[Any]]: ...


@dataclass(frozen=True, slots=True)
class EvidenceNode:
    """One candidate node: how it was found and (for seeds) its score."""

    id: str
    label: str
    properties: Mapping[str, Any]
    source: str
    score: float | None


#: Each label's human-readable display property. The graph schema declares a
#: different property per label (``Person.handle``, ``Commit.message``,
#: ``DocVersion.content_ref``, …), so a fixed ``title``/``name`` lookup would
#: show the raw id for most non-``Decision`` nodes. ``Message`` has no text
#: property, only the ``text_ref`` permalink, so that is its display value.
#: ``test_node_title_properties_match_the_schema`` pins this to the schema.
_DISPLAY_PROPERTIES: dict[str, str] = {
    "Decision": "title",
    "Issue": "title",
    "Person": "handle",
    "Team": "name",
    "Area": "name",
    "Concept": "name",
    "Commit": "message",
    "DocVersion": "content_ref",
    "Message": "text_ref",
}


def display_name(label: str, properties: Mapping[str, Any]) -> str:
    """The display property for ``label``, or ``""`` when the node has none.

    The graph schema declares a different display property per label
    (:data:`_DISPLAY_PROPERTIES`); callers that hold a label and properties but
    not an :class:`EvidenceNode` (e.g. the impact walk) share this lookup.
    """
    property_name = _DISPLAY_PROPERTIES.get(label)
    value = properties.get(property_name) if property_name else None
    return str(value) if value else ""


def node_title(node: EvidenceNode) -> str:
    """The node's human-readable title, falling back to its id."""
    return display_name(node.label, node.properties) or node.id


def evidence_line(node: EvidenceNode) -> str:
    """One prompt/chip line for a node: ``Label id: title``."""
    return f"{node.label} {node.id}: {node_title(node)}"


@dataclass(frozen=True, slots=True)
class QueryStep:
    """One traversed edge (or seed) on the query path."""

    src: str
    relation: str
    dst: str


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    evidence_nodes: tuple[EvidenceNode, ...]
    query_path: tuple[QueryStep, ...]
    candidate_count: int
    rounds: int
    stopped_early: bool
    #: The Cypher strings actually executed, in order — the honest source for
    #: CypherPeek, not a reconstruction from ``query_path``.
    cypher: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SufficiencyFacts:
    """The concrete retrieval facts the System-1 sufficiency gate judges."""

    question: str
    route: str
    candidate_count: int
    decision_count: int
    evidence_type_counts: Mapping[str, int]
    top_score: float | None
    seed_count: int
    round_index: int
    max_rounds: int


class _DecideYesNo(Protocol):
    def __call__(
        self,
        prompt: str,
        *,
        yes_no: bool,
        criteria: Mapping[str, str] | None = None,
    ) -> llm.DecideResult[bool]: ...


class _Embedder(Protocol):
    def __call__(self, text: str) -> llm.EmbeddingResult: ...


class FalkorDBGraphReader:
    """Synchronous read seam over the FalkorDB graph named in the environment."""

    def __init__(self, *, host: str, port: int, graph_name: str) -> None:
        self._host = host
        self._port = port
        self._graph_name = graph_name
        self._graph: Any = None

    def _graph_handle(self) -> Any:
        if self._graph is None:
            from falkordb import FalkorDB

            self._graph = FalkorDB(host=self._host, port=self._port).select_graph(
                self._graph_name
            )
        return self._graph

    def query(
        self, cypher: str, params: Mapping[str, Any] | None = None
    ) -> list[list[Any]]:
        result = self._graph_handle().query(cypher, dict(params or {}))
        return [list(row) for row in result.result_set]


@dataclass(frozen=True, slots=True)
class FalkorDBConnection:
    """The FalkorDB endpoint resolved from the environment."""

    host: str
    port: int
    graph_name: str


def connection_from_env() -> FalkorDBConnection:
    """Resolve the endpoint from ``FALKORDB_HOST``/``FALKORDB_PORT``/``FALKORDB_GRAPH``.

    The single declaration of these defaults: ``ingest.graph`` imports this so
    the loader and the retrieval reader can never point at different graphs.
    """
    return FalkorDBConnection(
        host=os.environ.get("FALKORDB_HOST", "localhost"),
        port=int(os.environ.get("FALKORDB_PORT", "6379")),
        graph_name=os.environ.get("FALKORDB_GRAPH", "decision_cortex"),
    )


def connect_from_env() -> FalkorDBGraphReader:
    """Build a reader over the environment-resolved endpoint."""
    connection = connection_from_env()
    return FalkorDBGraphReader(
        host=connection.host, port=connection.port, graph_name=connection.graph_name
    )


def retrieve_evidence(
    question: str,
    route: str,
    *,
    reader: GraphReader | None = None,
    embedder: _Embedder | None = None,
    decide_fn: _DecideYesNo = llm.decide,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    top_k: int = DEFAULT_TOP_K,
) -> RetrievalResult:
    """Seed, then expand up to ``max_rounds`` hops until evidence suffices.

    ``embedder`` defaults to :func:`api.llm.embed_query` when
    ``OPENROUTER_API_KEY`` is set and to ``None`` otherwise, so CI runs
    full-text-only with zero LLM calls.
    """
    active_reader = reader or connect_from_env()
    active_embedder = _resolve_embedder(embedder)

    evidence: dict[str, EvidenceNode] = {}
    path: list[QueryStep] = []
    queries: list[str] = []
    embed_latency_ms = 0
    embed_cost_usd = 0.0

    if active_embedder is not None:
        trace = active_embedder(question)
        embed_latency_ms = trace.latency_ms
        embed_cost_usd = trace.cost_usd
        queries.append(_VECTOR_QUERY)
        for node in _vector_seed(active_reader, trace.vector, top_k):
            if node.id not in evidence:
                evidence[node.id] = node
                path.append(QueryStep("query", "SEED_VECTOR", node.id))

    fulltext_terms = _fulltext_terms(question)
    if fulltext_terms:
        queries.append(_FULLTEXT_QUERY)
    for node in _fulltext_seed(active_reader, fulltext_terms, top_k):
        if node.id not in evidence:
            evidence[node.id] = node
            path.append(QueryStep("query", "SEED_FULLTEXT", node.id))

    frontier = [node.id for node in evidence.values() if node.label == "Decision"]
    rounds = 0
    stopped_early = False
    for round_index in range(1, max_rounds + 1):
        if not frontier:
            break
        queries.append(_OUT_QUERY)
        queries.append(_IN_QUERY)
        new_nodes, new_steps, next_frontier = _expand(active_reader, frontier)
        for node in new_nodes:
            evidence.setdefault(node.id, node)
        path.extend(new_steps)
        rounds = round_index
        frontier = next_frontier
        if sufficiency_stop(
            _sufficiency_facts(question, route, evidence, path, round_index, max_rounds),
            decide_fn=decide_fn,
        ):
            stopped_early = True
            break

    _append_retrieval_ledger(question, len(evidence), embed_latency_ms, embed_cost_usd)
    return RetrievalResult(
        evidence_nodes=tuple(sorted(evidence.values(), key=lambda node: node.id)),
        query_path=tuple(path),
        candidate_count=len(evidence),
        rounds=rounds,
        stopped_early=stopped_early,
        cypher=tuple(queries),
    )


def sufficiency_stop(
    facts: SufficiencyFacts, *, decide_fn: _DecideYesNo = llm.decide
) -> bool:
    """Ask the S1 model whether the gathered evidence is sufficient (yes/no)."""
    result = decide_fn(
        _sufficiency_prompt(facts),
        yes_no=True,
        criteria=SUFFICIENCY_CRITERIA,
    )
    return bool(result.choice)


def _resolve_embedder(embedder: _Embedder | None) -> _Embedder | None:
    if embedder is not None:
        return embedder
    if os.environ.get("OPENROUTER_API_KEY", "").strip():
        return llm.embed_query
    return None


def _vector_seed(
    reader: GraphReader, query_vector: Sequence[float], top_k: int
) -> list[EvidenceNode]:
    """Vector-index seed; an absent index is an empty seed, not an error."""
    try:
        rows = reader.query(_VECTOR_QUERY, {"k": top_k, "vector": list(query_vector)})
    except Exception as exc:
        if _is_missing_index_error(exc):
            return []
        raise
    return [
        _evidence_from_row(row, source="vector", score=_as_float(row[1])) for row in rows
    ]


def _fulltext_seed(
    reader: GraphReader, terms: Sequence[str], top_k: int
) -> list[EvidenceNode]:
    """Full-text seed over ``Decision.title``; terms are OR-ed so any match counts."""
    if not terms:
        return []
    rows = reader.query(_FULLTEXT_QUERY, {"q": "|".join(terms)})
    ranked = sorted(rows, key=lambda row: _as_float(row[1]) or 0.0, reverse=True)
    return [
        _evidence_from_row(row, source="fulltext", score=_as_float(row[1]))
        for row in ranked[:top_k]
    ]


def _expand(
    reader: GraphReader, decision_ids: Sequence[str]
) -> tuple[list[EvidenceNode], list[QueryStep], list[str]]:
    """One hop out of ``decision_ids``; returns nodes, steps, and new Decisions."""
    nodes: dict[str, EvidenceNode] = {}
    steps: list[QueryStep] = []
    next_decisions: set[str] = set()

    out_rows = reader.query(
        _OUT_QUERY, {"ids": list(decision_ids), "rels": list(_OUT_RELATIONS)}
    )
    for src, relation, value in out_rows:
        node = _traversal_node(nodes, value)
        steps.append(QueryStep(src=str(src), relation=str(relation), dst=node.id))
        if node.label == "Decision":
            next_decisions.add(node.id)

    in_rows = reader.query(
        _IN_QUERY, {"ids": list(decision_ids), "rels": list(_IN_RELATIONS)}
    )
    for value, relation, dst in in_rows:
        node = _traversal_node(nodes, value)
        steps.append(QueryStep(src=node.id, relation=str(relation), dst=str(dst)))
        if node.label == "Decision":
            next_decisions.add(node.id)

    return list(nodes.values()), steps, sorted(next_decisions)


def _traversal_node(nodes: dict[str, EvidenceNode], value: Any) -> EvidenceNode:
    node_id, label, properties = coerce_node(value)
    existing = nodes.get(node_id)
    if existing is not None:
        return existing
    node = EvidenceNode(
        id=node_id, label=label, properties=properties, source="traversal", score=None
    )
    nodes[node_id] = node
    return node


def _evidence_from_row(row: Sequence[Any], *, source: str, score: float | None) -> EvidenceNode:
    node_id, label, properties = coerce_node(row[0])
    return EvidenceNode(
        id=node_id, label=label, properties=properties, source=source, score=score
    )


def coerce_node(value: Any) -> tuple[str, str, dict[str, Any]]:
    """Return ``(id, label, properties)`` for a driver Node or a test mapping."""
    if isinstance(value, Mapping):
        properties = dict(value.get("properties", value))
        node_id = value.get("id") or properties.get("id")
        label = value.get("label")
        if label is None:
            labels = value.get("labels") or []
            label = labels[0] if labels else ""
        return str(node_id), str(label), properties
    properties = dict(getattr(value, "properties", {}) or {})
    node_id = properties.get("id")
    labels = list(getattr(value, "labels", []) or [])
    return str(node_id), (labels[0] if labels else ""), properties


def _fulltext_terms(question: str) -> list[str]:
    """Distinct content-word tokens, OR-joined; the full-text index does the matching."""
    seen: dict[str, None] = {}
    for token in _WORD_RE.findall(question.lower()):
        if len(token) > 1 and token not in _STOPWORDS:
            seen.setdefault(token, None)
    return list(seen)


def _sufficiency_facts(
    question: str,
    route: str,
    evidence: Mapping[str, EvidenceNode],
    path: Sequence[QueryStep],
    round_index: int,
    max_rounds: int,
) -> SufficiencyFacts:
    return SufficiencyFacts(
        question=question,
        route=route,
        candidate_count=len(evidence),
        decision_count=sum(1 for node in evidence.values() if node.label == "Decision"),
        evidence_type_counts=_relation_counts(path),
        top_score=_top_seed_score(evidence),
        seed_count=sum(1 for step in path if step.relation in SEED_RELATIONS),
        round_index=round_index,
        max_rounds=max_rounds,
    )


def _relation_counts(path: Sequence[QueryStep]) -> dict[str, int]:
    counts = Counter(step.relation for step in path if step.relation not in SEED_RELATIONS)
    return dict(sorted(counts.items()))


def _top_seed_score(evidence: Mapping[str, EvidenceNode]) -> float | None:
    """Best seed score; vector distances are converted to cosine similarity."""
    scores = [
        (1.0 - node.score if node.source == "vector" else node.score)
        for node in evidence.values()
        if node.source in ("vector", "fulltext") and node.score is not None
    ]
    return max(scores) if scores else None


def _sufficiency_prompt(facts: SufficiencyFacts) -> str:
    return (
        "You decide whether graph retrieval over the rust-lang/rfcs decision "
        "corpus has gathered enough evidence to answer a question, or whether "
        "one more traversal hop is likely to add evidence the answer needs.\n"
        "Answer yes if the evidence is sufficient (stop expanding), no if "
        "retrieval should expand further.\n"
        f"Question: {facts.question}\n"
        f"Route: {facts.route}\n"
        f"Expansion round: {facts.round_index} of {facts.max_rounds}\n"
        f"Seed candidates: {facts.seed_count}\n"
        f"Evidence nodes: {facts.candidate_count} "
        f"({facts.decision_count} decisions)\n"
        f"Traversed relations: {facts.evidence_type_counts or 'none'}\n"
        f"Best seed score: {facts.top_score if facts.top_score is not None else 'none'}\n"
    )


def _append_retrieval_ledger(
    question: str, candidate_count: int, latency_ms: int, cost_usd: float
) -> None:
    llm.ledger_append(
        llm.LedgerRecord(
            input_digest=hashlib.sha256(question.encode("utf-8")).hexdigest(),
            choice=candidate_count,
            confidence=None,
            model=_RETRIEVAL_MODEL,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
            escalated=False,
        )
    )


def _is_missing_index_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(hint in message for hint in _MISSING_INDEX_HINTS)


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None
