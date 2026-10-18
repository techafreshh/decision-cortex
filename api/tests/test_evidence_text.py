"""Offline tests for prompt grounding in the pinned snapshot text.

Each test points ``SNAPSHOT_DIR`` at a tiny fixture directory and clears the
module cache (it is keyed by directory, but the isolation makes that explicit),
so no test depends on the real committed corpus.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from api import evidence_text
from api.tests.fakes import FakeReader, evidence_node


@pytest.fixture()
def snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A minimal three-file snapshot with one record type each."""
    (tmp_path / "rfcs.jsonl").write_text(
        json.dumps(
            {"rfc": 200, "title": "Trait objects", "content": "The decision text. " * 3,
             "body": "fallback body"}
        )
        + "\n"
        + json.dumps({"rfc": 999, "title": "Title-only RFC", "content": None, "body": None})
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "pr-comments.jsonl").write_text(
        json.dumps(
            {"pr_id": 200, "comment_id": 5001, "author": "bob",
             "ts": "2019-01-01T00:00:00Z", "body": "I object to the blanket impl.",
             "url": "https://example.test/5001", "truncated": False}
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "commits.jsonl").write_text(
        json.dumps(
            {"sha": "abc123", "rfc": 200, "ts": "2019-02-02T00:00:00Z",
             "message": "Merge pull request #200", "url": "https://example.test/abc"}
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path))
    evidence_text.clear_cache()
    yield tmp_path
    evidence_text.clear_cache()


def test_message_bodies_come_from_the_snapshot(snapshot: Path) -> None:
    node = evidence_node("Message", "message:5001", text_ref="https://example.test/5001")

    assert evidence_text.evidence_text(node) == "I object to the blanket impl."


def test_decisions_prefer_content_then_body_then_title(snapshot: Path) -> None:
    with_content = evidence_node("Decision", "rfc:200", title="Trait objects")
    title_only = evidence_node("Decision", "rfc:999", title="Title-only RFC")
    unknown = evidence_node("Decision", "rfc:1234", title="Ghost")

    assert evidence_text.evidence_text(with_content).startswith("The decision text.")
    assert evidence_text.evidence_text(title_only) == "Title-only RFC"
    # No snapshot entry at all: the graph node's own title still grounds it.
    assert evidence_text.evidence_text(unknown) == "Ghost"


def test_docversion_shares_the_rfc_text(snapshot: Path) -> None:
    node = evidence_node("DocVersion", "docversion:200", sha="x")

    assert evidence_text.evidence_text(node).startswith("The decision text.")


def test_commits_carry_their_message(snapshot: Path) -> None:
    node = evidence_node("Commit", "commit:abc123", ts="2019-02-02T00:00:00Z")

    assert evidence_text.evidence_text(node) == "Merge pull request #200"


def test_long_text_is_truncated_with_an_ellipsis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pr-comments.jsonl").write_text(
        json.dumps(
            {"pr_id": 1, "comment_id": 7, "author": "a", "ts": "t",
             "body": "x" * (evidence_text.EVIDENCE_TEXT_LIMIT + 50),
             "url": "u", "truncated": False}
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path))
    evidence_text.clear_cache()

    node = evidence_node("Message", "message:7")
    text = evidence_text.evidence_text(node)

    assert len(text) <= evidence_text.EVIDENCE_TEXT_LIMIT + 2
    assert text.endswith("…")


def test_missing_snapshot_files_resolve_to_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path))
    evidence_text.clear_cache()

    assert evidence_text.evidence_text(evidence_node("Message", "message:5001")) is None


def test_resolve_evidence_texts_maps_only_known_ids(snapshot: Path) -> None:
    class EntityReader(FakeReader):
        def query(self, cypher, params=None):
            if "labels(n)" in cypher:
                if params["id"] == "message:5001":
                    return [
                        [["Message"],
                         {"id": "message:5001", "text_ref": "https://example.test/5001"}]
                    ]
                return []
            return super().query(cypher, params)

    texts = evidence_text.resolve_evidence_texts(
        EntityReader(), ["message:5001", "message:missing"]
    )

    assert texts == {"message:5001": "I object to the blanket impl."}


def test_default_snapshot_dir_is_the_pinned_corpus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SNAPSHOT_DIR", raising=False)

    assert evidence_text.snapshot_dir_from_env() == "snapshot"
