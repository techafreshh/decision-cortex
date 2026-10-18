"""RAGAS-style faithfulness, scored locally with HHEM-2.1-Open.

``POST /faithfulness`` scores one finished answer that the stream has already
delivered — the badge's "scoring…" phase (PRD §10). The web client posts the
answer's sentences with their cited evidence ids; the server resolves each id to
the real text the pinned snapshot holds (:mod:`api.evidence_text`), pairs every
sentence with its evidence text, and scores each pair with
**HHEM-2.1-Open** (``vectara/hhallucination_evaluation_model``), a local
cross-encoder. Nothing here calls an LLM API: the model loads from the local
Hugging Face cache, scoring runs on CPU, and the request can never block the
answer stream — by the time it runs, the stream is finished.

Aggregation follows the RAGAS definition at claim granularity:

- a claim (answer sentence) is **supported** when at least one of its cited
  evidence texts scores ≥ the threshold against it (the maximum over the
  claim's texts — the strongest supporting citation wins);
- ``faithfulness = supported_claims / claims_total`` over *all* sentences, so
  an uncited sentence is an unsupported claim exactly as the PRD example reads
  ("faithfulness 1.0 · 8/8 claims cited" implies 8 supported of 8);
- a claim whose evidence text cannot be resolved from the snapshot is reported
  with ``status: "unresolved"`` — counted as unsupported, never skipped.

The transformers/torch stack ships behind the ``faithfulness`` extra
(``pip install '.[faithfulness]'``); the import is lazy, so an image built
without the extra answers ``503`` with the install line instead of crashing —
and automated CI, which installs ``.[dev]`` only, never touches the model.

HHEM's logit is read as the pair's **consistency probability**
(``sigmoid(logit)``): closer to 1 = the evidence supports the sentence. The
polarity and the sanity check that pins it are recorded in
``docs/faithfulness-notes.md``.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from api import llm

logger = logging.getLogger(__name__)

#: The local cross-encoder that grounds the badge (PRD §8: RAGAS + HHEM-2.1-Open).
HHEM_MODEL_ID = "vectara/hhallucination_evaluation_model"

#: Claims scoring at/above this consistency probability count as supported.
DEFAULT_THRESHOLD = 0.5

THRESHOLD_ENV = "FAITHFULNESS_THRESHOLD"

#: HHEM's tokenizer input budget; premises are already bounded per evidence
#: text by :data:`api.evidence_text.EVIDENCE_TEXT_LIMIT`.
_MAX_LENGTH = 512

_BATCH_SIZE = 8

#: The scorer's ledger model name: a local model, so every row carries zero
#: cost — the badge is deliberately invisible to the $10 spend cap.
_SCORER_MODEL = "faithfulness:hhem-2.1-open"


class FaithfulnessUnavailableError(RuntimeError):
    """The local scorer stack is missing or the model cannot be loaded."""


class PairScorer(Protocol):
    """Batched premise/hypothesis → consistency probability in [0, 1]."""

    def score_pairs(
        self, premises: Sequence[str], hypotheses: Sequence[str]
    ) -> list[float]: ...


@dataclass(frozen=True, slots=True)
class ClaimInput:
    """One claim to score: the answer sentence and the evidence it cited."""

    sentence: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ClaimScore:
    """One claim's result: its score, verdict, and why it landed there."""

    sentence: str
    evidence_ids: tuple[str, ...]
    score: float | None
    supported: bool
    status: str  # "scored" | "uncited" | "unresolved" | "empty"


@dataclass(frozen=True, slots=True)
class FaithfulnessReport:
    """The badge payload: the RAGAS aggregate plus per-claim detail."""

    faithfulness: float | None
    claims_total: int
    claims_supported: int
    claims_scored: int
    claims_unresolved: int
    threshold: float
    model: str
    latency_ms: int
    claims: tuple[ClaimScore, ...]

    def payload(self) -> dict[str, Any]:
        return {
            "faithfulness": self.faithfulness,
            "claims_total": self.claims_total,
            "claims_supported": self.claims_supported,
            "claims_scored": self.claims_scored,
            "claims_unresolved": self.claims_unresolved,
            "threshold": self.threshold,
            "model": self.model,
            "latency_ms": self.latency_ms,
            "claims": [
                {
                    "sentence": claim.sentence,
                    "evidence_ids": list(claim.evidence_ids),
                    "score": claim.score,
                    "supported": claim.supported,
                    "status": claim.status,
                }
                for claim in self.claims
            ],
        }


def threshold_from_env() -> float:
    """The supported-claim threshold (``FAITHFULNESS_THRESHOLD`` or default)."""
    raw = os.environ.get(THRESHOLD_ENV, "").strip()
    if not raw:
        return DEFAULT_THRESHOLD
    value = float(raw)  # ValueError propagates: a broken override should be loud.
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{THRESHOLD_ENV}={raw!r} must be within [0, 1]")
    return value


def score_answer(
    claims: Sequence[ClaimInput],
    texts_by_id: dict[str, str],
    *,
    score_fn: PairScorer,
    threshold: float = DEFAULT_THRESHOLD,
) -> FaithfulnessReport:
    """Score every claim against its cited evidence text; aggregate RAGAS-style.

    ``texts_by_id`` maps evidence node ids to their real snapshot text (the
    endpoint builds it from the resolved evidence nodes). One batched
    cross-encoder call scores all pairs; for each claim its strongest (max)
    text score decides, mirroring "supported by which evidence".
    """
    started = time.monotonic()
    scored = _score_claims(claims, texts_by_id, score_fn, threshold)

    total = len(scored)
    report = FaithfulnessReport(
        faithfulness=(
            round(sum(1 for c in scored if c.supported) / total, 4) if total else None
        ),
        claims_total=total,
        claims_supported=sum(1 for c in scored if c.supported),
        claims_scored=sum(1 for c in scored if c.status == "scored"),
        claims_unresolved=sum(1 for c in scored if c.status == "unresolved"),
        threshold=threshold,
        model=_SCORER_MODEL,
        latency_ms=int((time.monotonic() - started) * 1000),
        claims=tuple(scored),
    )
    _append_ledger(report)
    return report


def _score_claims(
    claims: Sequence[ClaimInput],
    texts_by_id: dict[str, str],
    score_fn: PairScorer,
    threshold: float,
) -> list[ClaimScore]:
    """Classify each claim first, then score only the resolvable pairs in batch."""
    results: list[ClaimScore | None] = [None] * len(claims)
    claim_texts: dict[int, list[str]] = {}

    for index, claim in enumerate(claims):
        texts = [texts_by_id[eid] for eid in claim.evidence_ids if eid in texts_by_id]
        if not claim.sentence.strip():
            results[index] = ClaimScore(claim.sentence, (), None, False, "empty")
        elif not claim.evidence_ids:
            results[index] = ClaimScore(claim.sentence, (), None, False, "uncited")
        elif not texts:
            results[index] = ClaimScore(
                claim.sentence, claim.evidence_ids, None, False, "unresolved"
            )
        else:
            claim_texts[index] = texts

    if claim_texts:
        premises: list[str] = []
        hypotheses: list[str] = []
        for index, texts in claim_texts.items():
            premises.extend(texts)
            hypotheses.extend([claims[index].sentence] * len(texts))
        pair_scores = score_fn.score_pairs(premises, hypotheses)

        cursor = 0
        for index, texts in claim_texts.items():
            span = pair_scores[cursor : cursor + len(texts)]
            cursor += len(texts)
            best = max(span) if span else None
            results[index] = ClaimScore(
                sentence=claims[index].sentence,
                evidence_ids=claims[index].evidence_ids,
                score=round(best, 4) if best is not None else None,
                supported=best is not None and best >= threshold,
                status="scored",
            )
    return [claim for claim in results if claim is not None]


def _append_ledger(report: FaithfulnessReport) -> None:
    """One zero-cost ledger row per scoring request, named after the model.

    The ledger records *decisions*, and scoring is not one — but the row makes
    the scoring observable (digest, latency, verdict count) while provably
    costing nothing, and it never lands inside an /ask run's collection (a
    different request, a different thread).
    """
    llm.ledger_append(
        llm.LedgerRecord(
            input_digest=hashlib.sha256(
                "\x1f".join(claim.sentence for claim in report.claims).encode()
            ).hexdigest(),
            choice=report.claims_supported,
            confidence=report.faithfulness,
            model=_SCORER_MODEL,
            latency_ms=report.latency_ms,
            cost_usd=0.0,
            escalated=False,
        )
    )


class HHEMScorer:
    """The local HHEM-2.1-Open cross-encoder behind :data:`PairScorer`.

    ``transformers`` and ``torch`` import lazily inside :meth:`_load` — an
    image without the ``faithfulness`` extra stays import-clean. The model
    loads once per process; every batch of pairs is one tokenizer call.
    """

    def __init__(self, model_id: str = HHEM_MODEL_ID, batch_size: int = _BATCH_SIZE):
        self._model_id = model_id
        self._batch_size = batch_size
        self._lock = threading.Lock()
        self._loaded: tuple[Any, Any, Any] | None = None

    @property
    def model_id(self) -> str:
        return self._model_id

    def _load(self) -> tuple[Any, Any, Any]:
        if self._loaded is None:
            with self._lock:
                if self._loaded is None:
                    try:
                        import torch
                        from transformers import (
                            AutoModelForSequenceClassification,
                            AutoTokenizer,
                        )
                    except ImportError as exc:
                        raise FaithfulnessUnavailableError(
                            "the local HHEM scorer needs the 'faithfulness' "
                            "extra: pip install '.[faithfulness]'"
                        ) from exc
                    try:
                        tokenizer = AutoTokenizer.from_pretrained(self._model_id)
                        model = AutoModelForSequenceClassification.from_pretrained(
                            self._model_id
                        )
                        model.eval()
                    except Exception as exc:
                        logger.exception("failed to load %s", self._model_id)
                        raise FaithfulnessUnavailableError(
                            f"failed to load {self._model_id}: {exc}"
                        ) from exc
                    logger.info("loaded %s for local faithfulness scoring", self._model_id)
                    self._loaded = (model, tokenizer, torch)
        return self._loaded

    def score_pairs(
        self, premises: Sequence[str], hypotheses: Sequence[str]
    ) -> list[float]:
        """Score ``premises[i], hypotheses[i]`` pairs; P(consistent) per pair."""
        if len(premises) != len(hypotheses):
            raise ValueError("premises and hypotheses must be the same length")
        model, tokenizer, torch = self._load()
        scores: list[float] = []
        for start in range(0, len(premises), self._batch_size):
            batch_p = premises[start : start + self._batch_size]
            batch_h = hypotheses[start : start + self._batch_size]
            inputs = tokenizer(
                list(batch_p),
                list(batch_h),
                padding=True,
                truncation=True,
                max_length=_MAX_LENGTH,
                return_tensors="pt",
            )
            with torch.no_grad():
                logits = model(**inputs).logits
            scores.extend(
                float(value)
                for value in torch.sigmoid(logits).squeeze(-1).tolist()
            )
        return scores


_scorer: HHEMScorer | None = None
_scorer_lock = threading.Lock()


def get_scorer() -> HHEMScorer:
    """The process-wide scorer singleton (one model load per container)."""
    global _scorer
    with _scorer_lock:
        if _scorer is None:
            _scorer = HHEMScorer()
        return _scorer
