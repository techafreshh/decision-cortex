"""Build and read the committed Decision embeddings for the vector seed.

This is the one-time event-time step that gives the retrieval vector seed its
foundation. Each RFC's title plus a bounded prefix of its markdown is embedded
with the OpenRouter embeddings endpoint — the same slug the app embeds queries
with — and the vectors are committed as ``snapshot/decision-embeddings.jsonl``.
Embeddings are committed data, exactly like the rest of the snapshot, so the
loader stamps them onto ``Decision`` nodes and builds the FalkorDB vector index
without an LLM call: automated CI and judge replay stay at zero model cost.

Everything except :func:`main` is pure and takes an injected embedder, so the
transforms are tested offline with no network and no key.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from ingest import snapshot_pipeline

#: The bounded markdown prefix embedded alongside the title, in characters.
CONTENT_CHAR_LIMIT = 2_000
#: Texts per embeddings request.
BATCH_SIZE = 64

EMBEDDINGS_FILENAME = "decision-embeddings.jsonl"


def decision_search_text(record: Mapping[str, Any]) -> str:
    """The text embedded for one RFC: title plus a bounded content prefix."""
    title = record.get("title") or ""
    content = record.get("content")
    if not content:
        return title
    return f"{title}\n\n{content[:CONTENT_CHAR_LIMIT]}"


def build_decision_embeddings(
    records: Iterable[Mapping[str, Any]],
    *,
    embed: Callable[[list[str]], list[list[float]]],
    dimension: int,
) -> list[dict[str, Any]]:
    """Embed ``records`` in batches; returns ``{"rfc", "vector"}`` rows by rfc.

    Raises :class:`ValueError` if the embedder returns the wrong number of
    vectors or any vector's length differs from ``dimension`` (an empty or
    wrong-dimension vector would silently corrupt the vector index).
    """
    ordered = sorted(records, key=lambda record: record["rfc"])
    texts = [decision_search_text(record) for record in ordered]

    vectors: list[list[float]] = []
    for start in range(0, len(texts), BATCH_SIZE):
        vectors.extend(embed(texts[start : start + BATCH_SIZE]))
    if len(vectors) != len(ordered):
        raise ValueError(
            f"embedder returned {len(vectors)} vectors for {len(ordered)} records"
        )

    rows: list[dict[str, Any]] = []
    for record, vector in zip(ordered, vectors, strict=True):
        if len(vector) != dimension:
            raise ValueError(
                f"rfc {record['rfc']}: embedding has {len(vector)} dims, "
                f"expected {dimension}"
            )
        rows.append({"rfc": record["rfc"], "vector": [float(value) for value in vector]})
    return rows


def write_decision_embeddings(
    snapshot_dir: str | Path,
    *,
    embed: Callable[[list[str]], list[list[float]]],
    dimension: int,
    out: str | Path | None = None,
) -> int:
    """Read ``rfcs.jsonl``, embed it, and write the committed vector file.

    Returns the number of vectors written. The caller supplies the real
    embedder; this function never touches the network itself.
    """
    directory = Path(snapshot_dir)
    records = snapshot_pipeline.read_jsonl(directory / "rfcs.jsonl")
    rows = build_decision_embeddings(records, embed=embed, dimension=dimension)

    target = Path(out) if out is not None else directory / EMBEDDINGS_FILENAME
    rendered = "".join(
        json.dumps(row, separators=(",", ":")) + "\n" for row in rows
    )
    target.write_text(rendered, encoding="utf-8")
    return len(rows)


def read_decision_embeddings(path: str | Path) -> dict[int, list[float]]:
    """Read a decision-embeddings file into ``rfc -> vector``."""
    return {
        int(record["rfc"]): [float(value) for value in record["vector"]]
        for record in snapshot_pipeline.read_jsonl(path)
    }


def main(argv: list[str] | None = None) -> int:
    """CLI: ``python -m ingest.embeddings [snapshot_dir]`` (needs an API key)."""
    parser = argparse.ArgumentParser(
        prog="python -m ingest.embeddings",
        description="Embed the snapshot's RFCs and commit decision-embeddings.jsonl.",
    )
    parser.add_argument(
        "snapshot_dir",
        nargs="?",
        default="snapshot",
        help="directory holding rfcs.jsonl (and the output file)",
    )
    parser.add_argument(
        "--out",
        default=None,
        help=f"output path (default: <snapshot_dir>/{EMBEDDINGS_FILENAME})",
    )
    args = parser.parse_args(argv)

    # Lazy: keeps offline imports of this module free of the agent lane, and
    # fails here (not at import) if the embedding dependency is missing.
    from api import llm

    target = args.out or os.path.join(args.snapshot_dir, EMBEDDINGS_FILENAME)
    count = write_decision_embeddings(
        args.snapshot_dir,
        embed=llm.embed_documents,
        dimension=llm.embedding_dimension(),
        out=target,
    )
    print(f"wrote {count} decision embeddings to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
