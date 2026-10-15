"""Offline shape and corpus-grounding tests for the pinned verification set.

The 40-question set (30 gold + 10 no-record) is the honesty backbone of the
submission: it doubles as the regression eval and powers the abstention
buttons. These tests pin its shape and prove that every gold RFC number and
citation is grounded in the committed snapshot. No network, no FalkorDB, no
LLM, so they run in offline CI.
"""

from __future__ import annotations

from pathlib import Path

from ingest.snapshot_pipeline import read_jsonl

REPO_ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = REPO_ROOT / "verification" / "questions.jsonl"
SNAPSHOT = REPO_ROOT / "snapshot"

GOLD = "gold"
NO_RECORD = "no_record"


def _questions() -> list[dict]:
    return read_jsonl(QUESTIONS)


def test_set_has_exactly_forty_well_formed_entries() -> None:
    entries = _questions()
    assert len(entries) == 40
    for entry in entries:
        assert entry["type"] in (GOLD, NO_RECORD)
        assert isinstance(entry["question"], str) and entry["question"].strip()


def test_set_has_thirty_gold_and_ten_no_record() -> None:
    types = [entry["type"] for entry in _questions()]
    assert types.count(GOLD) == 30
    assert types.count(NO_RECORD) == 10


def test_gold_entries_cite_a_source_from_their_own_rfc() -> None:
    rfcs = {record["rfc"] for record in read_jsonl(SNAPSHOT / "rfcs.jsonl")}
    citation_rfc = {
        record["url"]: record["pr_id"]
        for record in read_jsonl(SNAPSHOT / "pr-comments.jsonl")
    }
    citation_rfc.update(
        {record["url"]: record["rfc"] for record in read_jsonl(SNAPSHOT / "commits.jsonl")}
    )

    gold = [entry for entry in _questions() if entry["type"] == GOLD]
    assert len(gold) == 30
    for entry in gold:
        assert isinstance(entry["expected_rfc"], int)
        assert entry["expected_rfc"] in rfcs
        citation = entry["expected_citation"]
        assert isinstance(citation, str) and citation.strip()
        assert citation in citation_rfc, f"citation not in snapshot: {citation}"
        assert citation_rfc[citation] == entry["expected_rfc"]


def test_no_record_entries_are_verified_absent_with_a_method() -> None:
    no_record = [entry for entry in _questions() if entry["type"] == NO_RECORD]
    assert len(no_record) == 10
    for entry in no_record:
        assert entry["verified_absent"] is True
        method = entry["verification_method"]
        assert isinstance(method, str) and method.strip()
