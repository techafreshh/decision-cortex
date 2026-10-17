"""Portable exports (``POST /exports/report``, ``POST /exports/graph``, PRD §10).

``render_report`` emits a Markdown report for either a single graph node (its
source block, stored properties, and compact impact section) or a cached
scripted scenario (the answer plan's route, sentence-by-sentence citations, and
abstention receipt). ``render_graph`` returns the impact payload for download.

Both are pure reads: a scenario report replays :data:`api.cache.cache` and a
node report reads the graph — neither calls an LLM, so exports cost nothing.
An unknown node is a ``404``, an unknown scenario name a ``400``, and a
scenario that has not been computed yet a ``409`` (run it in the UI first), so a
download can never silently fabricate an answer.
"""

from __future__ import annotations

import json
from typing import Any

from api.answer import SCENARIOS, AnswerPlan
from api.cache import cache
from api.impact import IMPACT_MAX_DEPTH, build_impact
from api.nodes import node_detail, source_block
from api.retrieval import GraphReader, display_name, node_title

_SOURCE_LABELS = (
    ("url", "url"),
    ("author", "author"),
    ("date", "date"),
    ("stance", "stance"),
    ("truncated", "truncated"),
)


class ExportError(Exception):
    """A failed export carrying the HTTP status the endpoint should return."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def render_report(
    reader: GraphReader,
    *,
    node_id: str | None = None,
    scenario: str | None = None,
) -> str:
    """Render the Markdown report for ``node_id`` or a cached ``scenario``."""
    if node_id is not None:
        detail = node_detail(reader, node_id)
        if detail is None:
            raise ExportError(404, f"no node with id {node_id!r}")
        return _render_node_report(reader, detail)
    if scenario is not None:
        if scenario not in SCENARIOS:
            raise ExportError(400, f"unknown scenario {scenario!r}")
        plan = cache.get(scenario)
        if plan is None:
            raise ExportError(
                409, f"scenario {scenario!r} has not been computed; run it in the UI first"
            )
        return _render_scenario_report(scenario, plan)
    raise ExportError(400, "provide either node_id or scenario")


def render_graph(
    reader: GraphReader, node_id: str, *, depth: int = IMPACT_MAX_DEPTH
) -> dict[str, Any]:
    """Return the impact subgraph around ``node_id`` for download."""
    impact = build_impact(reader, node_id, depth=depth)
    if impact is None:
        raise ExportError(404, f"no node with id {node_id!r}")
    return impact


def export_filename(*, node_id: str | None = None, scenario: str | None = None, suffix: str) -> str:
    """A filesystem-safe download name for the export."""
    stem = (node_id or scenario or "export").replace(":", "-").replace("/", "-")
    return f"{stem}.{suffix}"


def _render_node_report(reader: GraphReader, detail: dict[str, Any]) -> str:
    node_id = detail["id"]
    label = detail["label"]
    properties = detail["properties"]
    source = detail["source"]
    title = display_name(label, properties) or node_id
    lines = [f"# {label} {node_id}: {title}", "", "## Source", ""]
    for key, text in _SOURCE_LABELS:
        lines.append(f"- {text}: {_format_value(source.get(key))}")
    lines.extend(["", "## Properties", ""])
    for key in sorted(properties):
        lines.append(f"- {key}: {_format_value(properties[key])}")
    impact = build_impact(reader, node_id)
    lines.extend(["", f"## Impact (depth {IMPACT_MAX_DEPTH})", ""])
    if impact is None:
        lines.append("- no impact subgraph")
    else:
        lines.append(f"- nodes: {len(impact['nodes'])}")
        lines.append(f"- edges: {len(impact['edges'])}")
        lines.append(f"- evidence types: {', '.join(impact['evidence_types']) or 'none'}")
        lines.append(f"- truncated: {'yes' if impact['truncated'] else 'no'}")
    lines.append("")
    return "\n".join(lines)


def _render_scenario_report(scenario: str, plan: AnswerPlan) -> str:
    node_by_id = {node.id: node for node in plan.evidence_nodes}
    lines = [
        f"# Scenario: {scenario}",
        "",
        f"Question: {SCENARIOS[scenario]}",
        "",
        f"Route: {plan.route} (confidence {_format_value(plan.route_confidence)})",
        "",
        "## Answer",
        "",
    ]
    if not plan.verdicts:
        lines.append("- (no sentences; out-of-graph route)")
    for verdict in plan.verdicts:
        marker = "cited" if verdict.cited else "uncited"
        lines.append(f"- [{marker}] {verdict.sentence}")
        for evidence_id in verdict.evidence_ids:
            node = node_by_id.get(evidence_id)
            if node is None:
                continue
            url = source_block(node.label, node.properties).get("url")
            suffix = f" ({url})" if url else ""
            lines.append(f"  - {node.label} {node.id}: {node_title(node)}{suffix}")
    if plan.abstention is not None:
        receipt = plan.abstention
        lines.extend(["", "## Abstention", ""])
        lines.append(f"- nodes searched: {receipt.nodes_searched}")
        lines.append(f"- evidence chains: {receipt.evidence_chains}")
        lines.append(f"- matches: {receipt.matches}")
        for entry in receipt.came_close:
            lines.append(f"  - came close: {entry.label} {entry.id}: {entry.title}")
    lines.append("")
    return "\n".join(lines)


def _format_value(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, ensure_ascii=False)
