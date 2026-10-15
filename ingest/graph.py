"""Load the parsed snapshot into FalkorDB as the canonical §15.3 graph.

Two layers, deliberately split so the graph shape is testable without a
database:

* :func:`build_payload` / :func:`validate_payload` are pure — plain parser
  dicts in, a validated :class:`Payload` out, no ``graphrag_sdk`` or
  ``falkordb`` import. The ontology constraint (``ingest.ontology.SCHEMA``)
  is enforced here, offline.
* :func:`load_payload` / :func:`ingest_snapshot` are the IO edge: they import
  GraphRAG-SDK v1.1.0 lazily and upsert through its ``GraphStore``, whose
  ``MERGE``-on-``id`` writes make an unchanged re-run a count no-op.

Everything snapshot-grounded loads deterministically from the parser dicts —
no LLM call anywhere on this path, so ``pytest -m integration`` runs with an
empty ``OPENROUTER_API_KEY``. ``Concept``/``ABOUT`` and the stance edges are
enrichment: Phase 1 maps explicit records through the ``concepts``/``stances``
seam; deriving them over the real corpus is Phase 2/3 work behind the same
:data:`SCHEMA`.

The parser contract is the reason ``contents`` is a separate argument:
:func:`ingest.parsers.parse_decision` intentionally drops the RFC markdown
(only the ``DocVersion`` content hash needs it), so the caller passes the raw
``rfc -> content`` mapping alongside the parsed decisions.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ingest import ontology, parsers, snapshot_pipeline

#: RFC label prefixes that become ``:Team`` / ``:Area`` nodes (no OWNERS files
#: exist in the snapshot, so the label is the only derivation source).
_TEAM_PREFIX = "T-"
_AREA_PREFIX = "A-"


@dataclass(frozen=True)
class Node:
    """A node to write: a namespaced id, its label, and its properties."""

    id: str
    label: str
    properties: Mapping[str, Any]


@dataclass(frozen=True)
class Edge:
    """A directed edge between two node ids."""

    src: str
    dst: str
    type: str
    properties: Mapping[str, Any]


@dataclass(frozen=True)
class Payload:
    """A validated set of nodes and edges ready to load."""

    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]


@dataclass(frozen=True)
class LoadResult:
    """Outcome of one :func:`load_payload` call."""

    node_count: int
    edge_count: int
    graph_name: str


def decision_id(rfc: int) -> str:
    return f"rfc:{rfc}"


def person_id(handle: str) -> str:
    return f"person:{handle}"


def message_id(comment_id: int) -> str:
    return f"message:{comment_id}"


def commit_id(sha: str) -> str:
    return f"commit:{sha}"


def doc_version_id(rfc: int) -> str:
    return f"docversion:{rfc}"


def team_id(label: str) -> str:
    return f"team:{label}"


def area_id(label: str) -> str:
    return f"area:{label}"


def concept_id(key: str) -> str:
    return f"concept:{key}"


def build_payload(
    decisions: Iterable[dict[str, Any]],
    messages: Iterable[dict[str, Any]],
    commits: Iterable[dict[str, Any]],
    *,
    contents: Mapping[int, str | None] | None = None,
    concepts: Iterable[dict[str, Any]] = (),
    stances: Iterable[dict[str, Any]] = (),
) -> Payload:
    """Map parser dicts and enrichment records onto a :class:`Payload`.

    ``contents`` maps an RFC number to its markdown; a non-``None`` entry
    yields the ``DocVersion`` node and its ``HAS_VERSION`` / ``EVIDENCED_BY``
    (revision) edges. ``concepts`` entries carry ``rfc``/``key``/``name`` and
    yield ``Concept`` nodes plus ``ABOUT`` edges; ``stances`` entries carry
    ``rfc``/``handle``/``stance``/``evidence``/``confidence`` and yield the
    stance edge. An edge is emitted only when both endpoints are in the node
    set, so a dangling reference (e.g. a ``supersedes_rfc`` to an RFC outside
    the payload) is dropped rather than written against a missing node.
    """
    decisions = list(decisions)
    messages = list(messages)
    commits = list(commits)
    contents = contents or {}
    concepts = list(concepts)
    stances = list(stances)

    nodes: dict[str, Node] = {}

    def add(node: Node) -> None:
        nodes.setdefault(node.id, node)

    for decision in decisions:
        add(_decision_node(decision))
    for message in messages:
        add(_message_node(message))
    for commit in commits:
        add(_commit_node(commit))
    for decision in decisions:
        content = contents.get(decision["rfc"])
        if content is not None:
            add(_doc_version_node(decision, content))
    for label in _labels(decisions, _TEAM_PREFIX):
        add(Node(team_id(label), "Team", {"name": label}))
    for label in _labels(decisions, _AREA_PREFIX):
        add(Node(area_id(label), "Area", {"name": label}))
    for concept in concepts:
        add(
            Node(
                concept_id(concept["key"]),
                "Concept",
                {"key": concept["key"], "name": concept["name"]},
            )
        )
    for person in _persons(decisions, messages, stances):
        add(Node(person_id(person["handle"]), "Person", person))

    present = set(nodes)
    edges: list[Edge] = []

    def link(
        src: str, dst: str, relation: str, properties: Mapping[str, Any] | None = None
    ) -> None:
        if src in present and dst in present:
            edges.append(Edge(src, dst, relation, dict(properties or {})))

    for decision in decisions:
        rfc = decision["rfc"]
        if decision["author"] is not None:
            link(decision_id(rfc), person_id(decision["author"]), "PROPOSED_BY")
        if decision["supersedes_rfc"] is not None:
            link(decision_id(rfc), decision_id(decision["supersedes_rfc"]), "SUPERSEDES")
        for label in decision["labels"]:
            if label.startswith(_TEAM_PREFIX):
                link(decision_id(rfc), team_id(label), "ASSOCIATED_TEAM")
            elif label.startswith(_AREA_PREFIX):
                link(decision_id(rfc), area_id(label), "AREA")
        if contents.get(rfc) is not None:
            link(decision_id(rfc), doc_version_id(rfc), "HAS_VERSION")
            link(
                decision_id(rfc),
                doc_version_id(rfc),
                "EVIDENCED_BY",
                {"type": "revision"},
            )

    for message in messages:
        link(
            decision_id(message["pr_id"]),
            message_id(message["comment_id"]),
            "EVIDENCED_BY",
            {"type": "discussion"},
        )
    for commit in commits:
        link(
            decision_id(commit["rfc"]),
            commit_id(commit["sha"]),
            "EVIDENCED_BY",
            {"type": "implementation"},
        )
    for concept in concepts:
        link(decision_id(concept["rfc"]), concept_id(concept["key"]), "ABOUT")
    for stance in stances:
        link(
            person_id(stance["handle"]),
            decision_id(stance["rfc"]),
            stance["stance"],
            {"evidence": stance["evidence"], "confidence": stance["confidence"]},
        )

    return Payload(
        nodes=tuple(sorted(nodes.values(), key=lambda node: node.id)),
        edges=tuple(sorted(edges, key=lambda edge: (edge.type, edge.src, edge.dst))),
    )


def validate_payload(payload: Payload) -> None:
    """Assert ``payload`` conforms to the canonical §15.3 ontology.

    Every node label and property key must be declared in
    :data:`ingest.ontology.SCHEMA`; every edge type must be declared there and
    connect the exact ``(source_label, target_label)`` pattern its relation
    declares; every edge endpoint must exist. Raises :class:`ValueError` on the
    first violation.
    """
    properties_by_label = {
        entity.label: {prop.name for prop in entity.properties}
        for entity in ontology.SCHEMA.entities
    }
    patterns = {relation.label: set(relation.patterns) for relation in ontology.SCHEMA.relations}

    labels_by_id: dict[str, str] = {}
    for node in payload.nodes:
        if node.label not in properties_by_label:
            raise ValueError(f"unknown entity label: {node.label!r}")
        undeclared = set(node.properties) - properties_by_label[node.label]
        if undeclared:
            raise ValueError(
                f"{node.label} node has undeclared properties: {sorted(undeclared)}"
            )
        labels_by_id[node.id] = node.label

    for edge in payload.edges:
        if edge.type not in patterns:
            raise ValueError(f"unknown relation type: {edge.type!r}")
        src_label = labels_by_id.get(edge.src)
        dst_label = labels_by_id.get(edge.dst)
        if src_label is None or dst_label is None:
            raise ValueError(f"{edge.type} edge references a missing endpoint")
        if (src_label, dst_label) not in patterns[edge.type]:
            raise ValueError(
                f"{edge.type} edge {src_label}->{dst_label} is not an allowed pattern"
            )


def payload_from_snapshot(snapshot_dir: str | Path) -> Payload:
    """Read a snapshot directory and build its (unvalidated) payload.

    Reads ``rfcs.jsonl``, ``pr-comments.jsonl``, ``commits.jsonl`` and, when
    present, the optional ``concepts.jsonl`` / ``stances.jsonl`` enrichment
    files. Pure: no database, no network.
    """
    directory = Path(snapshot_dir)
    rfc_records = snapshot_pipeline.read_jsonl(directory / "rfcs.jsonl")
    return build_payload(
        parsers.parse_rfcs(rfc_records),
        parsers.parse_comments(
            snapshot_pipeline.read_jsonl(directory / "pr-comments.jsonl")
        ),
        parsers.parse_commits(
            snapshot_pipeline.read_jsonl(directory / "commits.jsonl")
        ),
        contents={record["rfc"]: record["content"] for record in rfc_records},
        concepts=_read_optional_jsonl(directory / "concepts.jsonl"),
        stances=_read_optional_jsonl(directory / "stances.jsonl"),
    )


async def load_payload(
    payload: Payload, *, host: str, port: int, graph_name: str
) -> LoadResult:
    """Upsert ``payload`` into FalkorDB via GraphRAG-SDK's ``GraphStore``.

    Nodes are written before relationships so every edge can match its
    endpoints. Re-running an unchanged payload only re-``MERGE``s, leaving the
    node and edge counts unchanged.
    """
    from graphrag_sdk import ConnectionConfig, FalkorDBConnection, GraphStore
    from graphrag_sdk.core.models import GraphNode, GraphRelationship

    connection = FalkorDBConnection(
        ConnectionConfig(host=host, port=port, graph_name=graph_name)
    )
    store = GraphStore(connection)
    try:
        await _ensure_id_indexes(store)
        nodes = [
            GraphNode(id=node.id, label=node.label, properties=dict(node.properties))
            for node in payload.nodes
        ]
        relationships = [
            GraphRelationship(
                start_node_id=edge.src,
                end_node_id=edge.dst,
                type=edge.type,
                properties=dict(edge.properties),
            )
            for edge in payload.edges
        ]
        node_count = await store.upsert_nodes(nodes)
        edge_count = await store.upsert_relationships(relationships)
    finally:
        await connection.close()
    # ``upsert_nodes`` raises on a per-item failure, but ``upsert_relationships``
    # swallows both its batch and per-item failures and returns a count that may
    # be short — including 0 when the query timeout trips its circuit breaker.
    # On success the SDK returns exactly the attempted count, so a shortfall is
    # always a swallowed write failure and must not be reported as a clean load.
    if node_count != len(payload.nodes):
        raise RuntimeError(
            f"node load shortfall: attempted {len(payload.nodes)}, wrote {node_count}"
        )
    if edge_count != len(payload.edges):
        raise RuntimeError(
            f"edge load shortfall: attempted {len(payload.edges)}, wrote {edge_count}"
        )
    return LoadResult(node_count=node_count, edge_count=edge_count, graph_name=graph_name)


async def ingest_snapshot(
    snapshot_dir: str | Path, *, host: str, port: int, graph_name: str
) -> LoadResult:
    """Build, validate, and load the snapshot at ``snapshot_dir``."""
    payload = payload_from_snapshot(snapshot_dir)
    validate_payload(payload)
    return await load_payload(payload, host=host, port=port, graph_name=graph_name)


def main(argv: list[str] | None = None) -> int:
    """CLI: ``python -m ingest.graph [snapshot_dir]``."""
    parser = argparse.ArgumentParser(
        prog="python -m ingest.graph",
        description="Load the committed snapshot into FalkorDB as the §15.3 graph.",
    )
    parser.add_argument(
        "snapshot_dir",
        nargs="?",
        default="snapshot",
        help="directory holding rfcs.jsonl, pr-comments.jsonl, commits.jsonl",
    )
    args = parser.parse_args(argv)

    result = asyncio.run(
        ingest_snapshot(
            args.snapshot_dir,
            host=os.environ.get("FALKORDB_HOST", "localhost"),
            port=int(os.environ.get("FALKORDB_PORT", "6379")),
            graph_name=os.environ.get("FALKORDB_GRAPH", "decision_cortex"),
        )
    )
    print(
        f"loaded graph '{result.graph_name}': "
        f"{result.node_count} nodes, {result.edge_count} edges"
    )
    return 0


def _decision_node(decision: dict[str, Any]) -> Node:
    return Node(
        decision_id(decision["rfc"]),
        "Decision",
        {
            "rfc": decision["rfc"],
            "title": decision["title"],
            "status": decision["status"],
            "proposed_on": decision["proposed_on"],
            "decided_on": decision["decided_on"],
            "supersedes_rfc": decision["supersedes_rfc"],
            "madr_link": decision["madr_link"],
        },
    )


def _message_node(message: dict[str, Any]) -> Node:
    return Node(
        message_id(message["comment_id"]),
        "Message",
        {
            "pr_id": message["pr_id"],
            "comment_id": message["comment_id"],
            "author": message["author"],
            "ts": message["ts"],
            "text_ref": message["text_ref"],
            "stance_hint": message["stance_hint"],
            "truncated": message["truncated"],
        },
    )


def _commit_node(commit: dict[str, Any]) -> Node:
    return Node(
        commit_id(commit["sha"]),
        "Commit",
        {"sha": commit["sha"], "ts": commit["ts"], "message": commit["message"]},
    )


def _doc_version_node(decision: dict[str, Any], content: str) -> Node:
    return Node(
        doc_version_id(decision["rfc"]),
        "DocVersion",
        {
            "sha": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "ts": decision["decided_on"] or decision["proposed_on"],
            "content_ref": decision["url"],
        },
    )


def _labels(decisions: list[dict[str, Any]], prefix: str) -> list[str]:
    return sorted(
        {
            label
            for decision in decisions
            for label in decision["labels"]
            if label.startswith(prefix)
        }
    )


def _persons(
    decisions: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    stances: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    persons = parsers.parse_persons(decisions, messages)
    known = {person["handle"] for person in persons}
    for stance in stances:
        # Reuse the parser's canonical-handle check so a malformed stance
        # handle fails loudly instead of becoming a bogus :Person id.
        (person,) = parsers.parse_persons([{"author": stance["handle"]}], [])
        if person["handle"] not in known:
            known.add(person["handle"])
            persons.append(person)
    return sorted(persons, key=lambda person: person["handle"])


def _read_optional_jsonl(path: Path) -> list[dict[str, Any]]:
    return snapshot_pipeline.read_jsonl(path) if path.exists() else []


def _id_index_labels() -> tuple[str, ...]:
    """Labels whose ``id`` needs an index, plus ``__Entity__``.

    Every node the builder emits is declared in :data:`ontology.SCHEMA`;
    ``GraphStore`` adds ``__Entity__`` to all of them and the relationship
    MATCHes look up ``__Entity__`` by ``id``.
    """
    return tuple(entity.label for entity in ontology.SCHEMA.entities) + ("__Entity__",)


async def _ensure_id_indexes(store: Any) -> None:
    """Create the ``id`` index each label needs, tolerating existing ones.

    The SDK's ``MERGE``/``MATCH`` on ``{id}`` full-scans a label without an
    index, which exceeds the connection's 10 s query timeout on the real
    corpus (the relationship load then writes zero edges). Creating an index
    that already exists raises "already indexed" — idempotent, so it is
    swallowed.
    """
    for label in _id_index_labels():
        try:
            await store.query_raw(f"CREATE INDEX FOR (n:{label}) ON (n.id)")
        except Exception as exc:
            if "already indexed" not in str(exc).lower():
                raise


if __name__ == "__main__":
    raise SystemExit(main())
