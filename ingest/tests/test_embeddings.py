"""Offline tests for the committed decision-embeddings transforms.

No network, no FalkorDB: the embedder is injected, so ``build``,
``write``/``read`` round-trips, and validation are all pure.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ingest import embeddings


def _record(rfc: int, *, title: str = "", content: str | None = None) -> dict:
    return {"rfc": rfc, "title": title, "content": content}


def test_decision_search_text_is_title_only_without_content() -> None:
    assert embeddings.decision_search_text(_record(1, title="Async/await")) == "Async/await"


def test_decision_search_text_prefixes_bounded_content() -> None:
    content = "x" * (embeddings.CONTENT_CHAR_LIMIT + 500)
    text = embeddings.decision_search_text(_record(1, title="T", content=content))

    assert text.startswith("T\n\n")
    assert len(text) == len("T\n\n") + embeddings.CONTENT_CHAR_LIMIT


class FakeEmbed:
    def __init__(self, dimension: int) -> None:
        self.dimension = dimension
        self.batches: list[list[str]] = []

    def __call__(self, texts: list[str]) -> list[list[float]]:
        self.batches.append(list(texts))
        return [[float(len(text))] * self.dimension for text in texts]


def test_build_sorts_by_rfc_and_keeps_input_order_within_batches() -> None:
    records = [_record(3, title="three"), _record(1, title="one"), _record(2, title="two")]
    fake = FakeEmbed(dimension=2)

    rows = embeddings.build_decision_embeddings(records, embed=fake, dimension=2)

    assert [row["rfc"] for row in rows] == [1, 2, 3]
    assert all(len(row["vector"]) == 2 for row in rows)


def test_build_pairs_each_vector_with_its_own_record() -> None:
    records = [
        _record(3, title="three"),
        _record(1, title="one"),
        _record(2, title="two!"),
    ]
    fake = FakeEmbed(dimension=1)

    rows = embeddings.build_decision_embeddings(records, embed=fake, dimension=1)

    assert {row["rfc"]: row["vector"] for row in rows} == {
        1: [3.0],
        2: [4.0],
        3: [5.0],
    }


def test_build_batches_large_inputs() -> None:
    records = [_record(rfc, title=f"r{rfc}") for rfc in range(embeddings.BATCH_SIZE + 1)]
    fake = FakeEmbed(dimension=1)

    embeddings.build_decision_embeddings(records, embed=fake, dimension=1)

    assert [len(batch) for batch in fake.batches] == [embeddings.BATCH_SIZE, 1]


def test_build_rejects_a_wrong_dimension() -> None:
    fake = FakeEmbed(dimension=2)

    with pytest.raises(ValueError, match="expected 3"):
        embeddings.build_decision_embeddings(
            [_record(1, title="x")], embed=fake, dimension=3
        )


def test_build_rejects_a_vector_count_mismatch() -> None:
    with pytest.raises(ValueError, match="1 records"):
        embeddings.build_decision_embeddings(
            [_record(1, title="x")], embed=lambda texts: [], dimension=2
        )


def test_write_then_read_round_trips(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "rfcs.jsonl").write_text(
        "".join(
            json.dumps(_record(rfc, title=f"r{rfc}")) + "\n" for rfc in (2, 1)
        ),
        encoding="utf-8",
    )

    written = embeddings.write_decision_embeddings(
        snapshot, embed=FakeEmbed(dimension=2), model="test/model", dimension=2
    )
    read_back = embeddings.read_decision_embeddings(
        snapshot / embeddings.EMBEDDINGS_FILENAME
    )

    assert written == 2
    assert read_back.model == "test/model"
    assert read_back.dimension == 2
    assert set(read_back.vectors) == {1, 2}
    assert all(len(vector) == 2 for vector in read_back.vectors.values())


def test_write_records_the_metadata_row_first(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "rfcs.jsonl").write_text(
        json.dumps(_record(1, title="r1")) + "\n", encoding="utf-8"
    )

    embeddings.write_decision_embeddings(
        snapshot, embed=FakeEmbed(dimension=2), model="test/model", dimension=2
    )

    first_line = (snapshot / embeddings.EMBEDDINGS_FILENAME).read_text(
        encoding="utf-8"
    ).split("\n")[0]
    assert json.loads(first_line) == {"model": "test/model", "dimension": 2}


def test_read_rejects_a_missing_metadata_row(tmp_path: Path) -> None:
    path = tmp_path / "decision-embeddings.jsonl"
    path.write_text('{"rfc":1,"vector":[0.1,0.2]}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="metadata row"):
        embeddings.read_decision_embeddings(path)


def test_read_rejects_a_vector_length_that_disagrees_with_the_metadata(
    tmp_path: Path,
) -> None:
    path = tmp_path / "decision-embeddings.jsonl"
    path.write_text(
        '{"model":"m","dimension":3}\n{"rfc":1,"vector":[0.1,0.2]}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="3-dimensional"):
        embeddings.read_decision_embeddings(path)
