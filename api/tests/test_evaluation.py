"""Offline tests for the verification-set runner and its endpoints.

No network: the pipeline seam is substituted with canned :class:`AnswerPlan`s
(the same shape ``answer_question`` returns); only the aggregate math, the
loading honesty, and the endpoint guards are tested here. The live path is the
owner-dispatched ``eval-run`` workflow.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import evaluation, llm, main
from api.abstention import AbstentionReceipt, AbstentionTrigger
from api.answer import AnswerPlan
from api.claim_gate import ClaimVerdict
from api.evaluation import Question
from api.retrieval import EvidenceNode


@pytest.fixture(autouse=True)
def _isolate_llm(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    with llm._ledger_lock:
        llm._ledger.clear()
    yield
    with llm._ledger_lock:
        llm._ledger.clear()


def _node(node_id: str) -> EvidenceNode:
    return EvidenceNode(
        id=node_id, label="Decision", properties={"id": node_id, "title": "T"},
        source="fulltext", score=1.0,
    )


def _plan(
    verdicts: tuple[ClaimVerdict, ...],
    receipt: AbstentionReceipt | None,
    node_ids: tuple[str, ...] = ("rfc:2394",),
) -> AnswerPlan:
    return AnswerPlan(
        route="fact",
        route_confidence=0.9,
        route_escalated=False,
        candidate_count=1,
        rounds=1,
        stopped_early=False,
        queries=("MATCH (n) RETURN n",),
        evidence_nodes=tuple(_node(nid) for nid in node_ids),
        sentences=tuple(verdict.sentence for verdict in verdicts),
        verdicts=verdicts,
        citation_count=sum(len(v.evidence_ids) for v in verdicts),
        claims_total=len(verdicts),
        claims_cited=sum(1 for v in verdicts if v.cited),
        abstention_required=receipt is not None,
        abstention=receipt,
    )


def _cited(evidence_id: str, sentence: str = "Decided.") -> ClaimVerdict:
    return ClaimVerdict(
        sentence=sentence, cited=True, confidence=0.9,
        evidence_ids=(evidence_id,), escalated=False,
    )


def _receipt(trigger: AbstentionTrigger) -> AbstentionReceipt:
    return AbstentionReceipt(
        nodes_searched=3, evidence_chains=2, matches=0, came_close=(),
        trigger=trigger,
    )


def test_gold_counts_correct_when_cited_evidence_resolves_to_expected_rfc() -> None:
    entry = Question(
        type="gold", question="q?", expected_rfc=2394,
        expected_citation="https://example.test", raw={},
    )
    plan = _plan(
        (_cited("message:77"), _cited("rfc:2394")), None,
        node_ids=("rfc:2394", "message:77"),
    )

    result = evaluation.run_set([entry], lambda question: plan)

    payload = result.payload()
    assert payload["gold"]["correct"] == 1
    assert payload["gold"]["accuracy"] == 1.0
    assert payload["gold_detail"][0]["cited_rfcs"] == [2394]


def test_gold_misses_when_the_answer_cites_another_decision() -> None:
    entry = Question(
        type="gold", question="q?", expected_rfc=2394, expected_citation=None, raw={},
    )
    plan = _plan((_cited("rfc:1001"),), None, node_ids=("rfc:1001",))

    result = evaluation.run_set([entry], lambda question: plan)

    assert result.payload()["gold"]["correct"] == 0


def test_pr_comment_evidence_resolves_through_its_properties() -> None:
    entry = Question(
        type="gold", question="q?", expected_rfc=2394, expected_citation=None, raw={},
    )
    plan = _plan((_cited("message:77", ),), None, node_ids=("message:77",))
    # message:77 carries pr_id 2394 in the graph; patch the node's properties.
    object.__setattr__(
        plan.evidence_nodes[0], "properties", {"id": "message:77", "pr_id": 2394}
    )

    result = evaluation.run_set([entry], lambda question: plan)

    assert result.payload()["gold"]["correct"] == 1


@pytest.mark.parametrize(
    "trigger,expected",
    [
        (AbstentionTrigger.OUT_OF_GRAPH, True),
        (AbstentionTrigger.UNCITED, True),
        (AbstentionTrigger.UNGROUNDED, False),
    ],
)
def test_no_record_counts_honest_negatives_but_not_degraded_runs(
    trigger: AbstentionTrigger, expected: bool
) -> None:
    entry = Question(
        type="no_record", question="q?", expected_rfc=None,
        expected_citation=None,
        raw={"verified_absent": True},
    )
    plan = _plan((), _receipt(trigger))

    result = evaluation.run_set([entry], lambda question: plan)

    detail = result.payload()["no_record_detail"][0]
    assert detail["correctly_abstained"] is expected
    assert detail["trigger"] == trigger.value


def test_a_confabulated_answer_on_a_negative_is_a_miss() -> None:
    entry = Question(
        type="no_record", question="q?", expected_rfc=None,
        expected_citation=None, raw={},
    )
    plan = _plan((_cited("rfc:2394"),), None)

    result = evaluation.run_set([entry], lambda question: plan)

    payload = result.payload()
    assert payload["no_record"]["abstained"] == 0
    assert payload["no_record"]["abstention_correctness"] == 0.0


def test_one_failing_question_records_an_error_and_lets_the_rest_run() -> None:
    entries = [
        Question(type="gold", question="ok?", expected_rfc=2394,
                 expected_citation=None, raw={}),
        Question(type="gold", question="boom?", expected_rfc=1,
                 expected_citation=None, raw={}),
    ]
    plans = {
        "ok?": _plan((_cited("rfc:2394"),), None),
        "boom?": None,
    }

    def run_one(question: str) -> AnswerPlan:
        target = plans[question]
        if target is None:
            raise RuntimeError("model exploded")
        return target

    result = evaluation.run_set(entries, run_one)

    payload = result.payload()
    assert payload["gold"]["total"] == 2
    assert payload["gold"]["correct"] == 1
    assert "model exploded" in payload["gold_detail"][1]["error"]


def test_load_set_reads_the_pinned_corpus_set() -> None:
    entries = evaluation.load_set("verification")

    assert len(entries) == 40
    assert len([e for e in entries if e.type == "gold"]) == 30
    assert len([e for e in entries if e.type == "no_record"]) == 10
    # Order follows the file: gold first, negatives trailing, as authored.
    assert entries[0].type == "gold"
    assert entries[-1].type == "no_record"


def test_load_set_honors_the_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "questions.jsonl").write_text(
        json.dumps({"type": "gold", "question": "mini?", "expected_rfc": 2394,
                    "expected_citation": "u"}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("VERIFICATION_DIR", str(tmp_path))

    entries = evaluation.load_set()

    assert len(entries) == 1
    assert entries[0].question == "mini?"


def test_get_verification_serves_the_pinned_set() -> None:
    with TestClient(main.app) as client:
        response = client.get("/verification")

    assert response.status_code == 200
    body = response.json()
    assert body["counts"] == {"gold": 30, "no_record": 10}
    assert len(body["gold"]) == 30
    # The negatives keep their absense-verification method in the response.
    assert body["no_record"][0]["verified_absent"] is True


def test_run_endpoint_refuses_without_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    with TestClient(main.app) as client:
        response = client.post("/verification/run")

    assert response.status_code == 503
    assert "OPENROUTER_API_KEY" in response.json()["detail"]


def test_run_endpoint_reports_the_executed_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("VERIFICATION_DIR", raising=False)
    entry = Question(
        type="gold", question="q?", expected_rfc=2394, expected_citation=None, raw={}
    )

    monkeypatch.setattr(
        evaluation, "load_set", lambda directory=None: [entry]
    )
    monkeypatch.setattr(
        main, "answer_question", lambda question: _plan(
            (_cited("rfc:2394"),), None
        )
    )
    llm.ledger_append(
        llm.LedgerRecord(
            input_digest="d", choice="e0", confidence=0.9, model="test",
            latency_ms=5, cost_usd=0.05, escalated=False,
        )
    )

    with TestClient(main.app) as client:
        response = client.post("/verification/run")

    assert response.status_code == 200
    body = response.json()
    assert body["gold"]["correct"] == 1
    assert body["calls"] == 0  # the run's own collection excludes pre-existing rows
    assert body["total_calls"] == 1
    assert body["total_cost_usd"] == pytest.approx(0.05)
