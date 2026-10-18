"""Ground evidence ids in the real text the pinned snapshot still holds.

The graph stores refs, never bodies (PRD §10): an evidence node always reads as
``Message message:12345: https://github.com/...`` — a permalink, not the debate.
The *committed snapshot* carries the bodies, and the ``api`` container already
ships the snapshot for seed-on-boot (``infra/api.Dockerfile`` copies it), so the
answer pipeline can ground its prompts — and the faithfulness scorer its
premises — in the real text with no network call and no LLM cost.

``evidence_text`` resolves one :class:`~api.retrieval.EvidenceNode` id against
the snapshot files:

- ``rfc:{n}`` / ``docversion:{n}`` → ``snapshot/rfcs.jsonl`` ``content`` (the RFC
  markdown), falling back to ``body`` then ``title``;
- ``message:{comment_id}`` → ``snapshot/pr-comments.jsonl`` ``body``;
- ``commit:{sha}`` → ``snapshot/commits.jsonl`` ``message``.

Everything is a bounded prefix: a premise longer than :data:`EVIDENCE_TEXT_LIMIT`
characters is truncated with a trailing ``…`` so one long RFC text can never
drown a synthesis prompt. A node the snapshot has no text for (an ``Issue``,
a truncated-away comment, a missing ``content``) resolves to ``None`` — honest
absence, never a filler string.

The three JSONL files are parsed once per process, lazily, under a lock: ~30 MB
of JSON is a second of work that only the first prompt build pays for.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Mapping, Sequence
from typing import Any

from api.retrieval import EvidenceNode, GraphReader

#: ``snapshot`` inside the repo and inside the ``api`` image; same variable the
#: seed-on-boot entrypoint already reads (``api/seed.py``).
SNAPSHOT_DIR_ENV = "SNAPSHOT_DIR"
DEFAULT_SNAPSHOT_DIR = "snapshot"

#: Longest evidence prefix carried into a prompt; beyond this, one RFC's
#: markdown would dominate the evidence list. The HHEM tokenizer truncates
#: again at its own 512-token input limit.
EVIDENCE_TEXT_LIMIT = 600

#: The pinned snapshot record shapes (``snapshot/README.md``), pinned by
#: ``ingest.snapshot_pipeline`` — kept as tuples so the parser accepts anything.
_RFC_FILE = "rfcs.jsonl"
_COMMENTS_FILE = "pr-comments.jsonl"
_COMMITS_FILE = "commits.jsonl"

_lock = threading.Lock()
_texts: dict[str, str] | None = None
_loaded_dir: str | None = None


def snapshot_dir_from_env() -> str:
    """The snapshot directory from the environment (``SNAPSHOT_DIR`` or default)."""
    return os.environ.get(SNAPSHOT_DIR_ENV, "").strip() or DEFAULT_SNAPSHOT_DIR


def _load(snapshot_dir: str) -> dict[str, str]:
    texts: dict[str, str] = {}
    for line in _read_lines(os.path.join(snapshot_dir, _RFC_FILE)):
        rfc = line.get("rfc")
        if rfc is None:
            continue
        text = _bounded_prefix(line, "content") or _bounded_prefix(line, "body") or ""
        title = line.get("title")
        titles = str(title) if isinstance(title, str) and title.strip() else ""
        texts[f"rfc:{rfc}"] = text or titles
        texts[f"docversion:{rfc}"] = text or titles
    for line in _read_lines(os.path.join(snapshot_dir, _COMMENTS_FILE)):
        comment_id = line.get("comment_id")
        body = line.get("body")
        if comment_id is None or not isinstance(body, str):
            continue
        texts[f"message:{comment_id}"] = _bounded(body)
    for line in _read_lines(os.path.join(snapshot_dir, _COMMITS_FILE)):
        sha = line.get("sha")
        message = line.get("message")
        if sha is None or not isinstance(message, str):
            continue
        texts[f"commit:{sha}"] = _bounded(message)
    return texts


def _bounded_prefix(record: Mapping[str, Any], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str):
        return ""
    return _bounded(value)


def _bounded(text: str) -> str:
    stripped = text.strip()
    if len(stripped) <= EVIDENCE_TEXT_LIMIT:
        return stripped
    return stripped[:EVIDENCE_TEXT_LIMIT].rstrip() + " …"


def _read_lines(path: str) -> list[dict[str, Any]]:
    """Parse a snapshot JSONL; a missing or empty file is an empty harvest."""
    try:
        with open(path, encoding="utf-8") as handle:
            lines = []
            for raw in handle:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    record = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    lines.append(record)
            return lines
    except OSError:
        return []


def _snapshot_texts() -> dict[str, str]:
    global _texts, _loaded_dir
    directory = snapshot_dir_from_env()
    with _lock:
        if _texts is None or _loaded_dir != directory:
            _texts = _load(directory)
            _loaded_dir = directory
        return _texts


def clear_cache() -> None:
    """Forget the parsed snapshot (tests switch ``SNAPSHOT_DIR`` between cases)."""
    global _texts, _loaded_dir
    with _lock:
        _texts = None
        _loaded_dir = None


def evidence_text(node: EvidenceNode) -> str | None:
    """The real snapshot text behind ``node``, bounded; ``None`` when absent.

    ``Decision`` nodes whose RFC has no markdown in the pinned snapshot fall
    back to the record's title — always better shown than a bare URL line, and
    still a fact the snapshot holds.
    """
    text = _snapshot_texts().get(node.id)
    if text is not None:
        return text
    # A Decision with no content/body in the snapshot still has its title.
    if node.label == "Decision":
        title = node.properties.get("title")
        if isinstance(title, str) and title.strip():
            return title.strip()
    return None


_ENTITY_QUERY = (
    "MATCH (n:__Entity__ {id: $id}) "
    "RETURN [l IN labels(n) WHERE l <> '__Entity__'] AS labels, properties(n) AS props"
)


def resolve_evidence_texts(
    reader: GraphReader, node_ids: Sequence[str]
) -> dict[str, str]:
    """Map each evidence node id to its real snapshot text (absent ids omitted).

    Citations arrive as bare ids from the web client; their labels live in the
    graph. One indexed ``__Entity__`` lookup per id reconstructs enough of each
    node (label + properties) for :func:`evidence_text` to do its lookup.
    """
    texts: dict[str, str] = {}
    for node_id in node_ids:
        rows = reader.query(_ENTITY_QUERY, {"id": node_id})
        if not rows:
            continue
        labels, properties = rows[0][0], rows[0][1]
        node = EvidenceNode(
            id=node_id,
            label=str(labels[0]) if labels else "",
            properties=dict(properties) if isinstance(properties, Mapping) else {},
            source="graph",
            score=None,
        )
        text = evidence_text(node)
        if text:
            texts[node_id] = text
    return texts
