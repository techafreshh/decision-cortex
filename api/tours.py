"""Curated lifecycle tours over the graph (``GET /timeline?tour=async_await``).

A tour is a hand-picked spine of real RFC numbers that tells one decision story
in order — here, Rust's road to async/await. The spine (:data:`ASYNC_AWAIT_TOUR`)
carries only the curation (RFC number, lifecycle ``role``, one-line
``narrative``); every factual field (title, status, dates) is resolved from the
graph at request time by :func:`build_tour`, so the served tour cannot drift
from the corpus. A stage whose RFC is not in the loaded graph is dropped, never
fabricated.

``test_tour.py`` pins the spine to ``snapshot/rfcs.jsonl``: every RFC number
must exist, the spine must be chronological, and the lifecycle must read as the
real history (early rejections → eRFC → landing → stabilization → extensions).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from api.retrieval import GraphReader, coerce_node

#: Wire keys — bound to ``web/src/api/types.ts`` by ``test_wire_contract.py``.
TOUR_KEYS = ("tour", "stages", "transitions")
TOUR_STAGE_KEYS = (
    "id",
    "rfc",
    "title",
    "status",
    "proposed_on",
    "decided_on",
    "role",
    "narrative",
)
TOUR_TRANSITION_KEYS = ("from", "to", "label")

_TOUR_NODE_QUERY = "MATCH (d:Decision {id: $id}) RETURN d"


@dataclass(frozen=True, slots=True)
class TourStage:
    """One curated step: the RFC, its lifecycle role, and the one-line story."""

    rfc: int
    role: str
    narrative: str


#: The async/await spine, chronological by ``proposed_on``. Roles read as the
#: lifecycle: rejected early attempts, the experimental eRFC, the landed
#: notation, stabilization, then later extensions.
ASYNC_AWAIT_TOUR: tuple[TourStage, ...] = (
    TourStage(53, "first-attempt", "Coroutines proposed and rejected before async existed."),
    TourStage(1083, "keyword-proposal", "An attempt to reserve the async and await keywords, rejected."),
    TourStage(1823, "syntax-proposal", "Stackless coroutines proposed; the syntax debate continued."),
    TourStage(2033, "experimental-rfc", "The eRFC that experimentally added coroutines to Rust."),
    TourStage(2394, "syntax-landed", "The async/await notation that landed the ergonomic syntax."),
    TourStage(2592, "runtime-stabilized", "Stabilizing std::task and Future as the runtime foundation."),
    TourStage(2932, "doc-refined", "A documentation update to the landed async/await RFC."),
    TourStage(3083, "update-rejected", "An update to the coroutines eRFC, rejected as not-RFC."),
    TourStage(3185, "traits-extended", "Static async fn in traits extends async to trait methods."),
    TourStage(3668, "closures-landed", "Async closures, the latest chapter in the async story."),
)

#: Registered tours by name; the timeline advertises these keys.
TOURS: dict[str, tuple[TourStage, ...]] = {"async_await": ASYNC_AWAIT_TOUR}


def build_tour(reader: GraphReader, name: str) -> dict[str, Any] | None:
    """Resolve the named tour against the graph, or ``None`` when unknown.

    Stages whose RFC is absent from the graph are dropped. ``transitions``
    connect consecutive surviving stages and are labelled by the arriving
    stage's lifecycle ``role`` (the story is lifecycle, not ``SUPERSEDES``).
    """
    stages = TOURS.get(name)
    if stages is None:
        return None
    resolved: list[dict[str, Any]] = []
    for stage in stages:
        node_id = f"rfc:{stage.rfc}"
        rows = reader.query(_TOUR_NODE_QUERY, {"id": node_id})
        if not rows:
            continue
        _, _, properties = coerce_node(rows[0][0])
        resolved.append(
            {
                "id": node_id,
                "rfc": properties.get("rfc", stage.rfc),
                "title": str(properties.get("title") or node_id),
                "status": properties.get("status"),
                "proposed_on": _as_text(properties.get("proposed_on")),
                "decided_on": _as_text(properties.get("decided_on")),
                "role": stage.role,
                "narrative": stage.narrative,
            }
        )
    transitions = [
        {
            "from": resolved[index]["id"],
            "to": resolved[index + 1]["id"],
            "label": resolved[index + 1]["role"],
        }
        for index in range(len(resolved) - 1)
    ]
    return {"tour": name, "stages": resolved, "transitions": transitions}


def _as_text(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None
