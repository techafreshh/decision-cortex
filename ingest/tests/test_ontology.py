"""Offline tests for the Phase-0 ontology draft.

No network, no FalkorDB, no LLM. They pin the §15.3 entity/relation coverage,
the pattern-endpoint invariant, and the prep-line dependency rule.
"""

from __future__ import annotations

from pathlib import Path

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


def test_draft_modules_do_not_reference_falkordb() -> None:
    for name in ("parsers.py", "ontology.py"):
        source = (INGEST / name).read_text(encoding="utf-8")
        assert "falkordb" not in source, f"{name} must not reference falkordb"
