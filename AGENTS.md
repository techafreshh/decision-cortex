# AGENTS.md — Decision Cortex (Track 3) project rules

Rules every agent must follow when working in this repository. If you are new,
read the two files below **before** changing anything:

1. `.agents/PRDs/PRD.md` — the PRD: the single product spec (scope, schema,
   phases, API sketch, success criteria)
2. `AGENTS.md` — this file: project rules, workstreams, demo beats, judge crib

Conflict rule: the PRD wins over agent improvisation. If you believe a conflict
forces you off-plan, **stop and ask** — do not silently decide. (The original
Track 3 brief and the shared battle-plan README were removed by the owner;
their content is fully consolidated into the PRD and this file.)

## Project overview

- **Product:** Decision Cortex — a company brain over the real `rust-lang/rfcs`
  corpus (~600 decision records): claim-level-cited answers, abstention with
  receipts, Impact Explorer, Timeline — all on FalkorDB as the primary graph DB.
- **Event:** Graph Hacks (WeMakeDevs × FalkorDB), **Oct 15–18, 2026**, submissions
  close **11:59 PM IST Oct 18**. Solo entrant (Techa), three parallel tracks —
  this is Track 3. Every agent's work feeds a live submission; breaking
  assumptions, burning budget, or re-doing locked decisions costs real prize
  contention (Track prize: M6 Mac Mini).

## Event compliance — hard rules, never bend

1. **FalkorDB is the primary graph DB and the center of the product.** No
   Postgres/SQLite/pgvector substitution, no in-memory graph side-channel.
2. **The graph must shape agent behavior** (router, claim gates, impact walks,
   sufficiency stops all read the graph) — it is never garnish on top of RAG.
3. **The FalkorDB implementation (schema, queries, agent loop) must be new work
   done during the event.** See "Prep line" below for what is legal before Oct 15.
4. **The owner must be able to explain everything.** No one-letter magic, no
   unexplained heuristics, no "the agent probably handles it". Every nontrivial
   decision gets a line in `docs/` (or the submission README) in plain language.
5. **Live deployment preferred; the demo video is recorded regardless.** Both
   workstreams must stay viable at all times.

## Prep line (date-sensitive — actually check `date`)

- **Before Oct 15 (event start):** legal work is scaffold, AGENTS.md,
  CI, parsers emitting **plain dicts (no FalkorDB calls)**, the JSONL snapshot
  pipeline, verification-set authoring, prompt drafts, UI mockups, shared
  component-kit skeleton. **You must not write schema/queries into FalkorDB or
  implement the agent loop** — that work happens during the event.
- During Phase 0 the snapshot (Day-0 spike) must be **pinned by Oct 14**. If
  ingestion is at risk by end of Day 1 (Oct 15), the fictional-corpus fallback
  may be switched **only by explicit owner decision** — never silently.

## Locked decisions (do not re-litigate)

- **LLMs via OpenRouter only**, two decision wrappers: `decide()` (typed
  System-1 outputs: 1-of-N / 0–5 / y-n + calibrated confidence) and `reason()`
  (System-2 synthesis). Escalation: S1 confidence < threshold → S2. Every
  *decision* call lands in the **decision ledger** (input digest, choice,
  confidence, model, latency, cost, escalated flag). The retrieval embeddings
  (`embed_documents()` / `embed_query()`) are not ledger rows: document
  embeddings are the one-time ingestion step, and a query embedding records its
  cost and latency on the retrieval layer's own row. S1 slug is TBD at build;
  the **default config is the small-model strict-JSON fallback** behind the same
  interface.
- **App language: Python** (FastAPI). FalkorDB 6.x is the graph. Rust/Go only
  for benchmark-harness cosmetics, never the app.
- **UI: React + Vite plain SPA + CopilotKit + AG-UI (SSE)** — no Next.js, no
  SSR. Static bundle served by Caddy. Generative UI: every backend tool call
  renders as a registered component (render props). AG-UI wiring ladder:
  LangGraph-native adapter → official AG-UI Python SDK on FastAPI → hand-rolled
  SSE with the same event schema (UI unchanged).
- **Deployment:** Docker Compose (`falkordb` with volume + `api` + `web`) +
  Caddy HTTPS on the VPS; seed-on-boot; one-command local run
  (`docker compose up --build` + `.env` with one OpenRouter key).
- **Corpus:** real rust-lang/rfcs data. No synthetic substitutions.

## Budget doctrine (hard cap: $10 OpenRouter per deploy)

- S1 `decide()` for all typing/classification/rating; S2 `reason()` only for
  synthesis, impact narratives, no-record verdicts.
- Extraction (ingestion) uses the **cheap model in batches**; extractions are
  cached and re-used; the committed snapshot makes judge replay ≈ **$0**.
- Demo queries are answer-cached; backup footage uses the pre-baked dev cache.
- `SPEND_CAP_USD=10` is a guard, not decoration — ledger cost is surfaced live
  in the UI footer. If a change risks clearly exceeding the doctrine (e.g.,
  calling S2 where S1 was designed to be enough), it needs owner approval.

## Ingestion & graph integrity (correctness rules)

- **Every ingestion write is idempotent** (re-`MERGE`-on-`id` no-op; the
  GraphRAG-SDK `apply_changes` file-content-hash path is *not* used — see
  `docs/graph-schema-notes.md`). Multiple agents may write concurrently — never
  assume you are the only writer; never "fix" duplication by deleting nodes
  manually.
- **Provenance honesty:** every message kept in the graph keeps its
  `truncated: bool` flag; PR-comment harvest stays capped at ~100 per PR; never
  quietly drop truncation to make an answer look complete.
- **Stance edges** (`OBJECTED|SUPPORTED|MODERATED`) always carry `{evidence,
  confidence}` and must remain jumpable to their source comment. Do not collapse
  or "clean up" low-confidence stances away — flagging is the design.
- **Verification set honesty:** the 30 gold + 10 no-record questions in
  `verification/` are corpus-verified. Adding or changing a question requires
  the same verification (search the corpus; record the method). Never edit the
  set to make a failing metric pass.

## Scope guards (from PRD §4 out-of-scope; enforced in code review)

- `rust-lang/rust` issues sub-corpus: **stretch only** (Day 3+, only if
  ingestion + answer pipeline + polish are all green). Do not start it earlier.
- Text-to-Cypher is a **display flourish (CypherPeek)**, never the retrieval
  backbone. Retrieval = vector seed + full-text + multi-hop FalkorDB traversal.
- QueryWeaver (Text2SQL) is a name-drop, not a dependency.
- MCP via `@falkordb/mcpserver` is a **read-only peephole**; the web app is the
  product surface. No write-path APIs, no auth/multi-tenancy, no GPU
  assumptions (VPS is CPU-only → HHEM badge scores async, never blocking the
  answer stream).

## Demo determinism

- Seed-on-boot: empty graph → fast-mode replay of the committed snapshot.
- Scripted verification-set buttons first ("Ask the corpus", "Prove the
  negative", "Impact tour", "The async/await story"), free chat second.
- Any change that alters a scripted scenario's expected output must update the
  cached answers and be gated behind a rehearsal.

## Repository layout (planned — PRD §6.3)

```
snapshot/      committed one-time JSONL corpus (rfcs, pr-comments, commits)
ingest/        parsers (plain dicts) + GraphRAG-SDK ingestion
api/           FastAPI agent core (router, gates, retrieval, S2, ledger)
web/           React + Vite SPA + CopilotKit components + shared kit
verification/  30 gold + 10 no-record questions + eval runner
infra/         docker-compose.yml, Caddyfile, .env.example, CI
docs/          submission README, schema reference, blog seed
scripts/       factory verification entrypoints (run_scenario_api.sh)
```

Create these dirs only when the phase that needs them starts; never invent new
top-level dirs without updating this section. **The repo is a git repository**
(origin: `github.com/techafreshh/decision-cortex`, private until
submission) — agents work behind review + commit (never force-push, never
rebase shared branches mid-event). **CI** (green-lit by the owner): four
workflows under `.github/workflows/` — `ci.yml` (ruff + offline pytest, web
build), `falkordb-integration.yml` (real FalkorDB service container; activates
with Phase-1 code), `compose-smoke.yml` (activates with `infra/`), and
`eval-run.yml` (owner-dispatched only, spend-capped key from repo secrets,
never on push/PR). Rules: automated CI makes **zero LLM calls**
(`OPENROUTER_API_KEY` hard-emptied; tests needing the real API carry the
`live` marker and run only via `eval-run`); don't add new workflow files
without owner sign-off.

## Commands

```bash
pip install -e '.[dev]'       # install api package + lint/test tooling
ruff check .                  # lint (CI: ci.yml python job)
pytest -q -m 'not integration and not live'   # offline unit tests
scripts/run_scenario_api.sh <scratch_dir> <port>  # boot + readiness-probe /healthz
# planned, pending their phases:
docker compose up --build     # full local brain (falkordb + api + web) — infra/ pending
npm --prefix web run build    # UI static bundle — web/ pending
# snapshot pull (Phase 0 only; needs vault GITHUB_TOKEN, rate-limit-safe)
```

Key files: `.agents/PRDs/PRD.md` and this `AGENTS.md`. There is no
submission-README yet — it is a Phase 4 deliverable under `docs/` (deliverable
README with positioning, schema, verification-set results, methodology).

## Agent workflow in this repo

1. Plan non-trivial work first (plan2 skill against the PRD; small fixes may
   skip with a stated reason).
2. Implement via the `implement` skill's validation loops; keep deliverables
   mapped to PRD phase checkboxes.
3. Review (`review` skill) before committing; `commit` skill for messages.
4. Track decisions/justifications for the `postmortem` skill (feeds the
   submission README's "explain everything" story and blog seed).
5. UI changes get exercised through the `web-gui-tester` (browser) check —
   chips open real sources; NoRecordCard receipts render; scripted buttons hit
   cached answers.

## Workstream split (round-the-clock agents — Phases 0–4)

One lane per agent. Task state lives in the PRD's phase checkboxes — tick them
as work completes. Cross-lane changes (graph schema, API contract) land in the
PRD (§15.3 / §10) **before** code.

- **W1 ingest** — snapshot pipeline → parsers → GraphRAG-SDK ingestion →
  FalkorDB → idempotency checks (Phase 0 spike → Phase 1)
- **W2 agent** — `decide()`/`reason()` wrappers, router, retrieval, claim
  gates, abstention, ledger (Phase 2)
- **W3 UI** — shared kit, AnswerCard/SourcePanel, ImpactGraph, Timeline,
  faithfulness badge (Phases 2–3)
- **W4 ops** — compose, Caddy, CI, spend guard, exports, deploy, rehearsals
  (Phase 0 → Phase 3)
- **W5 docs & video** — submission README, verification-run transcript, demo
  video, blog seed (Phase 4)

Concurrency rules: every graph write is idempotent; one lane per branch;
commits land after review; no force-push or interactive rebase of shared
branches; only W4 touches `infra/`.

## Demo script beats (4-minute video — the shape every agent must preserve)

1. **0:00–0:25** — "600 decisions, 30k debate comments, one question box." Open on `rust-lang/rfcs`.
2. **0:25–1:15** — "What did the language team decide about trait objects, and who objected?" → AnswerCard builds sentence-by-sentence; chips fly open to real comments; faithfulness badge lands.
3. **1:15–2:00** — **The negative-proof moment:** "Did Rust ever decide to require attachments in `unsafe` code?" → NoRecordCard with search receipts; then the twist — "…but three proposals came close" with their evidence trails. Flash the Vector-RAG ablation: the same question hallucinating a plausible-but-fake answer on chunk-embeddings.
4. **2:00–3:00** — Impact Explorer on async/await; timeline animates the supersede chain across real RFC numbers (pick the concrete chain at build time); CypherPeek flash.
5. **3:00–4:00** — router/ledger close-up (System-1 economics), "bring your own corpus" teaser, URL + one-command local run.

Any change that breaks one of these beats (cached answers, button names,
NoRecordCard fields) is a W5-coordination change, not a local one.

## Judge Q&A crib (owner must be able to answer these cold)

- **Why a graph and not full-text search?** Decisions, objections, and
  supersession are *relationships*; search can't ask "who objected" or "what
  does this decision touch". Show the NoRecordCard receipts.
- **Why this corpus?** Public (no privacy walls), canonical identity (GitHub
  handles, RFC numbers), visceral debates; the MADR-shaped schema maps to any
  org — that's the portability story.
- **How do we trust answers?** Claim-level gates with calibrated confidence,
  per-sentence citations, a real RAGAS/HHEM faithfulness badge, and abstention
  over unsupported claims — receipts for the *negative* prove the pipeline
  doesn't confabulate.
- **Why System-1 routing economics?** Three typed `decide()` gates per answer
  (router, per-claim, relevance) at decision-model cost; the decision ledger
  shows those economics live.
- **What's new during the event?** All FalkorDB schema/queries/agent logic;
  snapshot + parsers + prompts prepped before (rule-clean, per the prep line).
