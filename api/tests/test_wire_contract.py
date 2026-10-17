"""Conformance between the frozen backend schema and its hand-written web mirror.

The web SPA parses the ``POST /ask`` stream with blind casts (``web/src/api/``),
so a drifted field name would fail only at render, in the browser, after deploy.
This test binds ``web/src/api/types.ts`` to the backend's single declared source
of truth (:data:`api.events.EVENT_FIELDS` and :data:`api.nodes._SOURCE_KEYS`) and
runs in the CI python job, so drift fails the build instead.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from api import events, nodes

_TYPES_TS = Path(__file__).resolve().parents[2] / "web" / "src" / "api" / "types.ts"


@pytest.fixture(scope="module")
def types_source() -> str:
    if not _TYPES_TS.exists():
        pytest.skip(f"web mirror not present: {_TYPES_TS}")
    return _TYPES_TS.read_text(encoding="utf-8")


def _declared_event_names(source: str) -> set[str]:
    """The members of the ``EventType`` union in ``types.ts``."""
    block = source.split("export type EventType =", 1)[1].split("\n\n", 1)[0]
    return set(re.findall(r"'([A-Z_]+)'", block))


def _declared_event_fields(source: str) -> dict[str, tuple[str, ...]]:
    """Each ``AskEvent`` member's ``type`` and payload field names."""
    block = source.split("export type AskEvent =", 1)[1]
    members = re.findall(r"\{[^{}]*type: '([A-Z_]+)'([^{}]*)\}", block)
    return {
        name: tuple(re.findall(r"(\w+):", fields)) for name, fields in members
    }


def test_event_names_match_the_backend(types_source: str) -> None:
    assert _declared_event_names(types_source) == set(events.EVENT_FIELDS)


def test_event_fields_match_the_backend(types_source: str) -> None:
    assert _declared_event_fields(types_source) == events.EVENT_FIELDS


def test_node_source_fields_match_the_backend(types_source: str) -> None:
    block = types_source.split("export interface NodeSource {", 1)[1].split("}", 1)[0]
    assert set(re.findall(r"(\w+):", block)) == set(nodes._SOURCE_KEYS)
