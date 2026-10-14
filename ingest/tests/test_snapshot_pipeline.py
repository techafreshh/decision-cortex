"""Offline shape tests for the snapshot pipeline.

No network, no FalkorDB, no LLM: these read the committed fixtures and the
committed corpus under ``snapshot/`` and pin the record shapes. They are not
marked ``integration`` or ``live``, so they run in offline CI.
"""

from __future__ import annotations

import json
from pathlib import Path

from ingest import snapshot_pipeline as pipeline

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "snapshot" / "fixtures"
SNAPSHOT = REPO_ROOT / "snapshot"


def _load(name: str) -> object:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_fixture_pulls_normalize_to_pinned_rfc_shape() -> None:
    records = [
        pipeline.normalize_rfc(pull, content="# RFC\n")
        for pull in _load("pulls.json")
    ]
    for record in records:
        pipeline.validate_rfc(record)

    by_number = {record["rfc"]: record for record in records}
    assert by_number[100]["status"] == pipeline.MERGED
    assert by_number[100]["decided_on"] == "2014-06-17T22:57:09Z"
    assert by_number[100]["supersedes_rfc"] == 42
    assert by_number[9999]["status"] == pipeline.ACTIVE
    assert by_number[9999]["decided_on"] is None
    assert by_number[3]["status"] == pipeline.REJECTED


def test_fixture_comments_normalize_to_pinned_shape() -> None:
    for comment in _load("comments.json"):
        record = pipeline.normalize_comment(comment, pr_id=100, truncated=False)
        pipeline.validate_comment(record)
        assert record["pr_id"] == 100
        assert record["truncated"] is False


def test_fixture_commits_normalize_to_pinned_shape() -> None:
    for commit in _load("commits.json"):
        record = pipeline.normalize_commit(commit, rfc=100)
        pipeline.validate_commit(record)
        assert record["rfc"] == 100
        assert record["message"].startswith("Add RFC 100")


def test_cap_comments_clips_and_flags_truncation() -> None:
    small = [{"id": index, "created_at": "2020-01-01T00:00:00Z"} for index in range(5)]
    kept, truncated = pipeline.cap_comments(small)
    assert len(kept) == 5
    assert truncated is False

    large = [{"id": index, "created_at": "2020-01-01T00:00:00Z"} for index in range(150)]
    kept, truncated = pipeline.cap_comments(large)
    assert len(kept) == pipeline.COMMENT_CAP == 100
    assert truncated is True


def test_merge_jsonl_is_content_hash_noop(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    records = [{"id": 2, "v": "b"}, {"id": 1, "v": "a"}]

    assert pipeline.merge_jsonl(path, records, key=lambda record: record["id"]) is True
    first = path.read_bytes()
    assert pipeline.read_jsonl(path) == [{"id": 1, "v": "a"}, {"id": 2, "v": "b"}]

    assert pipeline.merge_jsonl(path, records, key=lambda record: record["id"]) is False
    assert path.read_bytes() == first


def test_committed_corpus_satisfies_acceptance() -> None:
    rfcs = pipeline.read_jsonl(SNAPSHOT / "rfcs.jsonl")
    comments = pipeline.read_jsonl(SNAPSHOT / "pr-comments.jsonl")
    commits = pipeline.read_jsonl(SNAPSHOT / "commits.jsonl")

    assert rfcs and comments and commits

    for record in rfcs:
        pipeline.validate_rfc(record)
    for record in comments:
        pipeline.validate_comment(record)
    for record in commits:
        pipeline.validate_commit(record)

    statuses = {record["status"] for record in rfcs}
    assert {pipeline.MERGED, pipeline.ACTIVE, pipeline.REJECTED} <= statuses

    for path in ("rfcs.jsonl", "pr-comments.jsonl", "commits.jsonl"):
        text = (SNAPSHOT / path).read_text(encoding="utf-8")
        assert text.endswith("\n")
        for line in text.splitlines():
            json.loads(line)
