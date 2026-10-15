"""Offline tests for the Phase-0 ontology draft.

No network, no FalkorDB, no LLM. They pin the §15.3 entity/relation coverage,
the pattern-endpoint invariant, and the prep-line dependency rule.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from ingest import ontology
from ingest.ontology import SCHEMA

INGEST = Path(__file__).resolve().parents[1]

ENTITY_LABELS = {
    "Decision",
    "Person",
    "Team",
    "Area",
    "Concept",
    "DocVersion",
    "Message",
    "Commit",
    "Issue",
}
RELATION_LABELS = {
    "PROPOSED_BY",
    "ASSOCIATED_TEAM",
    "ABOUT",
    "AREA",
    "HAS_VERSION",
    "EVIDENCED_BY",
    "OBJECTED",
    "SUPPORTED",
    "MODERATED",
    "SUPERSEDES",
    "MEMBER_OF",
    "RELATES",
}
RELATION_PATTERNS = {
    "PROPOSED_BY": {("Decision", "Person")},
    "ASSOCIATED_TEAM": {("Decision", "Team")},
    "ABOUT": {("Decision", "Concept")},
    "AREA": {("Decision", "Area")},
    "HAS_VERSION": {("Decision", "DocVersion")},
    "EVIDENCED_BY": {
        ("Decision", "Message"),
        ("Decision", "DocVersion"),
        ("Decision", "Commit"),
        ("Decision", "Issue"),
    },
    "OBJECTED": {("Person", "Decision")},
    "SUPPORTED": {("Person", "Decision")},
    "MODERATED": {("Person", "Decision")},
    "SUPERSEDES": {("Decision", "Decision")},
    "MEMBER_OF": {("Person", "Team")},
    "RELATES": {("Concept", "Concept")},
}


def test_schema_declares_exactly_the_section_15_3_entities() -> None:
    assert {entity.label for entity in SCHEMA.entities} == ENTITY_LABELS


def test_schema_declares_the_section_15_3_relations() -> None:
    assert {relation.label for relation in SCHEMA.relations} == RELATION_LABELS


def test_relation_patterns_only_reference_declared_entities() -> None:
    declared = {entity.label for entity in SCHEMA.entities}
    for relation in SCHEMA.relations:
        assert relation.patterns, f"{relation.label} declares no patterns"
        for source, target in relation.patterns:
            assert source in declared, f"{relation.label}: unknown source {source}"
            assert target in declared, f"{relation.label}: unknown target {target}"


def test_relation_patterns_match_section_15_3_directions() -> None:
    actual = {relation.label: set(relation.patterns) for relation in SCHEMA.relations}
    assert actual == RELATION_PATTERNS


def test_draft_modules_do_not_reference_falkordb() -> None:
    for name in ("parsers.py", "ontology.py"):
        source = (INGEST / name).read_text(encoding="utf-8")
        assert "falkordb" not in source, f"{name} must not reference falkordb"


_NO_DEFAULT = object()


def _dataclass_defaults(cls: type) -> dict[str, object]:
    defaults: dict[str, object] = {}
    for f in dataclasses.fields(cls):
        if f.default_factory is not dataclasses.MISSING:
            defaults[f.name] = "factory"
        elif f.default is dataclasses.MISSING:
            defaults[f.name] = _NO_DEFAULT
        else:
            defaults[f.name] = f.default
    return defaults


def _sdk_defaults(cls: type) -> dict[str, object]:
    from pydantic_core import PydanticUndefined

    defaults: dict[str, object] = {}
    for name, f in cls.model_fields.items():
        if f.default_factory is not None:
            defaults[name] = "factory"
        elif f.default is PydanticUndefined:
            defaults[name] = _NO_DEFAULT
        else:
            defaults[name] = f.default
    return defaults


def test_local_types_mirror_graphrag_sdk() -> None:
    models = pytest.importorskip("graphrag_sdk.core.models")

    for local_cls, sdk_cls in (
        (ontology.PropertyType, models.PropertyType),
        (ontology.EntityType, models.EntityType),
        (ontology.RelationType, models.RelationType),
        (ontology.GraphSchema, models.GraphSchema),
    ):
        assert _dataclass_defaults(local_cls) == _sdk_defaults(sdk_cls), (
            f"{local_cls.__name__} fields/defaults drift from the SDK"
        )

    assert ontology.EntityType("X") == ontology.EntityType("X", description="d")
    assert hash(ontology.EntityType("X")) == hash(
        ontology.EntityType("X", description="d")
    )
    assert ontology.RelationType("R") == ontology.RelationType(
        "R", patterns=[("A", "B")]
    )
    assert hash(ontology.RelationType("R")) == hash(
        ontology.RelationType("R", patterns=[("A", "B")])
    )
    assert models.EntityType(label="X") == models.EntityType(label="X", description="d")
    assert models.RelationType(label="R") == models.RelationType(
        label="R", patterns=[("A", "B")]
    )
