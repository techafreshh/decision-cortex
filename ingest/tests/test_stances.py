"""Offline tests for the stance-classification build step.

The classification seam (`stances._classify_call`) is substituted with canned
responses, so no HTTP call and no API key are needed; the tests pin the pair
selection, the strict no-guess policy, the retry behavior, and the artifact
shape the loader's `build_payload(stances=…)` consumes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from api import llm
from ingest import stances
from ingest.stances import Pair, StanceRow


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    with llm._ledger_lock:
        llm._ledger.clear()
    yield
    with llm._ledger_lock:
        llm._ledger.clear()


@pytest.fixture()
def snapshot(tmp_path: Path) -> Path:
    (tmp_path / "rfcs.jsonl").write_text(
        json.dumps({"rfc": 2394, "title": "async fn in traits", "status": "merged"}) + "\n"
        + json.dumps({"rfc": 7, "title": "old proposal", "status": "merged"}) + "\n"
        + json.dumps({"rfc": 50, "title": "rejected one", "status": "rejected"}) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "pr-comments.jsonl").write_text(
        "\n".join(
            json.dumps(record)
            for record in [
                {"pr_id": 2394, "comment_id": 1, "author": "alice", "ts": "t",
                 "body": "I support this design.", "url": "u1", "truncated": False},
                {"pr_id": 2394, "comment_id": 2, "author": "rfcbot", "ts": "t",
                 "body": "FCP started.", "url": "ubot", "truncated": False},
                {"pr_id": 2394, "comment_id": 3, "author": "bob", "ts": "t",
                 "body": "-1 on the blanket impls.", "url": "u3", "truncated": False},
                {"pr_id": 50, "comment_id": 4, "author": "carol", "ts": "t",
                 "body": "thoughts on the rejected one", "url": "u4", "truncated": False},
                {"pr_id": 9999, "comment_id": 5, "author": "ellen", "ts": "t",
                 "body": "comments on an unknown RFC", "url": "u5", "truncated": False},
            ]
        ),
        encoding="utf-8",
    )
    return tmp_path


def test_load_pairs_scopes_to_merged_rfcs_by_default(snapshot: Path) -> None:
    assert [(pair.handle, pair.rfc) for pair in stances.load_pairs(str(snapshot))] == [
        ("alice", 2394),
        ("bob", 2394),
    ]


def test_load_pairs_covers_every_rfc_status_in_all_mode(
    snapshot: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STANCES_STATUSES", "all")

    pairs = stances.load_pairs(str(snapshot))

    assert [p.rfc for p in pairs] == [2394, 2394, 50]


def test_load_pairs_groups_per_author_and_skips_bots_and_unknown_rfcs(
    snapshot: Path,
) -> None:
    pairs = stances.load_pairs(str(snapshot))

    assert [(pair.handle, pair.rfc) for pair in pairs] == [
        ("alice", 2394),
        ("bob", 2394),
    ]


def test_load_pairs_caps_comments_per_pair(tmp_path: Path) -> None:
    (tmp_path / "rfcs.jsonl").write_text(
        json.dumps({"rfc": 1, "title": "x", "status": "merged"}) + "\n",
        encoding="utf-8",
    )
    comments = [
        {"pr_id": 1, "comment_id": i, "author": "dana", "ts": "t",
         "body": "b" * 600, "url": f"u{i}", "truncated": False}
        for i in range(6)
    ]
    (tmp_path / "pr-comments.jsonl").write_text(
        "\n".join(json.dumps(c) for c in comments), encoding="utf-8"
    )
    missing_dir = tmp_path / "empty"
    missing_dir.mkdir()

    pairs = stances.load_pairs(str(tmp_path))

    assert len(pairs) == 1
    assert len(pairs[0].comments) == stances.COMMENTS_PER_PAIR
    assert len(pairs[0].comments[0]["body"]) <= stances.CHARS_PER_COMMENT + 1


def verdicts(payload: list[dict[str, object]]) -> str:
    return json.dumps({"verdicts": payload})


def test_classify_batch_drops_none_and_maps_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pairs = [
        Pair("alice", 2394, "async fn in traits", ({"comment_id": 1, "body": "+1", "url": "u1"},)),
        Pair("bob", 2394, "async fn in traits", ({"comment_id": 3, "body": "-1", "url": "u3"},)),
    ]

    calls: list[str] = []

    def fake_call(model: str, prompt: str) -> llm._CallTrace:
        calls.append(prompt)
        payload = [
            {"handle": "alice", "rfc": 2394, "stance": "SUPPORTED", "confidence": 0.9},
            {"handle": "bob", "rfc": 2394, "stance": "NONE", "confidence": 0.4},
        ]
        return llm._CallTrace(
            model=model, input_digest="d", content=verdicts(payload),
            latency_ms=10, cost_usd=0.001,
        )

    monkeypatch.setattr(stances, "_classify_call", fake_call)

    rows = stances.classify_batch(pairs)

    assert rows == [
        StanceRow(handle="alice", rfc=2394, stance="SUPPORTED",
                  evidence="u1", confidence=0.9)
    ]
    # One ledger row per batch, carrying the call's real cost.
    assert len(llm.ledger_records()) == 1
    assert llm.ledger_records()[0].cost_usd == pytest.approx(0.001)


def test_classify_batch_retries_once_on_bad_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pairs = [Pair("alice", 2394, "t", ({"comment_id": 1, "body": "b", "url": "u"},))]

    attempts: list[int] = []

    def flaky(model: str, prompt: str) -> llm._CallTrace:
        attempts.append(1)
        content = (
            verdicts([
                {"handle": "alice", "rfc": 2394, "stance": "OBJECTED", "confidence": 0.8},
            ])
            if len(attempts) > 1
            else "not json"
        )
        return llm._CallTrace(model=model, input_digest="d", content=content,
                              latency_ms=5, cost_usd=0.0)

    monkeypatch.setattr(stances, "_classify_call", flaky)

    rows = stances.classify_batch(pairs)

    assert len(attempts) == 2
    assert rows[0].stance == "OBJECTED"


def test_classify_batch_aborts_when_the_retry_is_also_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pairs = [Pair("alice", 2394, "t", ({"comment_id": 1, "body": "b", "url": "u"},))]

    def always_bad(model: str, prompt: str) -> llm._CallTrace:
        return llm._CallTrace(model=model, input_digest="d", content="nope",
                              latency_ms=5, cost_usd=0.0)

    monkeypatch.setattr(stances, "_classify_call", always_bad)

    with pytest.raises(RuntimeError, match="schema-valid"):
        stances.classify_batch(pairs)


def test_classify_batch_refuses_without_a_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "")

    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        stances.classify_batch([
            Pair("alice", 2394, "t", ({"comment_id": 1, "body": "b", "url": "u"},))
        ])


def test_model_slug_resolution_prefers_the_stances_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(stances.STANCES_MODEL_SLUG_ENV, raising=False)
    monkeypatch.setenv("DECIDE_MODEL_SLUG", "org/decide-model")
    assert stances.stance_model_slug() == "org/decide-model"

    monkeypatch.setenv(stances.STANCES_MODEL_SLUG_ENV, "org/stances-model")
    assert stances.stance_model_slug() == "org/stances-model"


def test_classify_batch_builds_prompts_for_the_configured_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(stances.STANCES_MODEL_SLUG_ENV, "org/stances-model")
    used: list[str] = []

    def spy(model: str, prompt: str) -> llm._CallTrace:
        used.append(model)
        return llm._CallTrace(
            model=model, input_digest="d",
            content=verdicts([
                {"handle": "alice", "rfc": 2394, "stance": "SUPPORTED", "confidence": 0.9},
            ]),
            latency_ms=5, cost_usd=0.0,
        )

    monkeypatch.setattr(stances, "_classify_call", spy)

    rows = stances.classify_batch([
        Pair("alice", 2394, "t", ({"comment_id": 1, "body": "b", "url": "u"},))
    ])

    assert used == ["org/stances-model"]
    assert rows[0].stance == "SUPPORTED"


def test_derive_stances_runs_batched_and_preserves_pair_order(
    snapshot: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[tuple[str, ...]] = []

    def classifier(batch: list[Pair]) -> list[StanceRow]:
        order.append(tuple(pair.handle for pair in batch))
        return [
            StanceRow(pair.handle, pair.rfc, "MODERATED", pair.evidence_url, 0.7)
            for pair in batch
        ]

    rows = stances.derive_stances(str(snapshot), classifier=classifier)

    # 2 pairs → exactly one batch of ≤ PAIRS_PER_BATCH, pair order preserved.
    assert order == [("alice", "bob")]
    assert [(row.handle, row.rfc) for row in rows] == [("alice", 2394), ("bob", 2394)]


def test_write_artifact_emits_loader_shaped_rows(snapshot: Path) -> None:
    rows = [
        StanceRow("bob", 2394, "OBJECTED", "u3", 0.83),
        StanceRow("alice", 2394, "SUPPORTED", "u1", 0.9),
    ]

    path = stances.write_artifact(rows, str(snapshot))

    content = path.read_text(encoding="utf-8").splitlines()
    first = json.loads(content[0])
    assert first == {
        "handle": "alice",
        "rfc": 2394,
        "stance": "SUPPORTED",
        "evidence": "u1",
        "confidence": 0.9,
    }
    assert len(content) == 2
    assert content[-1].endswith("}")  # newline-terminated JSONL
