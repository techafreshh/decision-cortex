"""Offline shape tests for the snapshot pipeline.

No network, no FalkorDB, no LLM: these read the committed fixtures and the
committed corpus under ``snapshot/`` and pin the record shapes. They are not
marked ``integration`` or ``live``, so they run in offline CI.
"""

from __future__ import annotations

import json
import time
import urllib.error
from collections.abc import Iterator
from pathlib import Path

from ingest import fetch_snapshot
from ingest import snapshot_pipeline as pipeline

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "snapshot" / "fixtures"
SNAPSHOT = REPO_ROOT / "snapshot"


def _load(name: str) -> object:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _http_error(code: int, headers: dict[str, str]) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://api.github.com/x", code, "boom", headers, None
    )


class _StubClient:
    """Minimal ``GitHubClient`` stand-in for the ownership resolver."""

    def __init__(
        self,
        commits: dict[str, list[dict[str, object]]],
        pulls: dict[str, list[dict[str, object]]],
    ) -> None:
        self._commits = commits
        self._pulls = pulls

    def paginate(
        self, path: str, *, params: dict[str, object]
    ) -> Iterator[dict[str, object]]:
        yield from self._commits[params["path"]]

    def get(self, url: str) -> list[dict[str, object]]:
        sha = url.split("/commits/")[1].split("/")[0]
        return self._pulls[sha]


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


def test_rfc_without_markdown_carries_null_content() -> None:
    pull = {"number": 7, "title": "no file", "state": "open", "created_at": None}
    record = pipeline.normalize_rfc(pull)
    pipeline.validate_rfc(record)
    assert record["content"] is None


def test_fixture_comments_normalize_to_pinned_shape() -> None:
    for comment in _load("comments.json"):
        record = pipeline.normalize_comment(comment, pr_id=100, truncated=False)
        pipeline.validate_comment(record)
        assert record["pr_id"] == 100
        assert record["truncated"] is False


def test_clipped_thread_marks_retained_comments_truncated() -> None:
    thread = [
        {"id": index, "created_at": "2020-01-01T00:00:00Z", "body": "x"}
        for index in range(150)
    ]
    kept, truncated = pipeline.cap_comments(thread)
    assert truncated is True

    records = [
        pipeline.normalize_comment(comment, pr_id=7, truncated=truncated)
        for comment in kept
    ]
    assert len(records) == pipeline.COMMENT_CAP
    for record in records:
        pipeline.validate_comment(record)
        assert record["truncated"] is True


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


def test_write_jsonl_is_content_hash_noop(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    records = [{"id": 2, "v": "b"}, {"id": 1, "v": "a"}]

    assert pipeline.write_jsonl(path, records, key=lambda record: record["id"]) is True
    first = path.read_bytes()
    assert pipeline.read_jsonl(path) == [{"id": 1, "v": "a"}, {"id": 2, "v": "b"}]

    assert pipeline.write_jsonl(path, records, key=lambda record: record["id"]) is False
    assert path.read_bytes() == first


def test_read_jsonl_round_trips_unicode_separators(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    record = {"body": "before\u2028after\u0085end\u2029."}

    assert pipeline.write_jsonl(path, [record], key=lambda item: item["body"]) is True
    assert pipeline.read_jsonl(path) == [record]


def test_resolve_rfc_owners_follows_merge_pull_for_orphan_file() -> None:
    client = _StubClient(
        commits={"text/3673-x.md": [{"sha": "newer"}, {"sha": "older"}]},
        pulls={
            "newer": [{"number": 3883, "merged_at": "2025-11-29T11:18:01Z"}],
            "older": [{"number": 3705, "merged_at": "2024-10-03T10:11:44Z"}],
        },
    )
    owners = fetch_snapshot._resolve_rfc_owners(
        client, "rust-lang/rfcs", {3673: ["text/3673-x.md"]}, {3705}
    )
    assert owners == {3705: ["text/3673-x.md"]}


def test_next_link_extracts_only_the_next_rel() -> None:
    header = (
        '<https://api.github.com/x?page=2>; rel="next", '
        '<https://api.github.com/x?page=5>; rel="last"'
    )
    assert fetch_snapshot._next_link(header) == "https://api.github.com/x?page=2"
    assert (
        fetch_snapshot._next_link('<https://api.github.com/x?page=5>; rel="last"')
        is None
    )
    assert fetch_snapshot._next_link(None) is None


def test_retry_delay_backs_off_and_waits_out_rate_limit(tmp_path: Path) -> None:
    client = fetch_snapshot.GitHubClient("", tmp_path)

    assert client._retry_delay(_http_error(404, {}), 0) is None
    assert client._retry_delay(_http_error(403, {"Retry-After": "7"}), 0) == 7.0
    assert client._retry_delay(_http_error(429, {}), 0) == 1.0

    reset = str(int(time.time()) + 30)
    delay = client._retry_delay(
        _http_error(403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": reset}), 0
    )
    assert 30.0 <= delay <= 32.0


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

    comments_per_pr: dict[int, int] = {}
    for record in comments:
        comments_per_pr[record["pr_id"]] = comments_per_pr.get(record["pr_id"], 0) + 1
    assert max(comments_per_pr.values()) <= pipeline.COMMENT_CAP
    assert any(record["truncated"] for record in comments)

    for path in ("rfcs.jsonl", "pr-comments.jsonl", "commits.jsonl"):
        text = (SNAPSHOT / path).read_text(encoding="utf-8")
        assert text.endswith("\n")
        for line in text.split("\n"):
            if line.strip():
                json.loads(line)


def test_committed_corpus_attaches_rfc_markdown() -> None:
    rfcs = {record["rfc"]: record for record in pipeline.read_jsonl(SNAPSHOT / "rfcs.jsonl")}

    # RFC 3673's markdown was merged via a separate pull request (3705).
    assert rfcs[3705]["content"] is not None
    assert rfcs[3705]["content"].startswith("- Start Date:")

    # RFC 2071 renamed its file; the record must hold the RFC, not the stub.
    assert rfcs[2071]["content"].startswith("- Feature Name: impl-trait-existential-types")
    assert not rfcs[2071]["content"].startswith("Moved to")


def test_committed_corpus_commit_rfc_references_join() -> None:
    rfcs = {record["rfc"] for record in pipeline.read_jsonl(SNAPSHOT / "rfcs.jsonl")}
    commits = pipeline.read_jsonl(SNAPSHOT / "commits.jsonl")
    assert {record["rfc"] for record in commits} <= rfcs
