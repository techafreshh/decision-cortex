"""Impact Explorer blast-radius walk (``GET /graph/impact/{node_id}``, PRD §7.1).

Given a seed node id, :func:`build_impact` walks the §15.3 entity relations
undirected, one bounded hop at a time (BFS), and returns the visited nodes with
their minimum distance from the seed plus every traversed edge. BFS — rather
than a single variable-length Cypher path match — is used so the walk is
bounded by :data:`IMPACT_NODE_CAP`: a depth-3 match over ``AREA`` fan-out would
materialise thousands of paths before Python could dedupe them, while the
hop-by-hop walk can stop the moment the cap is hit and flag ``truncated``.

The relation set is deliberately the *entity* relations. ``EVIDENCED_BY`` and
``HAS_VERSION`` lead to ``Message``/``DocVersion`` leaves, so they are not
hopped; the blast radius stays about decisions, people, teams, areas and
concepts. ``test_impact.py`` pins the set to ``ingest.ontology.SCHEMA``.

The node projection reuses the graph reader seam and display-property lookup
from :mod:`api.retrieval` so an impact node is titled exactly like an answer
chip (``Person.handle``, ``Area.name``, ``Decision.title``, …).
"""

from __future__ import annotations

from typing import Any

from api.retrieval import GraphReader, display_name

#: Undirected relations the blast radius traverses. Pinned to the §15.3 schema
#: by ``test_impact.py``; ``EVIDENCED_BY``/``HAS_VERSION`` are intentionally
#: excluded (they lead to comment/doc leaves, not entities).
IMPACT_RELATIONS = (
    "ABOUT",
    "AREA",
    "RELATES",
    "SUPERSEDES",
    "ASSOCIATED_TEAM",
    "PROPOSED_BY",
    "OBJECTED",
    "SUPPORTED",
    "MODERATED",
)

#: Maximum hop distance from the seed; the wire payload is depth 1..3.
IMPACT_MAX_DEPTH = 3
#: Hard ceiling on visited nodes, so a hub node cannot explode the payload.
IMPACT_NODE_CAP = 200

#: Wire keys — bound to ``web/src/api/types.ts`` by ``test_wire_contract.py``.
IMPACT_KEYS = ("seed", "nodes", "edges", "evidence_types", "truncated")
IMPACT_NODE_KEYS = ("id", "label", "name", "depth")
IMPACT_EDGE_KEYS = ("src", "dst", "type", "properties")

_SEED_QUERY = (
    "MATCH (n:__Entity__ {id: $id}) "
    "RETURN [l IN labels(n) WHERE l <> '__Entity__'] AS labels, properties(n) AS props"
)
_NEIGHBORS_QUERY = (
    "MATCH (n:__Entity__)-[r]-(m) "
    "WHERE n.id IN $ids AND type(r) IN $rels "
    "RETURN n.id AS origin, "
    "type(r) AS relation, "
    "properties(r) AS props, "
    "startNode(r).id AS src, "
    "endNode(r).id AS dst, "
    "m.id AS neighbor_id, "
    "[l IN labels(m) WHERE l <> '__Entity__'] AS neighbor_labels, "
    "properties(m) AS neighbor_props"
)


def build_impact(
    reader: GraphReader, node_id: str, *, depth: int = IMPACT_MAX_DEPTH
) -> dict[str, Any] | None:
    """Return the blast radius around ``node_id``, or ``None`` when it is absent.

    The result is ``{seed, nodes, edges, evidence_types, truncated}`` where each
    node carries its minimum hop ``depth`` and each edge its canonical
    ``src``/``dst`` direction as stored on the graph.
    """
    seed_rows = reader.query(_SEED_QUERY, {"id": node_id})
    if not seed_rows:
        return None
    seed_labels, seed_properties = seed_rows[0][0], seed_rows[0][1]
    seed_label = seed_labels[0] if seed_labels else ""
    seed_props = dict(seed_properties or {})

    nodes: dict[str, dict[str, Any]] = {
        node_id: _node(node_id, seed_label, seed_props, depth=0)
    }
    edges: dict[tuple[str, str, str], dict[str, Any]] = {}
    truncated = False
    max_depth = max(0, min(depth, IMPACT_MAX_DEPTH))
    frontier = [node_id]
    current_depth = 0

    while frontier and current_depth < max_depth:
        current_depth += 1
        rows = reader.query(
            _NEIGHBORS_QUERY, {"ids": frontier, "rels": list(IMPACT_RELATIONS)}
        )
        next_frontier: list[str] = []
        for row in rows:
            (_, relation, props, src, dst, neighbor_id, neighbor_labels, neighbor_props) = row
            edge_key = (str(src), str(dst), str(relation))
            if edge_key not in edges:
                edges[edge_key] = {
                    "src": str(src),
                    "dst": str(dst),
                    "type": str(relation),
                    "properties": dict(props or {}),
                }
            neighbor_id = str(neighbor_id)
            if neighbor_id in nodes:
                continue
            if len(nodes) >= IMPACT_NODE_CAP:
                truncated = True
                continue
            label = neighbor_labels[0] if neighbor_labels else ""
            nodes[neighbor_id] = _node(
                neighbor_id, label, dict(neighbor_props or {}), depth=current_depth
            )
            next_frontier.append(neighbor_id)
        frontier = next_frontier

    node_ids = set(nodes)
    edge_list = [
        edge
        for edge in edges.values()
        if edge["src"] in node_ids and edge["dst"] in node_ids
    ]
    edge_list.sort(key=lambda edge: (edge["type"], edge["src"], edge["dst"]))
    return {
        "seed": node_id,
        "nodes": sorted(nodes.values(), key=lambda node: (node["depth"], node["id"])),
        "edges": edge_list,
        "evidence_types": sorted({edge["type"] for edge in edge_list}),
        "truncated": truncated,
    }


def _node(node_id: str, label: str, properties: dict[str, Any], *, depth: int) -> dict[str, Any]:
    return {
        "id": node_id,
        "label": label,
        "name": display_name(label, properties) or node_id,
        "depth": depth,
    }
