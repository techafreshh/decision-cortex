"""Build and read the committed Decision embeddings for the vector seed.

This is the one-time event-time step that gives the retrieval vector seed its
foundation. Each RFC's title plus a bounded prefix of its markdown is embedded
with the OpenRouter embeddings endpoint — the same slug the app embeds queries
with — and the vectors are committed as ``snapshot/decision-embeddings.jsonl``.
The file's first line records the embedding model slug and dimension that
produced the vectors, so the loader can prove they match the query embedder
before building the vector index (a mismatch would search one space with
another's vectors). Embeddings are committed data, exactly like the rest of the
snapshot, so the loader stamps them onto ``Decision`` nodes and builds the
FalkorDB vector index without an LLM call: automated CI and judge replay stay at
zero model cost.

Everything except :func:`main` is pure and takes an injected embedder, so the
transforms are tested offline with no network and no key.
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ingest import snapshot_pipeline

#: The bounded markdown prefix embedded alongside the title, in characters.
CONTENT_CHAR_LIMIT = 2_000
#: Texts per embeddings request.
BATCH_SIZE = 64

EMBEDDINGS_FILENAME = "decision-embeddings.jsonl"


@dataclass(frozen=True, slots=True)
class DecisionEmbeddings:
    """The committed vector artifact: its embedder identity plus the vectors.

    The model slug and dimension are recorded alongside the vectors because the
    vectors alone cannot reveal which embedding space produced them. The loader
    compares both against the query embedder's configuration, so a mismatch is a
    loud failure instead of a crash or silently wrong neighbours. Every vector
    must be ``dimension`` long.
    """

    model: str
    dimension: int
    vectors: Mapping[int, list[float]]

    def __post_init__(self) -> None:
        if not self.model:
            raise ValueError("decision embeddings must record the embedding model slug")
        if self.dimension < 1:
            raise ValueError(f"embedding dimension must be positive, got {self.dimension}")
        lengths = {len(vector) for vector in self.vectors.values()}
        if lengths - {self.dimension}:
            raise ValueError(
                f"embedding vectors must all be {self.dimension}-dimensional, "
                f"got lengths {sorted(lengths)}"
            )


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
    model: str,
    dimension: int,
    out: str | Path | None = None,
) -> int:
    """Read ``rfcs.jsonl``, embed it, and write the committed vector file.

    The first line is a metadata row carrying ``model`` and ``dimension``; each
    following line is a ``{"rfc", "vector"}`` row. Returns the number of vectors
    written. The caller supplies the real embedder; this function never touches
    the network itself.
    """
    directory = Path(snapshot_dir)
    records = snapshot_pipeline.read_jsonl(directory / "rfcs.jsonl")
    rows = build_decision_embeddings(records, embed=embed, dimension=dimension)

    target = Path(out) if out is not None else directory / EMBEDDINGS_FILENAME
    target.write_text(
        snapshot_pipeline.render_jsonl(
            [{"model": model, "dimension": dimension}, *rows]
        ),
        encoding="utf-8",
    )
    return len(rows)


def read_decision_embeddings(path: str | Path) -> DecisionEmbeddings:
    """Read a decision-embeddings file into its model, dimension, and vectors."""
    records = snapshot_pipeline.read_jsonl(path)
    if not records:
        raise ValueError(f"{path}: decision embeddings file has no metadata row")
    metadata, vector_records = records[0], records[1:]
    try:
        model = str(metadata["model"])
        dimension = int(metadata["dimension"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            f"{path}: first line must be an embedding metadata row "
            "with 'model' and 'dimension'"
        ) from exc
    vectors = {
        int(record["rfc"]): [float(value) for value in record["vector"]]
        for record in vector_records
    }
    return DecisionEmbeddings(model=model, dimension=dimension, vectors=vectors)


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
        model=llm.embedding_model_slug(),
        dimension=llm.embedding_dimension(),
        out=target,
    )
    print(f"wrote {count} decision embeddings to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
