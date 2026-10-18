"""Derive ``Person-[OBJECTED|SUPPORTED|MODERATED]->Decision`` stances at build time.

The Phase-1 loader provides the seam (``build_payload(stances=…)`` reads an
optional ``snapshot/stances.jsonl``, `docs/graph-schema-notes.md`), but the
derivation was deferred: classifying 21k debate comments is model work and
needs a key. This module is that derivation, as a one-command build step:

    OPENROUTER_API_KEY=<key> python -m ingest.stances        # writes snapshot/stances.jsonl
    docker compose -f infra/docker-compose.yml up -d --build # seeds-on-boot picks it up

Doctrine budget (AGENTS.md): extraction runs on the **cheap decision model in
batches**. Work is grouped per ``(author, rfc)`` pair — a stance is a person's
overall position on one RFC, not one per comment — up to ``COMMENTS_PER_PAIR``
bounded comment excerpts, and pairs are classified ``PAIRS_PER_BATCH`` at a
time through one strict-JSON schema call. A pair the model cannot take a
stance on returns ``NONE`` and is **omitted from the artifact** — classification
never guesses a stance to fill a row. Every edge stays jumpable: ``evidence``
is the permalink of the pair's first comment, and the loader stamps
``{evidence, confidence}`` on the edge exactly as the PRD schema requires.

The run is spend-capped through the same ``SPEND_CAP_USD`` ledger guard as the
serving path, one ledger row per batch, so the owner sees the build's cost in
the same place as every other decision. A batch that fails after one retry
aborts the build — a partial artifact would quietly thin the objection story.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from api import llm


def _classify_call(model: str, prompt: str) -> llm._CallTrace:
    """One strict-JSON classification call through the shared OpenRouter seam."""
    return llm._call_llm(
        model=model,
        prompt=prompt,
        response_format=_schema_response_format(),
        temperature=0.0,
    )

SNAPSHOT_DIR = "snapshot"
COMMENTS_FILE = "pr-comments.jsonl"
RFCS_FILE = "rfcs.jsonl"
OUTPUT_FILE = "stances.jsonl"

#: Bound the excerpt text per `(author, rfc)` pair: a stance is derivable from
#: a person's first few comments, not their whole thread.
COMMENTS_PER_PAIR = 4
CHARS_PER_COMMENT = 500

#: Pairs classified per model call. Batches of this size keep each prompt well
#: under the decision model's context while sharing the schema overhead.
PAIRS_PER_BATCH = 8

#: Infrastructure accounts whose comments never carry a human stance.
_BOT_AUTHORS = frozenset({"rfcbot", "bors", "rust-highfive", "rfcsbot", "github-actions"})

_STANCES = ("SUPPORTED", "OBJECTED", "MODERATED", "NONE")

_MAX_WORKERS = 4


class StanceVerdict(BaseModel):
    """One pair's classification; ``NONE`` means *no labelable stance*."""

    model_config = ConfigDict(extra="forbid")

    handle: str
    rfc: int
    stance: str = Field(pattern="^(SUPPORTED|OBJECTED|MODERATED|NONE)$")
    confidence: float = Field(ge=0.0, le=1.0)


class StanceBatch(BaseModel):
    """The strict-JSON contract for one batch of pair classifications."""

    model_config = ConfigDict(extra="forbid")

    verdicts: list[StanceVerdict]


@dataclass(frozen=True, slots=True)
class Pair:
    """One `(author, rfc)` classification unit with its bounded excerpts."""

    handle: str
    rfc: int
    rfc_title: str
    comments: tuple[dict[str, Any], ...]  # {comment_id, body, url}

    @property
    def evidence_url(self) -> str:
        return str(self.comments[0].get("url", ""))


@dataclass(frozen=True, slots=True)
class StanceRow:
    """One artifact row: exactly what ``build_payload(stances=…)`` consumes."""

    handle: str
    rfc: int
    stance: str
    evidence: str
    confidence: float


def load_pairs(snapshot_dir: str = SNAPSHOT_DIR) -> list[Pair]:
    """Group the snapshot's comments into per-`(author, rfc)` classification units.

    Bot accounts are skipped, RFCs the snapshot has no record for are skipped
    (their numbers cannot become `Decision` ids), and each pair keeps only its
    first ``COMMENTS_PER_PAIR`` comments, bodies bounded.
    """
    rfcs = _rfc_titles(Path(snapshot_dir) / RFCS_FILE)
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for comment in _read_jsonl(Path(snapshot_dir) / COMMENTS_FILE):
        author = str(comment.get("author", "")).strip()
        pr_id = comment.get("pr_id")
        if not author or author.lower() in _BOT_AUTHORS or author.endswith("-bot"):
            continue
        if not isinstance(pr_id, int) or pr_id not in rfcs:
            continue
        grouped.setdefault((author, pr_id), []).append(comment)
    return [
        Pair(
            handle=handle,
            rfc=rfc,
            rfc_title=rfcs[rfc],
            comments=tuple(
                {
                    "comment_id": comment.get("comment_id"),
                    "body": _bounded(str(comment.get("body", ""))),
                    "url": comment.get("url", ""),
                }
                for comment in comments[:COMMENTS_PER_PAIR]
            ),
        )
        for (handle, rfc), comments in sorted(grouped.items())
    ]


def batch_prompt(pairs: Sequence[Pair]) -> str:
    """The batch prompt: one numbered block per pair, labels the schema echoes."""
    blocks: list[str] = []
    for index, pair in enumerate(pairs):
        excerpts = "\n".join(
            f'  - {comment["body"]}' for comment in pair.comments
        )
        blocks.append(
            f"[{index}] handle={pair.handle!r} rfc={pair.rfc} "
            f"title={pair.rfc_title!r}\n{excerpts}"
        )
    return (
        "You classify a participant's overall stance toward an RFC proposal "
        "from the rust-lang/rfcs debate corpus.\n"
        "For every numbered entry decide whether the person SUPPORTED the "
        "proposal (endorsed or argued for it), OBJECTED (argued against the "
        "proposal itself), or takes a MODERATED position (conditional support, "
        "mixed, or procedural). NONE means the excerpts show no labelable "
        "stance toward the proposal. Judge the final position the text alone "
        "supports; do not infer from tone or fame.\n"
        "Return one verdict per entry with the same handle/rfc values.\n\n"
        + "\n\n".join(blocks)
        + "\n"
    )


def _schema_response_format() -> dict[str, object]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "stance_batch",
            "strict": True,
            "schema": StanceBatch.model_json_schema(),
        },
    }


def classify_batch(
    pairs: Sequence[Pair], *, decide_model: str | None = None
) -> list[StanceRow]:
    """Classify one batch; ``NONE`` verdicts are dropped, never guessed into rows.

    Extraction rides the same HTTP seam, spend-cap guard, and model-slug config
    as the serving path (`api.llm`), through its private batch call — the
    locked public surface stays exactly `decide()`/`reason()`/embeddings.
    """
    if not pairs:
        return []
    if not os.environ.get("OPENROUTER_API_KEY", "").strip():
        raise RuntimeError(
            "OPENROUTER_API_KEY is empty; stance classification needs a key"
        )
    prompt = batch_prompt(pairs)
    model = decide_model or llm._model_slug("DECIDE_MODEL_SLUG")
    try:
        trace = _classify_call(model, prompt)
        batch = StanceBatch.model_validate_json(trace.content)
    except (llm.ModelOutputError, ValidationError):
        # One retry, then abort the build: a partial artifact would quietly
        # thin the objection story instead of failing loudly.
        trace = _classify_call(model, prompt)
        try:
            batch = StanceBatch.model_validate_json(trace.content)
        except ValidationError as exc:
            raise RuntimeError(
                f"{model} did not return schema-valid stance JSON: {exc}"
            ) from exc
    _ledger_batch(trace)
    evidence_by_pair = {(pair.handle, pair.rfc): pair.evidence_url for pair in pairs}
    return [
        StanceRow(
            handle=verdict.handle,
            rfc=verdict.rfc,
            stance=verdict.stance,
            evidence=evidence_by_pair.get((verdict.handle, verdict.rfc), ""),
            confidence=verdict.confidence,
        )
        for verdict in batch.verdicts
        if verdict.stance in _STANCES[:-1]
    ]


def derive_stances(
    snapshot_dir: str = SNAPSHOT_DIR,
    *,
    classifier: Any = classify_batch,
    limit: int | None = None,
    max_workers: int = _MAX_WORKERS,
) -> list[StanceRow]:
    """Classify every pair in the snapshot; deterministic order, threaded batches."""
    pairs = load_pairs(snapshot_dir)
    if limit is not None:
        pairs = pairs[:limit]
    batches = [
        pairs[start : start + PAIRS_PER_BATCH]
        for start in range(0, len(pairs), PAIRS_PER_BATCH)
    ]
    rows: list[StanceRow] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for batch_rows in pool.map(lambda batch: classifier(batch), batches):
            rows.extend(batch_rows)
    order = {(pair.handle, pair.rfc): index for index, pair in enumerate(pairs)}
    return sorted(
        rows,
        key=lambda row: (
            order.get((row.handle, row.rfc), len(order)),
            row.handle,
            row.rfc,
        ),
    )


def write_artifact(rows: Sequence[StanceRow], out_dir: str = SNAPSHOT_DIR) -> Path:
    """Write ``stances.jsonl`` deterministically: sorted, stable bytes."""
    path = Path(out_dir) / OUTPUT_FILE
    lines = [
        json.dumps(
            {
                "handle": row.handle,
                "rfc": row.rfc,
                "stance": row.stance,
                "evidence": row.evidence,
                "confidence": row.confidence,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        for row in sorted(rows, key=lambda row: (row.rfc, row.handle, row.stance))
    ]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return path


def main() -> int:
    """The ``python -m ingest.stances`` entrypoint; aborts on classification failure."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--snapshot-dir", default=SNAPSHOT_DIR)
    parser.add_argument("--limit", type=int, default=None, help="classify only the first N pairs (smoke)")
    args = parser.parse_args()
    started = time.monotonic()
    rows = derive_stances(
        args.snapshot_dir,
        limit=args.limit,
    )
    path = write_artifact(rows, args.snapshot_dir)
    spent = llm.ledger_total_cost_usd()
    print(
        f"stances: wrote {len(rows)} rows to {path} "
        f"in {time.monotonic() - started:.0f}s, ledger spend ${spent:.4f}"
    )
    return 0


def _rfc_titles(path: Path) -> dict[int, str]:
    titles: dict[int, str] = {}
    for record in _read_jsonl(path):
        rfc = record.get("rfc")
        title = record.get("title")
        if isinstance(rfc, int) and isinstance(title, str):
            titles[rfc] = title
    return titles


def _bounded(text: str) -> str:
    stripped = text.strip()
    return stripped[:CHARS_PER_COMMENT] + ("…" if len(stripped) > CHARS_PER_COMMENT else "")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"snapshot file missing: {path}")
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        record = json.loads(line)
        if isinstance(record, dict):
            records.append(record)
    return records


def _ledger_batch(trace: llm._CallTrace) -> None:
    """One zero-guess ledger row per batch (digest, latency, real cost)."""
    llm.ledger_append(
        llm.LedgerRecord(
            input_digest=trace.input_digest,
            choice=len(trace.content),
            confidence=None,
            model=trace.model,
            latency_ms=trace.latency_ms,
            cost_usd=trace.cost_usd,
            escalated=False,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
