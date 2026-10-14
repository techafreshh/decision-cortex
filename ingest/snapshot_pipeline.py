"""Pure transforms for the committed rust-lang/rfcs snapshot corpus.

The fetcher (:mod:`ingest.fetch_snapshot`) is the only caller: it hands these
functions raw GitHub REST payloads and receives plain dicts, then writes them
as one UTF-8 JSON object per line. Nothing here imports FalkorDB or calls an
LLM (``AGENTS.md`` prep-line rule).

Record shape is pinned by :func:`validate_rfc`, :func:`validate_comment`, and
:func:`validate_commit` and exercised by ``ingest/tests``.

Idempotency: :func:`merge_jsonl` keys records by identity, renders the whole
file deterministically, and rewrites it only when the rendered content differs
from what is already on disk — so re-running over an unchanged corpus is a
content-hash no-op and never appends duplicate lines.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

MERGED = "merged"
ACTIVE = "active"
REJECTED = "rejected"

#: PR-comment harvest cap per pull request (``AGENTS.md`` provenance honesty).
COMMENT_CAP = 100

RFC_KEYS = (
    "rfc",
    "title",
    "status",
    "proposed_on",
    "decided_on",
    "supersedes_rfc",
    "author",
    "url",
    "labels",
    "body",
    "content",
)
COMMENT_KEYS = (
    "pr_id",
    "comment_id",
    "author",
    "ts",
    "body",
    "url",
    "truncated",
)
COMMIT_KEYS = ("sha", "rfc", "ts", "message", "url")

_SUPERSEDES_RE = re.compile(r"(?i)supersed(?:es|ing)\s+#(\d+)")

Key = Callable[[dict[str, Any]], Any]


def rfc_status(pull: dict[str, Any]) -> str:
    """Map a GitHub pull request onto the corpus RFC status.

    ``merged`` (merged FCP), ``active`` (still open), ``rejected`` (closed
    without merge). ``PRD.md`` §15.3 normalizes ``merged`` to ``accepted`` and
    ``active`` to ``proposed`` downstream; the snapshot keeps the corpus words.
    """
    if pull.get("merged_at"):
        return MERGED
    if pull.get("state") == "open":
        return ACTIVE
    return REJECTED


def supersedes_rfc(body: str | None) -> int | None:
    """Best-effort supersession link from an explicit ``supersedes #N``."""
    match = _SUPERSEDES_RE.search(body or "")
    return int(match.group(1)) if match else None


def normalize_rfc(pull: dict[str, Any], *, content: str = "") -> dict[str, Any]:
    """Map a raw pull request onto the ``rfcs.jsonl`` record shape."""
    return {
        "rfc": pull["number"],
        "title": pull.get("title") or "",
        "status": rfc_status(pull),
        "proposed_on": pull.get("created_at"),
        "decided_on": pull.get("merged_at") or pull.get("closed_at"),
        "supersedes_rfc": supersedes_rfc(
            f"{pull.get('body') or ''}\n{content}"
        ),
        "author": (pull.get("user") or {}).get("login"),
        "url": pull.get("html_url"),
        "labels": sorted(
            label["name"]
            for label in pull.get("labels") or []
            if isinstance(label, dict) and label.get("name")
        ),
        "body": pull.get("body") or "",
        "content": content,
    }


def cap_comments(
    comments: Iterable[dict[str, Any]], *, limit: int = COMMENT_CAP
) -> tuple[list[dict[str, Any]], bool]:
    """Keep the first ``limit`` comments and report whether the cap clipped."""
    ordered = sorted(
        comments,
        key=lambda comment: (comment.get("created_at") or "", comment.get("id") or 0),
    )
    return ordered[:limit], len(ordered) > limit


def normalize_comment(
    comment: dict[str, Any], *, pr_id: int, truncated: bool
) -> dict[str, Any]:
    """Map a raw PR conversation comment onto the ``pr-comments.jsonl`` shape."""
    return {
        "pr_id": pr_id,
        "comment_id": comment["id"],
        "author": (comment.get("user") or {}).get("login"),
        "ts": comment.get("created_at"),
        "body": comment.get("body") or "",
        "url": comment.get("html_url"),
        "truncated": bool(truncated),
    }


def normalize_commit(commit: dict[str, Any], *, rfc: int) -> dict[str, Any]:
    """Map a raw commit onto the ``commits.jsonl`` shape, tagged with its RFC."""
    meta = commit.get("commit") or {}
    stamp = (meta.get("committer") or meta.get("author") or {}).get("date")
    return {
        "sha": commit["sha"],
        "rfc": rfc,
        "ts": stamp,
        "message": (meta.get("message") or "").strip(),
        "url": commit.get("html_url"),
    }


def render_jsonl(records: Iterable[dict[str, Any]]) -> str:
    """Render records as UTF-8-safe, newline-terminated JSON lines."""
    return "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
        for record in records
    )


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """Parse a JSONL file, ignoring blank lines."""
    text = Path(path).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def write_jsonl(
    path: str | Path, records: Iterable[dict[str, Any]], *, key: Key
) -> bool:
    """Write deduplicated, deterministically ordered records.

    Returns ``True`` when the file changed, ``False`` when the rendered content
    matched what was already on disk (the content-hash no-op).
    """
    ordered = _dedupe_sorted(records, key)
    rendered = render_jsonl(ordered)
    path = Path(path)
    if path.exists() and path.read_text(encoding="utf-8") == rendered:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")
    return True


def merge_jsonl(
    path: str | Path, records: Iterable[dict[str, Any]], *, key: Key
) -> bool:
    """Merge records into an existing JSONL file by identity, last write wins."""
    path = Path(path)
    existing = read_jsonl(path) if path.exists() else []
    combined: dict[Any, dict[str, Any]] = {key(record): record for record in existing}
    for record in records:
        combined[key(record)] = record
    return write_jsonl(path, combined.values(), key=key)


def _dedupe_sorted(
    records: Iterable[dict[str, Any]], key: Key
) -> list[dict[str, Any]]:
    by_key: dict[Any, dict[str, Any]] = {}
    for record in records:
        by_key[key(record)] = record
    return [by_key[item] for item in sorted(by_key)]


def validate_rfc(record: dict[str, Any]) -> None:
    """Assert the pinned ``rfcs.jsonl`` record shape."""
    _require_keys(record, RFC_KEYS)
    if not isinstance(record["rfc"], int):
        raise TypeError("rfc must be an int")
    if record["status"] not in (MERGED, ACTIVE, REJECTED):
        raise ValueError(f"unknown status: {record['status']!r}")
    if not isinstance(record["labels"], list):
        raise TypeError("labels must be a list")
    if not isinstance(record["content"], str):
        raise TypeError("content must be a string")


def validate_comment(record: dict[str, Any]) -> None:
    """Assert the pinned ``pr-comments.jsonl`` record shape."""
    _require_keys(record, COMMENT_KEYS)
    if not isinstance(record["pr_id"], int) or not isinstance(
        record["comment_id"], int
    ):
        raise TypeError("pr_id and comment_id must be ints")
    if not isinstance(record["truncated"], bool):
        raise TypeError("truncated must be a bool")


def validate_commit(record: dict[str, Any]) -> None:
    """Assert the pinned ``commits.jsonl`` record shape."""
    _require_keys(record, COMMIT_KEYS)
    if not isinstance(record["sha"], str):
        raise TypeError("sha must be a string")
    if not record["sha"]:
        raise ValueError("sha must be non-empty")
    if not isinstance(record["rfc"], int):
        raise TypeError("rfc must be an int")


def _require_keys(record: dict[str, Any], keys: tuple[str, ...]) -> None:
    missing = [name for name in keys if name not in record]
    if missing:
        raise ValueError(f"record missing keys: {missing}")
