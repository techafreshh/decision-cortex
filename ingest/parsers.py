"""Normalize committed snapshot records into canonical graph-shaped dicts.

The committed ``snapshot/*.jsonl`` files are one normalization pass removed from
raw GitHub REST (see :mod:`ingest.snapshot_pipeline`). This module is the second
layer: it maps those records onto the ``PRD.md`` §15.3 node shapes as plain
dicts, so Phase-1 ingestion stays thin and testable.

Pure functions over dicts — no FalkorDB, no network, no LLM (``AGENTS.md``
prep-line rule), no file I/O.
"""

from __future__ import annotations

from collections.abc import Iterable
from itertools import chain
from typing import Any

#: Corpus RFC statuses that normalize onto a different schema status.
_STATUS_MAP = {"merged": "accepted", "active": "proposed"}
#: Schema statuses that pass through unchanged.
_PASSTHROUGH_STATUSES = frozenset({"accepted", "proposed", "rejected", "replaced", "closed"})


def normalize_status(status: str) -> str:
    """Map a corpus RFC status onto the §15.3 schema status.

    ``merged`` becomes ``accepted`` (shipped as a merged FCP) and ``active``
    becomes ``proposed``; ``accepted``, ``proposed``, ``rejected``, ``replaced``
    and ``closed`` pass through. Anything else is a corpus drift the caller must
    not silently absorb, so it raises :class:`ValueError`.
    """
    if status in _STATUS_MAP:
        return _STATUS_MAP[status]
    if status in _PASSTHROUGH_STATUSES:
        return status
    raise ValueError(f"unknown RFC status: {status!r}")


def parse_decision(record: dict[str, Any]) -> dict[str, Any]:
    """Map one ``rfcs.jsonl`` record onto a Decision node dict.

    ``author``, ``url`` and ``labels`` ride along so Phase 1 can build
    ``PROPOSED_BY`` and area/team links without re-reading the raw snapshot.
    ``madr_link`` has no snapshot source and is ``None``.
    """
    return {
        "rfc": record["rfc"],
        "title": record["title"],
        "status": normalize_status(record["status"]),
        "proposed_on": record["proposed_on"],
        "decided_on": record["decided_on"],
        "supersedes_rfc": record["supersedes_rfc"],
        "madr_link": None,
        "author": record["author"],
        "url": record["url"],
        "labels": list(record["labels"]),
    }


def parse_message(record: dict[str, Any]) -> dict[str, Any]:
    """Map one ``pr-comments.jsonl`` record onto a Message node dict.

    ``text_ref`` is the jump-to-evidence permalink; ``truncated`` is preserved
    verbatim (``AGENTS.md`` provenance honesty); ``stance_hint`` is left ``None``
    for Phase-3 classification.
    """
    return {
        "pr_id": record["pr_id"],
        "comment_id": record["comment_id"],
        "author": record["author"],
        "ts": record["ts"],
        "text_ref": record["url"],
        "stance_hint": None,
        "truncated": record["truncated"],
        "body": record["body"],
    }


def parse_commit(record: dict[str, Any]) -> dict[str, Any]:
    """Map one ``commits.jsonl`` record onto a Commit node dict.

    ``rfc`` and ``url`` ride along for the Decision link and source chip.
    """
    return {
        "sha": record["sha"],
        "ts": record["ts"],
        "message": record["message"],
        "rfc": record["rfc"],
        "url": record["url"],
    }


def parse_person(handle: str) -> dict[str, Any]:
    """Map a GitHub handle onto a canonical Person node dict."""
    return {"handle": handle, "name": None}


def parse_rfcs(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map an iterable of ``rfcs.jsonl`` records onto Decision dicts."""
    return [parse_decision(record) for record in records]


def parse_comments(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map an iterable of ``pr-comments.jsonl`` records onto Message dicts."""
    return [parse_message(record) for record in records]


def parse_commits(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map an iterable of ``commits.jsonl`` records onto Commit dicts."""
    return [parse_commit(record) for record in records]


def parse_persons(
    decisions: Iterable[dict[str, Any]],
    messages: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Derive the canonical Person dicts from Decision and Message authors.

    De-duplicated by handle and sorted for determinism; records without an
    author handle (a deleted GitHub account) contribute no Person.
    """
    handles = {
        record["author"]
        for record in chain(decisions, messages)
        if record["author"]
    }
    return [parse_person(handle) for handle in sorted(handles)]
