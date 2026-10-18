"""System-1/System-2 model wrappers over OpenRouter, the only provider.

``decide()`` asks a model for a typed choice — one-of-N labels, an integer
rating in a bounded range, or y/n — together with a self-reported (expected
calibrated) confidence in [0, 1]. The request carries a strict JSON schema
and the response is validated against it; unusable output is never guessed,
it triggers one retry on the small fallback model and then raises. When the
remaining confidence is below the escalation threshold, the same typed
question is handed to the S2 model and the result comes back with
``escalated=True``.

``reason()`` asks the S2 model for synthesis text and returns it verbatim.

``embed_documents()`` / ``embed_query()`` are the retrieval embeddings — the
only OpenRouter call that is neither ``decide`` nor ``reason``. They are not
ledger rows: the decision ledger tracks model *decisions*, and a retrieval that
embeds a query records its own row (with the embedding's cost/latency) at the
retrieval layer instead. ``embed_query`` returns the vector with its call trace
so that row can be honest.

Every completed decision call appends one :class:`LedgerRecord` (the locked
seven-field schema) via :func:`ledger_append`. Once the ledger's cumulative
``cost_usd`` reaches ``SPEND_CAP_USD``, new calls raise
:class:`SpendCapExceededError` before any HTTP request is made.

Configuration (all read at call time, so tests and config changes need no
restart):

- ``OPENROUTER_API_KEY`` — required at runtime; never needed offline because
  tests substitute the HTTP seam.
- ``DECIDE_MODEL_SLUG`` — S1 slug (default: ``FALLBACK_MODEL_SLUG``).
- ``REASON_MODEL_SLUG`` — S2 slug (default: ``FALLBACK_MODEL_SLUG``).
- ``EMBEDDING_MODEL_SLUG`` — embedding slug (default ``openai/text-embedding-3-small``).
- ``EMBEDDING_DIMENSION`` — embedding dimension (default 1536).
- ``SPEND_CAP_USD`` — hard stop on cumulative ledger cost (default 10).
"""

import hashlib
import json
import os
import threading
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Annotated, Literal, overload

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_EMBEDDINGS_URL = "https://openrouter.ai/api/v1/embeddings"
#: The Alpha Decisions endpoint serves "decisions-class" models (TypeSafe Jev,
#: Perplexity pplx-decider) that refuse chat/completions: typed questions with
#: per-option criteria, answered with real probability distributions.
OPENROUTER_DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"

#: S1 lane selection: "" (default) calls the chat/completions schema path;
#: "decisions" calls the typed Decisions endpoint above.
DECIDE_API_ENV = "DECIDE_API"

# The PRD's small-model fallback: cheap, widely available on OpenRouter, and
# reliable at emitting strict JSON. It is also the default slug for both
# lanes until pinning assigns a primary decision/reason model.
FALLBACK_MODEL_SLUG = "openai/gpt-4o-mini"

# The retrieval embeddings model. Document embeddings (committed at event time
# by ``ingest.embeddings``) and query embeddings must use the same slug and
# dimension or the FalkorDB vector index compares vectors from different spaces.
DEFAULT_EMBEDDING_MODEL_SLUG = "openai/text-embedding-3-small"
DEFAULT_EMBEDDING_DIMENSION = 1536

DEFAULT_SPEND_CAP_USD = 10.0

# S1 confidence strictly below this hands the step to the S2 model (PRD §6.2).
ESCALATION_THRESHOLD = 0.6

_REQUEST_TIMEOUT_S = 60.0


class ModelOutputError(RuntimeError):
    """The model returned nothing the strict contract can accept."""


class SpendCapExceededError(RuntimeError):
    """Cumulative ledger spend reached ``SPEND_CAP_USD``; new calls are refused."""


class EmbeddingError(RuntimeError):
    """The embeddings endpoint returned nothing the contract can accept."""


@dataclass(frozen=True, slots=True)
class DecideResult[TChoice: (str, int, bool)]:
    choice: TChoice
    confidence: float
    escalated: bool


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    """One query embedding plus the call's cost/latency for the ledger row."""

    vector: list[float]
    latency_ms: int
    cost_usd: float


class LedgerRecord(BaseModel):
    """The PRD-locked ledger row; later components parse this shape."""

    model_config = ConfigDict(extra="forbid")

    input_digest: str
    choice: str | bool | int
    confidence: Annotated[float, Field(ge=0.0, le=1.0)] | None
    model: str
    latency_ms: Annotated[int, Field(ge=0)]
    cost_usd: Annotated[float, Field(ge=0.0)]
    escalated: bool


_ledger_lock = threading.Lock()
_ledger: list[LedgerRecord] = []

#: Per-thread collector, active only while a run wraps its compute in
#: :func:`collect_ledger`. A run computes its whole plan synchronously on one
#: thread, so the rows it appends are exactly the rows this collects — never a
#: concurrent request's, which slicing the shared ledger by position would leak.
_ledger_local = threading.local()


@contextmanager
def collect_ledger() -> Iterator[list[LedgerRecord]]:
    """Collect the records appended on this thread until the block exits.

    Used by ``ask_events`` to attribute ledger rows to the run that produced
    them. Nested collection is not supported — one run, one collector.
    """
    records: list[LedgerRecord] = []
    _ledger_local.records = records
    try:
        yield records
    finally:
        del _ledger_local.records


def ledger_append(record: LedgerRecord) -> LedgerRecord:
    """Append one fully-formed record to the decision ledger."""
    with _ledger_lock:
        _ledger.append(record)
    collected = getattr(_ledger_local, "records", None)
    if collected is not None:
        collected.append(record)
    return record


def ledger_records() -> list[LedgerRecord]:
    with _ledger_lock:
        return list(_ledger)


def ledger_total_cost_usd() -> float:
    with _ledger_lock:
        return sum(record.cost_usd for record in _ledger)


@dataclass(frozen=True, slots=True)
class _CallTrace:
    """What one HTTP round-trip produced; ledger rows are built from it."""

    model: str
    input_digest: str
    content: str
    latency_ms: int
    cost_usd: float


@dataclass(frozen=True, slots=True)
class _OneOf:
    labels: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Rating:
    minimum: int
    maximum: int


@dataclass(frozen=True, slots=True)
class _YesNo:
    pass


_Shape = _OneOf | _Rating | _YesNo


@dataclass(frozen=True, slots=True)
class _TypedChoice:
    choice: str | bool | int
    confidence: float


def _post_openrouter(url: str, payload: dict[str, object]) -> object:
    """The one authenticated OpenRouter HTTP round-trip; the two named seams
    below validate its body shape and are the seams tests substitute."""
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is empty; OpenRouter is the only provider")
    response = httpx.post(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=_REQUEST_TIMEOUT_S,
    )
    response.raise_for_status()
    return response.json()


def _post_chat_completion(payload: dict[str, object]) -> dict[str, object]:
    """The single seam that talks to OpenRouter; tests substitute this."""
    data = _post_openrouter(OPENROUTER_URL, payload)
    if not isinstance(data, dict):
        raise ModelOutputError("OpenRouter returned a non-object response body")
    return data


def _model_slug(env_var: str) -> str:
    return os.environ.get(env_var, "").strip() or FALLBACK_MODEL_SLUG


def embedding_model_slug() -> str:
    """The configured embedding model slug (``EMBEDDING_MODEL_SLUG`` or default)."""
    return os.environ.get("EMBEDDING_MODEL_SLUG", "").strip() or DEFAULT_EMBEDDING_MODEL_SLUG


def embedding_dimension() -> int:
    """The configured embedding dimension (``EMBEDDING_DIMENSION`` or default)."""
    raw = os.environ.get("EMBEDDING_DIMENSION", "").strip()
    if not raw:
        return DEFAULT_EMBEDDING_DIMENSION
    try:
        dimension = int(raw)
    except ValueError:
        raise ValueError(f"EMBEDDING_DIMENSION={raw!r} is not an integer") from None
    if dimension < 1:
        raise ValueError(f"EMBEDDING_DIMENSION={raw!r} must be positive")
    return dimension


def _env_float(env_var: str, default: float) -> float:
    raw = os.environ.get(env_var, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        raise ValueError(f"{env_var}={raw!r} is not a number") from None


def _input_digest(model: str, prompt: str) -> str:
    return hashlib.sha256(f"{model}\x1f{prompt}".encode()).hexdigest()


def _completion_content(model: str, data: dict[str, object]) -> str:
    """Extract the completion text; empty text is a response like any other."""
    try:
        content: object = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ModelOutputError(f"{model} returned no completion content") from exc
    if not isinstance(content, str):
        raise ModelOutputError(f"{model} returned a non-text completion")
    return content


def _reported_cost(data: dict[str, object]) -> float:
    usage = data.get("usage")
    if isinstance(usage, dict):
        cost = usage.get("cost")
        if isinstance(cost, int | float) and not isinstance(cost, bool):
            return float(cost)
    return 0.0


def _enforce_spend_cap() -> None:
    cap = _env_float("SPEND_CAP_USD", DEFAULT_SPEND_CAP_USD)
    spent = ledger_total_cost_usd()
    if spent >= cap:
        raise SpendCapExceededError(
            f"ledger spend ${spent:.4f} reached SPEND_CAP_USD={cap:g}; "
            "refusing new OpenRouter calls"
        )


def _call_llm(
    *,
    model: str,
    prompt: str,
    response_format: dict[str, object] | None,
    temperature: float | None,
) -> _CallTrace:
    _enforce_spend_cap()
    payload: dict[str, object] = {"model": model, "messages": [{"role": "user", "content": prompt}]}
    if response_format is not None:
        payload["response_format"] = response_format
    if temperature is not None:
        payload["temperature"] = temperature
    started = time.monotonic()
    data = _post_chat_completion(payload)
    latency_ms = int((time.monotonic() - started) * 1000)
    content = _completion_content(model, data)
    return _CallTrace(
        model=model,
        input_digest=_input_digest(model, prompt),
        content=content,
        latency_ms=latency_ms,
        cost_usd=_reported_cost(data),
    )


def _selected_shape(
    one_of: Sequence[str] | None,
    rating: tuple[int, int] | None,
    yes_no: bool | None,
) -> _Shape:
    given = [
        name
        for name, value in (("one_of", one_of), ("rating", rating), ("yes_no", yes_no))
        if value is not None
    ]
    if len(given) != 1:
        raise ValueError(
            f"pass exactly one of one_of, rating, or yes_no (got {given or 'none'})"
        )
    if given[0] == "one_of":
        assert one_of is not None
        return _OneOf(labels=tuple(one_of))
    if given[0] == "rating":
        assert rating is not None
        return _Rating(minimum=rating[0], maximum=rating[1])
    assert yes_no is not None
    return _YesNo()


def _choice_model(shape: _Shape) -> type[BaseModel]:
    choice: object
    match shape:
        case _OneOf(labels=labels):
            if len(labels) < 2:
                raise ValueError("one_of requires at least two labels")
            choice = Literal[labels]
        case _Rating(minimum=minimum, maximum=maximum):
            if minimum >= maximum:
                raise ValueError("rating requires minimum < maximum")
            choice = Annotated[int, Field(ge=minimum, le=maximum)]
        case _YesNo():
            choice = bool
        case _:
            raise TypeError(f"unknown shape {shape!r}")
    confidence = Annotated[float, Field(ge=0.0, le=1.0)]
    return create_model(
        "TypedDecision",
        __config__=ConfigDict(extra="forbid"),
        choice=(choice, ...),
        confidence=(confidence, ...),
    )


def _json_schema_response_format(model_cls: type[BaseModel]) -> dict[str, object]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "typed_decision",
            "strict": True,
            "schema": model_cls.model_json_schema(),
        },
    }


def _trace_to_record(
    trace: _CallTrace,
    choice: str | bool | int,
    confidence: float | None,
    escalated: bool,
) -> LedgerRecord:
    return LedgerRecord(
        input_digest=trace.input_digest,
        choice=choice,
        confidence=confidence,
        model=trace.model,
        latency_ms=trace.latency_ms,
        cost_usd=trace.cost_usd,
        escalated=escalated,
    )


@overload
def decide(prompt: str, *, one_of: Sequence[str]) -> DecideResult[str]: ...


@overload
def decide(prompt: str, *, rating: tuple[int, int]) -> DecideResult[int]: ...


@overload
def decide(prompt: str, *, yes_no: bool) -> DecideResult[bool]: ...


def decide(
    prompt: str,
    *,
    one_of: Sequence[str] | None = None,
    rating: tuple[int, int] | None = None,
    yes_no: bool | None = None,
    criteria: Mapping[str | int, str] | Sequence[str] | None = None,
) -> DecideResult[str | int | bool]:
    """System-1 typed decision: 1-of-N, bounded rating, or y/n + confidence.

    Malformed schema-violating output retries once on ``FALLBACK_MODEL_SLUG``
    and then raises :class:`ModelOutputError`. Confidence below the escalation
    threshold re-asks the same typed question on the S2 model; the returned
    result and every record on that escalation path carry ``escalated=True``.

    Lane selection: with ``DECIDE_API=decisions`` the S1 call goes to the
    Decisions endpoint (:func:`_decide_via_decisions`) — decisions-class models
    (TypeSafe Jev, Perplexity pplx-decider) answer with *measured* probability
    distributions over the option criteria instead of a self-reported JSON
    confidence. ``criteria`` carries the per-option descriptions that lane
    needs; the chat lane ignores it. On any Decisions failure the ladder falls
    back to the chat path on ``FALLBACK_MODEL_SLUG``.
    """
    shape = _selected_shape(one_of=one_of, rating=rating, yes_no=yes_no)
    model_cls = _choice_model(shape)
    response_format = _json_schema_response_format(model_cls)
    pending: list[tuple[_CallTrace, str | bool | int, float | None, bool]] = []

    def attempt(slug: str, escalated: bool) -> _TypedChoice:
        trace = _call_llm(
            model=slug,
            prompt=prompt,
            response_format=response_format,
            temperature=0.0,
        )
        try:
            verdict = model_cls.model_validate_json(trace.content)
        except ValidationError as exc:
            pending.append((trace, trace.content, None, escalated))
            raise ModelOutputError(f"{slug} did not return schema-valid JSON: {exc}") from exc
        pending.append((trace, verdict.choice, verdict.confidence, escalated))
        return _TypedChoice(choice=verdict.choice, confidence=verdict.confidence)

    try:
        try:
            if decisions_api_enabled():
                s1 = _decide_via_decisions(
                    shape, model_cls, prompt, criteria, pending, escalated=False
                )
            else:
                s1 = attempt(_model_slug("DECIDE_MODEL_SLUG"), escalated=False)
        except ModelOutputError:
            s1 = attempt(FALLBACK_MODEL_SLUG, escalated=False)

        if s1.confidence < ESCALATION_THRESHOLD:
            trace, choice, confidence, _ = pending[-1]
            pending[-1] = (trace, choice, confidence, True)
            try:
                s2 = attempt(_model_slug("REASON_MODEL_SLUG"), escalated=True)
            except ModelOutputError:
                s2 = attempt(FALLBACK_MODEL_SLUG, escalated=True)
            return DecideResult(choice=s2.choice, confidence=s2.confidence, escalated=True)
        return DecideResult(choice=s1.choice, confidence=s1.confidence, escalated=False)
    finally:
        for trace, choice, confidence, escalated in pending:
            ledger_append(_trace_to_record(trace, choice, confidence, escalated))


def decisions_api_enabled() -> bool:
    """Whether the S1 lane is set to the Decisions endpoint (``DECIDE_API``)."""
    return os.environ.get(DECIDE_API_ENV, "").strip().lower() == "decisions"


def _post_decisions(payload: dict[str, object]) -> dict[str, object]:
    """The single seam that talks to the Alpha Decisions endpoint; tests substitute."""
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise ModelOutputError(
            "OPENROUTER_API_KEY is empty; OpenRouter is the only provider"
        )
    response = httpx.post(
        OPENROUTER_DECISIONS_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json=payload,
        timeout=_REQUEST_TIMEOUT_S,
    )
    if response.status_code != 200:
        try:
            detail = str(response.json().get("error", response.status_code))[:200]
        except Exception:  # noqa: BLE001 — any body shape degrades to the status
            detail = str(response.status_code)
        raise ModelOutputError(f"decisions endpoint returned {response.status_code}: {detail}")
    data = response.json()
    if not isinstance(data, dict):
        raise ModelOutputError("decisions endpoint returned a non-object body")
    return data


def _criteria_glosses(
    labels: Sequence[str], criteria: Mapping[str | int, str] | Sequence[str] | None
) -> dict[str, str]:
    """Per-option descriptions: caller-supplied, else the labels themselves."""
    if isinstance(criteria, Mapping):
        return {str(label): str(criteria.get(label, label)) for label in labels}
    seq = [str(item) for item in (criteria or [])]
    return {
        label: (seq[index] if index < len(seq) else str(label))
        for index, label in enumerate(labels)
    }


def _decisions_question(
    shape: _Shape, prompt: str, criteria: Mapping[str | int, str] | Sequence[str] | None
) -> dict[str, object]:
    """Map the decide() shape onto a Decisions question typed by the endpoint."""
    if isinstance(shape, _OneOf):
        return {
            "q": {
                "type": "choice",
                "instructions": prompt,
                "criteria": _criteria_glosses(list(shape.labels), criteria),
            }
        }
    if isinstance(shape, _Rating):
        values = list(range(shape.minimum, shape.maximum + 1))
        if isinstance(criteria, Mapping):
            glosses = [str(criteria.get(value, value)) for value in values]
        else:
            seq = [str(item) for item in (criteria or [])]
            glosses = [
                seq[index] if index < len(seq) else str(value)
                for index, value in enumerate(values)
            ]
        return {
            "q": {
                "type": "score",
                "instructions": prompt,
                "criteria": glosses,
            }
        }
    glosses = criteria if isinstance(criteria, Mapping) else {}
    return {
        "q": {
            "type": "noul",
            "instructions": prompt,
            "criteria": {
                "true": str(glosses.get("true", "the statement holds")),
                "false": str(glosses.get("false", "the statement does not hold")),
            },
        }
    }


def _decisions_typed_choice(
    shape: _Shape, model_cls: type[BaseModel], data: dict[str, object], model: str
) -> _TypedChoice:
    """Parse one ``q`` answer into the same typed contract the chat lane yields.

    ``choice`` answers carry a label plus a measured probability distribution
    (the confidence field is the winner's probability); ``score`` answers a
    float on the scale (rounded to the nearest integer step and clamped);
    ``noul`` answers the probability that the statement holds, from which the
    boolean and its confidence are read.
    """
    answers = data.get("answers")
    entry = answers.get("q") if isinstance(answers, dict) else None
    if not isinstance(entry, dict):
        raise ModelOutputError(f"{model} decisions response carried no 'q' answer")

    kind = entry.get("type")
    try:
        if kind == "choice":
            choice: str | bool | int = str(entry["choice"])
            confidence = float(entry["confidence"])
        elif kind == "score":
            score = float(entry["score"])
            if isinstance(shape, _Rating):
                score = min(max(score, shape.minimum), shape.maximum)
            choice = round(score)  # rounds to a valid scale step; already numeric
            confidence = float(entry["confidence"])
        elif kind == "noul":
            probability = float(entry["noul"])
            choice = probability >= 0.5
            confidence = max(probability, 1.0 - probability)
        else:
            raise ModelOutputError(
                f"{model} decisions response had unknown answer type {kind!r}"
            )
    except (KeyError, TypeError, ValueError) as exc:
        raise ModelOutputError(f"{model} decisions answer malformed: {exc}") from exc

    try:
        verdict = model_cls.model_validate_json(
            json.dumps({"choice": choice, "confidence": confidence})
        )
    except ValidationError as exc:
        raise ModelOutputError(
            f"{model} decisions answer violates the typed contract: {exc}"
        ) from exc
    return _TypedChoice(choice=verdict.choice, confidence=verdict.confidence)


def _decide_via_decisions(
    shape: _Shape,
    model_cls: type[BaseModel],
    prompt: str,
    criteria: Mapping[str | int, str] | Sequence[str] | None,
    pending: list[tuple[_CallTrace, str | bool | int, float | None, bool]],
    *,
    escalated: bool,
) -> _TypedChoice:
    """One S1 decision through the Decisions endpoint; ledger row on completion."""
    _enforce_spend_cap()
    slug = _model_slug("DECIDE_MODEL_SLUG")
    payload = {
        "model": slug,
        "questions": _decisions_question(shape, prompt, criteria),
        "state": {"prompt": prompt},
    }
    started = time.monotonic()
    data = _post_decisions(payload)
    latency_ms = int((time.monotonic() - started) * 1000)
    typed = _decisions_typed_choice(shape, model_cls, data, slug)
    usage = data.get("usage")
    trace = _CallTrace(
        model=slug,
        input_digest=_input_digest(f"decisions:{slug}", prompt),
        content=json.dumps({"answers": data.get("answers"), "type": typed.choice}, default=str),
        latency_ms=latency_ms,
        cost_usd=(
            float(usage["cost"])
            if isinstance(usage, dict) and isinstance(usage.get("cost"), int | float)
            else 0.0
        ),
    )
    pending.append((trace, typed.choice, typed.confidence, escalated))
    return typed


def reason(prompt: str) -> str:
    """System-2 synthesis via OpenRouter; returns the model's text verbatim.

    An empty completion is returned as-is: the row lands in the ledger and
    the caller decides what a silent synthesis means.
    """
    trace = _call_llm(
        model=_model_slug("REASON_MODEL_SLUG"),
        prompt=prompt,
        response_format=None,
        temperature=None,
    )
    ledger_append(
        _trace_to_record(
            trace, choice=trace.content, confidence=None, escalated=False
        )
    )
    return trace.content


def _post_embeddings(payload: dict[str, object]) -> dict[str, object]:
    """The single seam that talks to OpenRouter's embeddings endpoint."""
    data = _post_openrouter(OPENROUTER_EMBEDDINGS_URL, payload)
    if not isinstance(data, dict):
        raise EmbeddingError("OpenRouter returned a non-object embeddings body")
    return data


def _embedding_vectors(model: str, data: dict[str, object]) -> list[list[float]]:
    """Extract vectors in input order; a malformed item is never guessed at."""
    items = data.get("data")
    if not isinstance(items, list) or not items:
        raise EmbeddingError(f"{model} returned no embeddings")
    ordered: list[tuple[int, list[float]]] = []
    for item in items:
        if not isinstance(item, dict):
            raise EmbeddingError(f"{model} returned a malformed embedding item")
        vector = item.get("embedding")
        index = item.get("index")
        if not isinstance(vector, list) or not all(
            isinstance(value, int | float) and not isinstance(value, bool)
            for value in vector
        ):
            raise EmbeddingError(f"{model} returned a non-numeric embedding vector")
        if not isinstance(index, int):
            raise EmbeddingError(f"{model} returned an embedding without an index")
        ordered.append((index, [float(value) for value in vector]))
    ordered.sort(key=lambda pair: pair[0])
    return [vector for _, vector in ordered]


def _request_embeddings(texts: Sequence[str]) -> tuple[list[list[float]], int, float]:
    _enforce_spend_cap()
    model = embedding_model_slug()
    dimension = embedding_dimension()
    payload: dict[str, object] = {
        "model": model,
        "input": list(texts),
        "dimensions": dimension,
    }
    started = time.monotonic()
    data = _post_embeddings(payload)
    latency_ms = int((time.monotonic() - started) * 1000)
    vectors = _embedding_vectors(model, data)
    for vector in vectors:
        if len(vector) != dimension:
            raise EmbeddingError(
                f"{model} returned a {len(vector)}-dim vector, expected {dimension}"
            )
    return vectors, latency_ms, _reported_cost(data)


def embed_documents(texts: Sequence[str]) -> list[list[float]]:
    """Embed a batch of documents: one vector per input, in input order."""
    vectors, _, _ = _request_embeddings(texts)
    if len(vectors) != len(texts):
        raise EmbeddingError(
            f"embeddings endpoint returned {len(vectors)} vectors for {len(texts)} inputs"
        )
    return vectors


def embed_query(text: str) -> EmbeddingResult:
    """Embed one query; the returned trace feeds the retrieval ledger row."""
    vectors, latency_ms, cost_usd = _request_embeddings([text])
    if len(vectors) != 1:
        raise EmbeddingError(
            f"embeddings endpoint returned {len(vectors)} vectors for one input"
        )
    return EmbeddingResult(vector=vectors[0], latency_ms=latency_ms, cost_usd=cost_usd)
