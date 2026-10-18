"""The verification-set runner: accuracy and abstention correctness over the
pinned 40 questions (PRD §10, §11.2).

``load_set`` reads ``verification/questions.jsonl`` — the corpus-verified set
pinned in-repo (30 gold + 10 no-record, ``verification/README.md``) — exactly
as authored: questions are never edited to make a metric pass.

``run_set`` executes every question through the live answer pipeline
(:func:`api.answer.answer_question`) and scores each outcome:

- a **gold** question is *correct* when the answer's cited evidence resolves to
  the entry's ``expected_rfc`` — the `rfc:{n}`/`docversion:{n}` node itself, or
  the cited comment/commit whose snapshot properties carry that RFC;
- a **no-record** question is *correctly abstained* when the run produced an
  ``out-of-graph`` or ``uncited`` receipt — the honest negatives. An
  ``ungrounded`` trigger is a degraded run, not a true negative, and counts as
  a miss; a confabulated answer counts as a miss.

One question that raises (a model failure, a spend-cap stop) records an
``error`` result and lets the rest of the set run — a full-set report is worth
more than a fatal one. Every real call lands in the decision ledger, so the
report carries the run's own call count and cost, and the $10 spend cap is the
same guard it always is.

This is the live eval the `eval-run` workflow exists for: it makes real
OpenRouter calls and is dispatched by the owner, never by push/PR CI (which
hard-empties the key — :func:`run_set` refuses with an empty key so the
offline path cannot accidentally burn budget).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from api.abstention import AbstentionTrigger
from api.answer import AnswerPlan

#: The pinned set, shipped next to the repo/tests and copied into the api image.
VERIFICATION_DIR_ENV = "VERIFICATION_DIR"
DEFAULT_VERIFICATION_DIR = "verification"

_QUESTIONS_FILE = "questions.jsonl"


@dataclass(frozen=True, slots=True)
class Question:
    """One pinned entry: a gold question or a verified-absent negative."""

    type: str  # "gold" | "no_record"
    question: str
    expected_rfc: int | None
    expected_citation: str | None
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class SetResult:
    """The full-set outcome: per-question detail plus the aggregate report."""

    gold_detail: tuple[dict[str, Any], ...]
    no_record_detail: tuple[dict[str, Any], ...]

    def payload(self) -> dict[str, Any]:
        gold_total = len(self.gold_detail)
        gold_correct = sum(1 for entry in self.gold_detail if entry["correct"])
        no_total = len(self.no_record_detail)
        no_abstained = sum(
            1 for entry in self.no_record_detail if entry["correctly_abstained"]
        )
        return {
            "gold": {
                "total": gold_total,
                "correct": gold_correct,
                "accuracy": round(gold_correct / gold_total, 4) if gold_total else None,
            },
            "no_record": {
                "total": no_total,
                "abstained": no_abstained,
                "abstention_correctness": (
                    round(no_abstained / no_total, 4) if no_total else None
                ),
            },
            "gold_detail": list(self.gold_detail),
            "no_record_detail": list(self.no_record_detail),
        }


class _RunOne(Protocol):
    """One question → its plan; the seam tests substitute with fakes."""

    def __call__(self, question: str) -> AnswerPlan: ...


def load_set(directory: str | None = None) -> list[Question]:
    """Parse the pinned questions file in set order; gold first, then negatives.

    A missing or unreadable file is :class:`FileNotFoundError` — the set is
    committed, so its absence is a packaging bug worth surfacing loudly.
    """
    base = Path(directory or os.environ.get(VERIFICATION_DIR_ENV, "") or DEFAULT_VERIFICATION_DIR)
    entries: list[Question] = []
    with open(base / _QUESTIONS_FILE, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            entries.append(
                Question(
                    type=str(raw.get("type", "")),
                    question=str(raw.get("question", "")),
                    expected_rfc=raw.get("expected_rfc"),
                    expected_citation=raw.get("expected_citation"),
                    raw=raw,
                )
            )
    return entries


def run_set(entries: list[Question], run_one: _RunOne) -> SetResult:
    """Execute the set; every question runs even after a sibling fails."""
    gold: list[dict[str, Any]] = []
    no_record: list[dict[str, Any]] = []
    for entry in entries:
        try:
            plan = run_one(entry.question)
            if entry.type == "gold":
                gold.append(_gold_detail(entry, plan))
            else:
                no_record.append(_no_record_detail(entry, plan))
        except Exception as exc:  # noqa: BLE001 — one failure must not kill the set
            detail = {
                "question": entry.question,
                "correct": False,
                "correctly_abstained": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
            (gold if entry.type == "gold" else no_record).append(detail)
    return SetResult(gold_detail=tuple(gold), no_record_detail=tuple(no_record))


def _gold_detail(entry: Question, plan: AnswerPlan) -> dict[str, Any]:
    cited = _cited_rfcs(plan)
    expected = entry.expected_rfc
    correct = expected is not None and expected in cited
    return {
        "question": entry.question,
        "expected_rfc": expected,
        "cited_rfcs": sorted(cited),
        "abstained": plan.abstention is not None,
        "correct": correct,
    }


def _no_record_detail(entry: Question, plan: AnswerPlan) -> dict[str, Any]:
    receipt = plan.abstention
    honest_negative = receipt is not None and receipt.trigger in (
        AbstentionTrigger.OUT_OF_GRAPH,
        AbstentionTrigger.UNCITED,
    )
    return {
        "question": entry.question,
        "abstained": receipt is not None,
        "trigger": receipt.trigger.value if receipt is not None else None,
        "correctly_abstained": honest_negative,
    }


def _cited_rfcs(plan: AnswerPlan) -> set[int]:
    """The RFC numbers the answer's cited evidence resolves to."""
    nodes = {node.id: node for node in plan.evidence_nodes}
    cited: set[int] = set()
    for verdict in plan.verdicts:
        for evidence_id in verdict.evidence_ids:
            node = nodes.get(evidence_id)
            named = _id_rfc(evidence_id)
            if named is not None:
                cited.add(named)
            elif node is not None:
                rfc = node.properties.get("rfc", node.properties.get("pr_id"))
                if isinstance(rfc, int):
                    cited.add(rfc)
    return cited


def _id_rfc(evidence_id: str) -> int | None:
    """The RFC number in an `rfc:{n}` or `docversion:{n}` node id, if any."""
    for prefix in ("rfc:", "docversion:"):
        if evidence_id.startswith(prefix):
            try:
                return int(evidence_id[len(prefix):])
            except ValueError:
                return None
    return None


def require_key() -> None:
    """Refuse the live eval when no OpenRouter key is configured."""
    if not os.environ.get("OPENROUTER_API_KEY", "").strip():
        raise RuntimeError(
            "the verification run makes real OpenRouter calls; set "
            "OPENROUTER_API_KEY (owner-dispatched eval-run) to execute it"
        )
