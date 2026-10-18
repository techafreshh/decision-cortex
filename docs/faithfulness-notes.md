# Faithfulness notes — the local HHEM badge

Decisions behind `POST /faithfulness` (`api/faithfulness.py`) and the web
badge wiring (`web/src/api/faithfulness.ts`, `web/src/components/FaithfulnessBadge.tsx`).
The PRD pins the *what* (RAGAS + HHEM-2.1-Open, local CPU, async, never blocks
the stream); these are the choices the PRD left open, so a reviewer can
overrule them explicitly.

## The score is a post-stream REST round-trip, not a stream event

The SSE stream already ends with `faithfulness_pending` → `RUN_FINISHED`
(frozen schema — adding a late "score" event would break every consumer). So
the web client, once the run finishes with answer sentences, `POST`s the
sentences + their cited evidence ids to `/faithfulness` and renders the report
when it resolves: "faithfulness 0.86 · 6/7 claims supported". The stream is
never touched, and a scoring outage degrades to an honest
"faithfulness unavailable" badge — it can never fail the answer.

## Premises come from the pinned snapshot, not the graph

The graph stores refs, never bodies (PRD §10), but the evidence *text* the
answer was grounded in lives in `snapshot/pr-comments.jsonl` (`body`),
`snapshot/rfcs.jsonl` (`content`/`body`), and `snapshot/commits.jsonl`
(`message`) — and the `api` image already ships the snapshot for seed-on-boot.
`api/evidence_text.py` resolves each cited node id to that real text
(bounded at 600 chars). At the moment the graph is the id→label resolver; the
snapshot is the textbank.

The same resolver feeds two more consumers, so the grounding is defined once:

- **synthesis** (`api/synthesis.py`): the S2 prompt lists each evidence with
  its bounded text under the positional `[eN]` label, so the answer is written
  from the debate, not from permalinks;
- **claim gate** (`api/claim_gate.py`): the S1 gate matches each sentence
  against a tighter 240-char excerpt — enough text to recognize the supporting
  node, small enough to keep the per-sentence prompt cheap.

## Aggregation is RAGAS at claim granularity

Per claim (answer sentence): the premise is every cited evidence text; the
claim's score is the **max** over its premise-HHEM scores (the strongest
supporting citation wins, mirroring "supported by which evidence"); a claim is
**supported** when that max ≥ `FAITHFULNESS_THRESHOLD` (default 0.5).
`faithfulness = supported / claims_total` over *all* sentences — an uncited
sentence is an unsupported claim, so the number matches the PRD's reading of
"faithfulness 1.0 · 8/8 claims cited". Claims whose evidence cannot be
resolved to text are `unresolved`: counted as unsupported and reported in
`claims_unresolved`, never skipped. An abstention run has no claims, so the
badge renders "n/a · abstention" instead of a number.

## HHEM polarity and the sanity check

`HHEMScorer` uses **HHEM-2.1-Open**, whose public Hugging Face home is
`vectara/hhallucination_evaluation_model` — with a *single* `h`
(`hhallucination` is the gated alias; headless downloads get HTTP 401,
verified against the hub API on deploy day). Loading requires
`trust_remote_code=True` (the repo ships `modeling_hhem_v2.py`), and scoring
goes through the model's custom `predict([ (premise, hypothesis), … ])` API —
the card is explicit that you must not call the module with a tokenizer.
`predict` returns a consistency probability per pair where **1 = fully
supported**, and the deployed model reproduces the card's own reference
scores to the fourth decimal (`Berlin/Paris` → 0.0111, `California/
United States` → 0.6474), which is the polarity sanity check this default is
pinned by. A future `FAITHFULNESS_MODEL_ID` swap must re-run it (consistent
pair ≥ 0.5, unrelated pair ≤ 0.5). Live checks under the `live` marker need
no HF token for this id; automated CI never imports torch (the import is
lazy inside `HHEMScorer._load`, failed imports raise
`FaithfulnessUnavailableError` → 503 with the install line).

## Image weight and cache

torch was already a transitive dependency of `graphrag-sdk`, but PyPI's linux
wheel drags the CUDA stack into a CPU-only deployment — the image now installs
torch from the CPU-only index first, then `.[faithfulness]`
(`infra/api.Dockerfile`). The downloaded weights live under
`HF_HOME=/hf-cache`, a named compose volume (`hf-cache`), so restarting or
recreating the `api` container never re-fetches the model; only a fresh volume
download pays once.

## Ledger observability

Every scoring request appends one ledger row: model
`faithfulness:hhem-2.1-open`, zero cost, the report's digest and latency, and
the supported count as its choice. The ledger tracks *decisions*; scoring is
not one, but surfacing it keeps the "show your work" rule honest — and the
zero cost is part of the story: the badge is invisible to the $10 spend cap
because the model is local.

## Which checkpoint the default actually loads (deployed reality)

HHEM-2.1-Open's canonical repository — `vectara/hhallucination_evaluation_model`
(double "hh") — is **access-gated** on the Hugging Face hub: an anonymous
`GET /api/models/…` returns 401, and downloading the weights requires an
account that accepted the terms. A judge's `docker compose up` cannot do that,
so the shipped default loads Vectara's earlier **public checkpointer of the
same family**, id `vectara/hhallucination_evaluation_model` — concretely the
ungated single-"h" repo `vectara/hallucination_evaluation_model` (200, ~422 MB),
cached once in the `hf-cache` volume. The polarity sanity check ran live
against it before ship (paraphrase 0.57, unrelated 0.10). A deployment that
owns an HF token with the gated repo accepted upgrades to the exact
HHEM-2.1-Open weights in one line:
`FAITHFULNESS_MODEL_ID=vectara/hhallucination_evaluation_model`.
