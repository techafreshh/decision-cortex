"""Offline tests for the local HHEM faithfulness scorer and its aggregation.

No model and no network: the aggregation runs against a stub :data:`PairScorer`,
the endpoint test swaps the process-wide scorer for the same stub, and the
spend-capped ledger only sees zero-cost rows.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import evidence_text, faithfulness, llm, main
from api.tests.fakes import FakeReader


class StubScorer:
    """Answers each premise/hypothesis batch from a canned list, in order."""

    def __init__(self, scores: list[float]) -> None:
        self.scores = list(scores)
        self.calls: list[tuple[list[str], list[str]]] = []

    def score_pairs(self, premises, hypotheses):
        assert len(premises) == len(hypotheses)
        self.calls.append((list(premises), list(hypotheses)))
        batch = self.scores[: len(premises)]
        del self.scores[: len(premises)]
        assert len(batch) == len(premises), "stub ran out of canned scores"
        return batch


@pytest.fixture(autouse=True)
def _isolate_llm():
    with llm._ledger_lock:
        llm._ledger.clear()
    yield
    with llm._ledger_lock:
        llm._ledger.clear()


@pytest.fixture(autouse=True)
def _threshold_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("FAITHFULNESS_THRESHOLD", raising=False)


@pytest.fixture()
def snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """One-comment snapshot so cited ids resolve to real premise text."""
    (tmp_path / "pr-comments.jsonl").write_text(
        json.dumps(
            {"pr_id": 1, "comment_id": 1, "author": "a", "ts": "t",
             "body": "the evidence text", "url": "u", "truncated": False}
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path))
    evidence_text.clear_cache()
    yield tmp_path
    evidence_text.clear_cache()


def test_supported_claim_when_any_evidence_text_scores_high() -> None:
    claims = [faithfulness.ClaimInput("Rust merged RFC 200.", ("message:1", "message:2"))]
    texts = {"message:1": "the merge comment", "message:2": "an unrelated comment"}

    report = faithfulness.score_answer(
        claims, texts, score_fn=StubScorer([0.2, 0.93]), threshold=0.5
    )

    assert report.claims_supported == 1
    assert report.claims[0].score == pytest.approx(0.93)
    assert report.claims[0].supported is True
    assert report.faithfulness == pytest.approx(1.0)


def test_uncited_sentence_is_an_unsupported_claim() -> None:
    report = faithfulness.score_answer(
        [faithfulness.ClaimInput("Nobody said that.", ())],
        {},
        score_fn=StubScorer([]),
        threshold=0.5,
    )

    assert report.claims[0].status == "uncited"
    assert report.faithfulness == pytest.approx(0.0)


def test_unresolved_evidence_text_never_counts_as_supported() -> None:
    claims = [faithfulness.ClaimInput("A claim.", ("message:missing",))]

    report = faithfulness.score_answer(
        claims, {}, score_fn=StubScorer([]), threshold=0.5
    )

    assert report.claims[0].status == "unresolved"
    assert report.claims[0].supported is False
    assert report.claims_unresolved == 1
    assert report.faithfulness == pytest.approx(0.0)


def test_all_supported_gives_one_and_totals_stay_honest() -> None:
    claims = [
        faithfulness.ClaimInput("First.", ("message:1",)),
        faithfulness.ClaimInput("Second.", ("message:2",)),
        faithfulness.ClaimInput("Uncited.", ()),
    ]
    texts = {"message:1": "one", "message:2": "two"}

    report = faithfulness.score_answer(
        claims, texts, score_fn=StubScorer([1.0, 1.0]), threshold=0.5
    )

    assert (report.claims_total, report.claims_supported) == (3, 2)
    assert report.faithfulness == pytest.approx(round(2 / 3, 4))


def test_scoring_appends_a_zero_cost_ledger_row_named_after_the_model() -> None:
    faithfulness.score_answer(
        [faithfulness.ClaimInput("First.", ("message:1",))],
        {"message:1": "one"},
        score_fn=StubScorer([1.0]),
        threshold=0.5,
    )

    rows = [r for r in llm.ledger_records() if r.model.startswith("faithfulness:")]
    assert len(rows) == 1
    assert rows[0].cost_usd == 0.0
    assert rows[0].confidence is not None


def test_empty_answer_reports_no_claims() -> None:
    report = faithfulness.score_answer([], {}, score_fn=StubScorer([]), threshold=0.5)

    assert report.faithfulness is None
    assert report.claims_total == 0


def test_payload_carries_per_claim_detail() -> None:
    report = faithfulness.score_answer(
        [faithfulness.ClaimInput("First.", ("message:1",))],
        {"message:1": "one"},
        score_fn=StubScorer([0.9]),
        threshold=0.5,
    )

    payload = report.payload()
    assert payload["claims"][0]["sentence"] == "First."
    assert payload["claims"][0]["evidence_ids"] == ["message:1"]
    assert payload["model"] == "faithfulness:hhem-2.1-open"


def test_threshold_env_is_parsed_and_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAITHFULNESS_THRESHOLD", "0.7")
    assert faithfulness.threshold_from_env() == 0.7
    monkeypatch.setenv("FAITHFULNESS_THRESHOLD", "1.5")
    with pytest.raises(ValueError):
        faithfulness.threshold_from_env()
    monkeypatch.setenv("FAITHFULNESS_THRESHOLD", "bogus")
    with pytest.raises(ValueError):
        faithfulness.threshold_from_env()


def test_scorer_model_id_is_env_configurable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FAITHFULNESS_MODEL_ID", raising=False)
    assert faithfulness.model_id_from_env() == faithfulness.HHEM_MODEL_ID

    monkeypatch.setenv("FAITHFULNESS_MODEL_ID", "my-org/my-cross-encoder")
    scorer = faithfulness.HHEMScorer(model_id=faithfulness.model_id_from_env())
    assert scorer.model_id == "my-org/my-cross-encoder"

    # The report carries the configured id, not just the zero-cost label.
    report = faithfulness.score_answer(
        [faithfulness.ClaimInput("First.", ("message:1",))],
        {"message:1": "one"},
        score_fn=StubScorer([1.0]),
        model_label="my-org/my-cross-encoder",
        threshold=0.5,
    )
    assert report.model == "my-org/my-cross-encoder"


def test_scorer_rejects_mismatched_batches() -> None:
    scorer = faithfulness.HHEMScorer()
    with pytest.raises(ValueError):
        scorer.score_pairs(["only one premise"], ["a", "b"])


def test_endpoint_scores_claims_and_reports(
    snapshot: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class EntityReader(FakeReader):
        def query(self, cypher, params=None):
            if "labels(n)" in cypher and params["id"] == "message:1":
                return [[["Message"], {"id": "message:1", "text_ref": "u"}]]
            if "labels(n)" in cypher:
                return []
            return super().query(cypher, params)

    monkeypatch.setattr(main, "connect_from_env", lambda: EntityReader())
    stub = StubScorer([0.9])
    monkeypatch.setattr(faithfulness, "get_scorer", lambda: stub)

    with TestClient(main.app) as client:
        response = client.post(
            "/faithfulness",
            json={"claims": [{"sentence": "First.", "evidence_ids": ["message:1"]}]},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["faithfulness"] == pytest.approx(1.0)
    assert body["claims"][0]["supported"] is True
    # The premise the stub scored is the real snapshot body, not the ref URL.
    assert stub.calls[0][0] == ["the evidence text"]


def test_endpoint_answers_503_when_the_scorer_stack_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_scorer():
        raise faithfulness.FaithfulnessUnavailableError(
            "the local HHEM scorer needs the 'faithfulness' extra"
        )

    monkeypatch.setattr(main, "connect_from_env", lambda: FakeReader())
    monkeypatch.setattr(faithfulness, "get_scorer", no_scorer)

    with TestClient(main.app) as client:
        response = client.post(
            "/faithfulness",
            json={"claims": [{"sentence": "First.", "evidence_ids": []}]},
        )

    assert response.status_code == 503
    assert "faithfulness" in response.json()["detail"]
