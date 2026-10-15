"""Offline behavior tests for the snapshot parsers.

No network, no FalkorDB, no LLM: fixtures and the committed corpus are read
through the existing pipeline and mapped by :mod:`ingest.parsers`. These tests
are not marked ``integration`` or ``live``, so they run in offline CI.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ingest import parsers
from ingest import snapshot_pipeline as pipeline

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "snapshot" / "fixtures"
SNAPSHOT = REPO_ROOT / "snapshot"

DECISION_KEYS = {
    "rfc",
    "title",
    "status",
    "proposed_on",
    "decided_on",
    "supersedes_rfc",
    "madr_link",
    "author",
    "url",
    "labels",
}
ACCEPTANCE_KEYS = {
    "rfc",
    "title",
    "status",
    "proposed_on",
    "decided_on",
    "supersedes_rfc",
}
MESSAGE_KEYS = {
    "pr_id",
    "comment_id",
    "author",
    "ts",
    "text_ref",
    "stance_hint",
    "truncated",
    "body",
}
COMMIT_KEYS = {"sha", "ts", "message", "rfc", "url"}
PERSON_KEYS = {"handle", "name"}


def _load(name: str) -> list[dict[str, object]]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _decision_records() -> list[dict[str, object]]:
    return [
        pipeline.normalize_rfc(pull, content="# RFC\n") for pull in _load("pulls.json")
    ]


def _message_records() -> list[dict[str, object]]:
    return [
        pipeline.normalize_comment(comment, pr_id=100, truncated=index == 1)
        for index, comment in enumerate(_load("comments.json"))
    ]


def _commit_records() -> list[dict[str, object]]:
    return [
        pipeline.normalize_commit(commit, rfc=100) for commit in _load("commits.json")
    ]


@pytest.mark.parametrize(
    ("corpus_status", "schema_status"),
    [
        ("merged", "accepted"),
        ("active", "proposed"),
        ("rejected", "rejected"),
        ("replaced", "replaced"),
        ("closed", "closed"),
        ("accepted", "accepted"),
        ("proposed", "proposed"),
    ],
)
def test_normalize_status_maps_corpus_onto_schema(
    corpus_status: str, schema_status: str
) -> None:
    assert parsers.normalize_status(corpus_status) == schema_status


def test_normalize_status_rejects_unknown_value() -> None:
    with pytest.raises(ValueError):
        parsers.normalize_status("draft")


def test_parse_rfcs_normalizes_fixture_statuses() -> None:
    decisions = parsers.parse_rfcs(_decision_records())
    for decision in decisions:
        assert set(decision) == DECISION_KEYS

    by_rfc = {decision["rfc"]: decision for decision in decisions}
    assert by_rfc[100]["status"] == "accepted"
    assert by_rfc[100]["supersedes_rfc"] == 42
    assert by_rfc[9999]["status"] == "proposed"
    assert by_rfc[3]["status"] == "rejected"
    assert by_rfc[100]["madr_link"] is None


def test_parse_comments_carries_message_shape_and_truncation() -> None:
    messages = parsers.parse_comments(_message_records())
    for message in messages:
        assert set(message) == MESSAGE_KEYS
        assert message["stance_hint"] is None

    assert messages[0]["truncated"] is False
    assert messages[1]["truncated"] is True
    assert messages[0]["text_ref"] == (
        "https://github.com/rust-lang/rfcs/pull/100#issuecomment-5001"
    )


def test_parse_commits_carries_commit_shape_and_rfc() -> None:
    commits = parsers.parse_commits(_commit_records())
    for commit in commits:
        assert set(commit) == COMMIT_KEYS
        assert commit["rfc"] == 100
    assert commits[0]["message"].startswith("Add RFC 100")


def test_parse_persons_dedupes_and_sorts_handles() -> None:
    decisions = parsers.parse_rfcs(_decision_records())
    messages = parsers.parse_comments(_message_records())

    persons = parsers.parse_persons(decisions, messages)

    assert [person["handle"] for person in persons] == ["alice", "bob", "carol"]
    for person in persons:
        assert set(person) == PERSON_KEYS
        assert person["name"] is None


def test_parse_persons_skips_deleted_account() -> None:
    decisions = [{"author": None}, {"author": "alice"}]
    messages = [{"author": None}, {"author": "bob"}]

    persons = parsers.parse_persons(decisions, messages)

    assert [person["handle"] for person in persons] == ["alice", "bob"]


@pytest.mark.parametrize("handle", ["", "   ", " alice", "alice ", "al ice", 123])
def test_parse_persons_rejects_non_canonical_handle(handle: object) -> None:
    with pytest.raises(ValueError):
        parsers.parse_persons([{"author": handle}], [])


def test_committed_corpus_parses_onto_schema_statuses() -> None:
    decisions = parsers.parse_rfcs(pipeline.read_jsonl(SNAPSHOT / "rfcs.jsonl"))

    assert decisions
    for decision in decisions:
        assert ACCEPTANCE_KEYS <= set(decision)
        assert decision["status"] in {"accepted", "proposed", "rejected"}

    statuses = {decision["status"] for decision in decisions}
    assert {"accepted", "proposed", "rejected"} <= statuses
