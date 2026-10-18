"""Decision timeline builder (``GET /timeline``, PRD §7.1/§7.2).

Flattens the graph's ``Decision`` nodes into a chronological list — status,
dates, the areas and teams each decision touches, its ``SUPERSEDES`` chain, and
the stance edges (``OBJECTED``/``SUPPORTED``/``MODERATED``) pointing at it — plus
the deduped supersession edges and the distinct area/team filter values. The
list is filterable by ``area``/``team`` and always advertises the registered
tours (:mod:`api.tours`).

Every read is a bounded ``MATCH`` over the committed graph; no LLM is involved,
so the timeline is free to serve. The payload keys are bound to
``web/src/api/types.ts`` by ``test_wire_contract.py``.
"""

from __future__ import annotations

from typing import Any

from api.retrieval import GraphReader, coerce_node, display_name
from api.tours import TOURS

#: Wire keys — bound to ``web/src/api/types.ts`` by ``test_wire_contract.py``.
TIMELINE_KEYS = ("decisions", "supersede_edges", "areas", "teams", "tours")
TIMELINE_DECISION_KEYS = (
    "id",
    "rfc",
    "title",
    "status",
    "proposed_on",
    "decided_on",
    "areas",
    "teams",
    "supersedes",
    "superseded_by",
    "stances",
)
STANCE_KEYS = ("handle", "kind", "evidence", "confidence")
SUPERSEDE_EDGE_KEYS = ("src", "dst")

_DECISIONS_QUERY = "MATCH (d:Decision) RETURN d"
_DECISION_AREAS_QUERY = "MATCH (d:Decision)-[:AREA]->(a:Area) RETURN d.id, a.name"
_DECISION_TEAMS_QUERY = "MATCH (d:Decision)-[:ASSOCIATED_TEAM]->(t:Team) RETURN d.id, t.name"
_SUPERSEDE_QUERY = "MATCH (d:Decision)-[:SUPERSEDES]->(e:Decision) RETURN d.id, e.id"
_STANCE_QUERY = (
    "MATCH (p:Person)-[r:OBJECTED|SUPPORTED|MODERATED]->(d:Decision) "
    "RETURN d.id, p.handle, type(r), properties(r)"
)


def build_timeline(
    reader: GraphReader, *, area: str | None = None, team: str | None = None
) -> dict[str, Any]:
    """Return the chronological timeline, optionally filtered by area/team."""
    decisions: dict[str, dict[str, Any]] = {}
    for row in reader.query(_DECISIONS_QUERY):
        node_id, _, properties = coerce_node(row[0])
        decisions[node_id] = {
            "id": node_id,
            "rfc": properties.get("rfc"),
            "title": display_name("Decision", properties) or node_id,
            "status": properties.get("status"),
            "proposed_on": _as_text(properties.get("proposed_on")),
            "decided_on": _as_text(properties.get("decided_on")),
            "areas": [],
            "teams": [],
            "supersedes": [],
            "superseded_by": [],
            "stances": [],
        }

    areas_by_decision: dict[str, set[str]] = {}
    for decision_id, name in reader.query(_DECISION_AREAS_QUERY):
        areas_by_decision.setdefault(str(decision_id), set()).add(str(name))
    teams_by_decision: dict[str, set[str]] = {}
    for decision_id, name in reader.query(_DECISION_TEAMS_QUERY):
        teams_by_decision.setdefault(str(decision_id), set()).add(str(name))

    supersede_edges: list[dict[str, str]] = []
    for src, dst in reader.query(_SUPERSEDE_QUERY):
        src, dst = str(src), str(dst)
        supersede_edges.append({"src": src, "dst": dst})
        if src in decisions:
            decisions[src]["supersedes"].append(decisions[dst]["rfc"] if dst in decisions else dst)
        if dst in decisions:
            decisions[dst]["superseded_by"].append(
                decisions[src]["rfc"] if src in decisions else src
            )

    for decision_id, handle, kind, properties in reader.query(_STANCE_QUERY):
        decision = decisions.get(str(decision_id))
        if decision is None:
            continue
        decision["stances"].append(
            {
                "handle": str(handle),
                "kind": str(kind),
                "evidence": properties.get("evidence"),
                "confidence": _confidence(properties.get("confidence")),
            }
        )

    selected = {
        node_id: decision
        for node_id, decision in decisions.items()
        if _matches(node_id, areas_by_decision, teams_by_decision, area, team)
    }
    for node_id, decision in selected.items():
        decision["areas"] = sorted(areas_by_decision.get(node_id, set()))
        decision["teams"] = sorted(teams_by_decision.get(node_id, set()))
        decision["supersedes"].sort()
        decision["superseded_by"].sort()
        decision["stances"].sort(
            key=lambda stance: (
                stance["confidence"] is None,
                -(stance["confidence"] or 0.0),
                stance["handle"],
                stance["kind"],
            )
        )

    selected_ids = set(selected)
    edges = [
        edge
        for edge in supersede_edges
        if edge["src"] in selected_ids and edge["dst"] in selected_ids
    ]
    edges.sort(key=lambda edge: (edge["src"], edge["dst"]))
    ordered = sorted(selected.values(), key=_sort_key)
    return {
        "decisions": ordered,
        "supersede_edges": edges,
        "areas": sorted({name for values in areas_by_decision.values() for name in values}),
        "teams": sorted({name for values in teams_by_decision.values() for name in values}),
        "tours": sorted(TOURS),
    }


def _matches(
    node_id: str,
    areas: dict[str, set[str]],
    teams: dict[str, set[str]],
    area: str | None,
    team: str | None,
) -> bool:
    area_ok = area is None or area in areas.get(node_id, set())
    team_ok = team is None or team in teams.get(node_id, set())
    return area_ok and team_ok


def _sort_key(decision: dict[str, Any]) -> tuple[bool, str, Any]:
    date = decision["decided_on"] or decision["proposed_on"] or ""
    return (date == "", date, decision["rfc"] if decision["rfc"] is not None else 0)


def _as_text(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None


def _confidence(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
