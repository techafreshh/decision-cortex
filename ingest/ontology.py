"""Dependency-free Phase-0 draft of the Decision Cortex graph ontology.

Declares the canonical ``PRD.md`` §15.3 schema as local frozen dataclasses whose
field names, defaults, and identity semantics mirror GraphRAG-SDK v1.1.0
(``graphrag_sdk.core.models``). This is a *draft*: Phase-1 ingestion swaps the
four classes below for the SDK's own ``PropertyType`` / ``EntityType`` /
``RelationType`` / ``GraphSchema`` by changing the import, because the
constructors and label-only identity match — ``SCHEMA`` then feeds
ontology-constrained extraction. ``ingest/tests/test_ontology.py`` pins that
parity (skipped when the SDK is not installed).

Nothing here imports FalkorDB, touches the network, or calls an LLM
(``AGENTS.md`` prep-line rule). Only the four node types with a committed
snapshot source are emitted by :mod:`ingest.parsers` (``Decision``, ``Person``,
``Message``, ``Commit``); the other five (``Team``, ``Area``, ``Concept``,
``DocVersion``, ``Issue``) are declared here for Phase-1 extraction and the §4
stretch sub-corpus.

GraphRAG-SDK v1.1.0 ``RelationType`` carries no properties field, so the §15.3
edge properties (``EVIDENCED_BY.type``, the stance ``{evidence, confidence}``,
``RELATES.strength``) are written into each relation's ``description`` text.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PropertyType:
    """A property definition for a node or relationship type."""

    name: str
    type: str = "STRING"
    description: str | None = None
    required: bool = False


@dataclass(frozen=True, eq=False)
class EntityType:
    """Definition of a node/entity type in the graph schema.

    Identity is by ``label`` only, matching GraphRAG-SDK v1.1.0: two instances
    with the same label but different descriptions or properties compare and
    hash equal, so the Phase-1 import swap preserves set/dedupe semantics.
    """

    label: str
    description: str | None = None
    properties: list[PropertyType] = field(default_factory=list)

    def __hash__(self) -> int:
        return hash(self.label)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, EntityType):
            return NotImplemented
        return self.label == other.label


@dataclass(frozen=True, eq=False)
class RelationType:
    """Definition of a relationship type in the graph schema.

    ``patterns`` lists the allowed directional ``(source_label, target_label)``
    pairs; an empty list means the relation is open between any entity types.
    Identity is by ``label`` only, matching GraphRAG-SDK v1.1.0.
    """

    label: str
    description: str | None = None
    patterns: list[tuple[str, str]] = field(default_factory=list)

    def __hash__(self) -> int:
        return hash(self.label)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RelationType):
            return NotImplemented
        return self.label == other.label


@dataclass(frozen=True)
class GraphSchema:
    """Complete schema definition for the knowledge graph."""

    entities: list[EntityType] = field(default_factory=list)
    relations: list[RelationType] = field(default_factory=list)


SCHEMA = GraphSchema(
    entities=[
        EntityType(
            label="Decision",
            description="A rust-lang/rfcs decision record (one RFC / pull request).",
            properties=[
                PropertyType("rfc", "INTEGER"),
                PropertyType("title"),
                PropertyType("status"),
                PropertyType("proposed_on", "DATE"),
                PropertyType("decided_on", "DATE"),
                PropertyType("supersedes_rfc", "INTEGER"),
                PropertyType("madr_link"),
            ],
        ),
        EntityType(
            label="Person",
            description="A GitHub handle; the canonical identity for authors and voters.",
            properties=[PropertyType("handle"), PropertyType("name")],
        ),
        EntityType(
            label="Team",
            description="A Rust team (Phase-1 derivation from RFC fields + OWNERS).",
            properties=[PropertyType("name")],
        ),
        EntityType(
            label="Area",
            description="A decision area (Phase-1 derivation from RFC fields + OWNERS).",
            properties=[PropertyType("name")],
        ),
        EntityType(
            label="Concept",
            description="An extracted topic (Phase-1 GraphRAG-SDK extraction).",
            properties=[PropertyType("key"), PropertyType("name")],
        ),
        EntityType(
            label="DocVersion",
            description="A content-hash-versioned snapshot of an RFC document (Phase 1).",
            properties=[
                PropertyType("sha"),
                PropertyType("ts", "DATE"),
                PropertyType("content_ref"),
            ],
        ),
        EntityType(
            label="Message",
            description="A harvested PR conversation comment; the jump-to-evidence target.",
            properties=[
                PropertyType("pr_id", "INTEGER"),
                PropertyType("comment_id", "INTEGER"),
                PropertyType("author"),
                PropertyType("ts", "DATE"),
                PropertyType("text_ref"),
                PropertyType("stance_hint"),
                PropertyType("truncated", "BOOLEAN"),
            ],
        ),
        EntityType(
            label="Commit",
            description="A commit attached to an RFC pull request.",
            properties=[
                PropertyType("sha"),
                PropertyType("ts", "DATE"),
                PropertyType("message"),
            ],
        ),
        EntityType(
            label="Issue",
            description="An issue from the rust-lang/rust stretch sub-corpus (§4).",
            properties=[
                PropertyType("number", "INTEGER"),
                PropertyType("ts", "DATE"),
                PropertyType("title"),
            ],
        ),
    ],
    relations=[
        RelationType("PROPOSED_BY", patterns=[("Decision", "Person")]),
        RelationType("ASSOCIATED_TEAM", patterns=[("Decision", "Team")]),
        RelationType("ABOUT", patterns=[("Decision", "Concept")]),
        RelationType("AREA", patterns=[("Decision", "Area")]),
        RelationType("HAS_VERSION", patterns=[("Decision", "DocVersion")]),
        RelationType(
            "EVIDENCED_BY",
            description="Edge property type: discussion|vote|revision|implementation.",
            patterns=[
                ("Decision", "Message"),
                ("Decision", "DocVersion"),
                ("Decision", "Commit"),
                ("Decision", "Issue"),
            ],
        ),
        RelationType(
            "OBJECTED",
            description="Stance edge; properties {evidence, confidence}.",
            patterns=[("Person", "Decision")],
        ),
        RelationType(
            "SUPPORTED",
            description="Stance edge; properties {evidence, confidence}.",
            patterns=[("Person", "Decision")],
        ),
        RelationType(
            "MODERATED",
            description="Stance edge; properties {evidence, confidence}.",
            patterns=[("Person", "Decision")],
        ),
        RelationType("SUPERSEDES", patterns=[("Decision", "Decision")]),
        RelationType("MEMBER_OF", patterns=[("Person", "Team")]),
        RelationType(
            "RELATES",
            description="Edge property strength.",
            patterns=[("Concept", "Concept")],
        ),
    ],
)
