# PRD — Decision Cortex (Track 3: Company Brain)

| | |
|---|---|
| **Product** | Decision Cortex — a company brain over real decision records |
| **Event** | Graph Hacks: Context for AI Agents — WeMakeDevs × FalkorDB · Oct 15–18, 2026 |
| **Deadline** | Submissions close 11:59 PM IST, Oct 18, 2026 |
| **Entrant** | Techa (solo · all three tracks; this doc covers Track 3 — prize: M6 Mac Mini) |
| **Status** | Approved for implementation planning · Oct 13, 2026 |
| **Sources** | Owner decisions of Oct 13. The original Track 3 brief and shared battle-plan README were removed by the owner; their content is consolidated into this PRD + `AGENTS.md` |
| **Next step** | Implementation plan (`/plan .agents/PRDs/PRD.md`) → build |

---

## 1. Executive Summary

Enterprise knowledge tools (Glean et al.) retrieve documents; they don't model **decisions** — what was decided, by whom, over what objection, superseded by what. **Decision Cortex** is an open, graph-native, citation-first company brain built on the hardest test case available: **rust-lang/rfcs**, an organization whose decisions are all public and all disputed. ~600 real decision records, ~30k debate-thread comments, decades of supersession — unified in **FalkorDB** where every `Decision` node hangs off its evidence (RFC text, PR comments, FCP votes, revisions).

The core value proposition has three parts. **(a) Provenance by construction:** answers are synthesized from graph evidence, and every sentence carries a **citation chip** that opens the exact source — the RFC section, the GitHub comment, the commit — not a "references" list bolted on afterwards. **(b) Impact analysis is a traversal:** "what touches async trails?" is a multi-hop graph walk, and the Impact Explorer renders the blast radius live. **(c) The agent can prove a negative:** "there is no record we ever decided that" is a first-class answer — the `NoRecordCard` shows the receipts (N nodes searched, M evidence chains, 0 matches), which no RAG stack can honestly claim.

**MVP goal statement:** By 11:59 PM IST on Oct 18, ship a live URL where a judge can ask anything over the RFC corpus, get chip-cited answers with a real-time faithfulness badge (RAGAS + HHEM), fire the 10 no-record questions and watch principled abstention with receipts, walk the Impact Explorer and Timeline on real supersede chains, and run the whole brain locally with `docker compose up --build` + one OpenRouter key — **replaying the demo at $0 LLM cost** — plus a 4-minute video featuring the negative-proof moment.

**Positioning paragraph:** Microsoft GraphRAG is in maintenance mode; LightRAG (40k★) is the current wave. Neither does decisions-with-provenance or principled abstention as first-class UX. Glean sells this closed-source with 275 connectors; Decision Cortex is the open, graph-native, citation-first take. Claim-level attribution is an active research area (ARE arXiv:2410.16708, RAGentA arXiv:2506.16988) — we ship a minimal, verifiable version of it.

---

## 2. Mission

**Mission statement:** *Make an organization's decisions first-class, queryable objects — every claim traceable to its source, every negative provable with receipts — on a graph, not a vector pile.*

**Core principles:**

1. **Decisions are nodes, not documents.** `Decision` is a first-class node hanging off `Person`, `Team`, `Concept`, and `Evidence`. Everything else follows.
2. **Provenance by construction, not by annotation.** The retrieval trail (`MENTIONED_IN`, `EVIDENCED_BY`) is the same path the citation chips render. No claim exists without its edge.
3. **Abstention is a feature.** "No record support that" — with search receipts — outranks a plausible confabulation. The vendor's own GraphRAG-SDK `grounded_answers_with_abstention` pattern is cited, not hand-rolled invisibly.
4. **The graph shapes agent behavior.** The router, claim gates, impact walks, and sufficiency stops all read the graph; FalkorDB is the spine, not garnish (event hard rule).
5. **Show your work.** Router class → retrieval mode → evidence count → faithfulness, plus the decision ledger, visible in the UI. Judges who care can see the agent's spine.
6. **Judges pay $0 to replay.** The snapshot is committed; ingestion replays locally without tokens or API quotas.

---

## 3. Target Users

**P1 — Hackathon judges (primary).** Expert, skeptical, time-boxed. They probe provenance ("which comment is this from?"), test negative questions the corpus never answered, and check the stack is real (FalkorDB central, new implementation).
- *Technical comfort:* high — reads Cypher, runs Docker, inspects code.
- *Key needs:* instant credibility (citations that open the real source), the negative-proof moment, honest methodology in the submission README, one-command local run.
- *Pain points addressed:* RAG systems that confabulate plausible-but-fake answers; "references" lists that don't link to the actual passage.

**P2 — Demo viewers / community evaluators (secondary).** People watching the 4-minute video or opening the live URL after the event.
- *Key needs:* the scripted buttons must land fast and visibly; the "600 decisions, 30k comments, one question box" story must read from the landing page.
- *Pain points addressed:* knowledge tools that demo well on cherry-picked prompts but break on free input — hence scripted buttons first, free chat second (locked demo-determinism rule).

**P3 — "Any org" adopter (portability persona).** A platform/engineering lead at an OSS org or startup who wants a decision brain for *their* records.
- *Key needs:* the schema is MADR 4.0.0-informed and GitHub-identity-canonical, so a new corpus is a pipeline re-run, not a rewrite. "Bring your own corpus" is the submission README's closing teaser.
- *Pain points addressed:* ADR collections that rot in repos with no queryable structure.

---

## 4. MVP Scope

### In Scope

**Core functionality**
- [ ] Q&A over the RFC corpus with **claim-level citations**: sentence-by-sentence answers, each sentence mapped to evidence nodes by the claim↔evidence gate; uncited sentences visually flagged
- [ ] **Citation chips → SourcePanel**: every chip opens the actual RFC section (rendered markdown), the GitHub comment (author, date, stance), or the commit
- [ ] **Principled abstention**: if key claims go uncited → answer abstains ("no record supports that — here's what the record does contain") with the `NoRecordCard` receipts (searched N nodes, M evidence chains, 0 matches) and the "proposals that came close" trail
- [ ] **Impact Explorer**: click any Decision/Concept/Person → dependent subgraph blooms (React Flow); edges labeled by evidence type; hover-focus beat
- [ ] **Timeline**: decisions over time with supersede arrows and loudest-voice stances; scripted "async/await lifecycle story" tour
- [ ] **Faithfulness badge**: RAGAS faithfulness (HHEM-2.1-Open, local CPU) scored per answer → "faithfulness 1.0 · 8/8 claims cited"
- [ ] **Verification-set buttons**: "Ask the corpus", "Prove the negative", "Impact tour", "The async/await story" — scripted, deterministic, first
- [ ] **Show-your-work strip** on every answer: router class → retrieval mode → evidence count → faithfulness (collapsible)
- [ ] **CypherPeek**: collapsible panel showing generated Cypher (display flourish only)
- [ ] Free-text search box over the corpus (after scripted buttons)
- [ ] **Exports**: Markdown report + JSON graph dump ("your company brain, portable")

**Data & graph**
- [ ] **One-time RFC snapshot** via GitHub REST (free PAT, ≤ 5,000 req/h): RFC markdown files, PR review comments (first ~100 per PR; retained honestly as `:Message {truncated: bool}`), commit history per RFC file → JSONL committed in-repo
- [ ] **GraphRAG-SDK v1.1.0 ingestion** into FalkorDB 6.x: ontology-constrained extraction (`GraphSchema`/`EntityType`/`RelationType`), `MENTIONED_IN` provenance edges, content-hash incremental `apply_changes` (idempotent; round-the-clock agents never duplicate)
- [ ] MADR/Graphiti-informed **graph schema** (§6) with canonical identity: GitHub handles = `:Person` ids; RFC/PR numbers = canonical object ids
- [ ] **Stance edges** `OBJECTED|SUPPORTED|MODERATED` from FCP/review patterns + S1 classification, every edge confidence-stamped and jumpable to its evidence comment
- [ ] **Verification set** (pinned in-repo): 30 golden questions (answerable, known citation) + 10 no-record questions (verified absent during authoring) — doubles as the regression eval and powers the abstention button
- [ ] Seed-on-boot: if graph empty → replay snapshot ingestion in fast mode

**Agent**
- [ ] **System 1 / System 2 split** via OpenRouter only: `decide()` decision model (question router 1-of-4: fact · decision-provenance · impact · out-of-graph; per-claim y/n + confidence; impact-node relevance 0–5; recall-sufficiency stop) and `reason()` synthesis model (sentence-by-sentence answers, impact narratives, no-record verdicts)
- [ ] Confidence-escalation: S1 confidence < threshold → escalate to S2
- [ ] **Decision ledger**: every decision call recorded (input digest, choice, confidence, model, latency, cost, escalated flag) → live UI footer
- [ ] Query-side retrieval: vector seed + full-text + multi-hop traversal in FalkorDB

**MCP (minimal, scope guard)**
- [ ] Read-peephole MCP server (`@falkordb/mcpserver`): list / query — the product surface is the web app; don't over-invest

**Tech & deployment**
- [ ] FastAPI backend, React + Vite + CopilotKit + AG-UI (SSE) frontend, static bundle served by Caddy
- [ ] Docker Compose: `falkordb` (6.x, volume) + `api` + `web`; TLS; one-command local run
- [ ] Live deployment on the VPS; seed-on-boot; demo answers cached; pre-baked dev cache for backup footage
- [ ] CI: lint, unit, compose smoke
- [ ] 4-minute demo video + backup footage; README with positioning, schema, verification-set results, snapshot methodology

### Out of Scope (deferred)

**Data**
- [ ] `rust-lang/rust` issues sub-corpus (implementation evidence `:Issue` links) — **stretch goal only** (Day-3+ if ingestion, answer pipeline, and polish are all green; the brain must be complete on RFCs alone; submission README mentions it as future work)
- [ ] GitHub Discussions via GraphQL — likely unnecessary; only if a verification question demands it

**Agent / product**
- [ ] Text-to-Cypher as the retrieval backbone — SDK's text2Cypher is the *display flourish* only (CypherPeek)
- [ ] QueryWeaver — it is Text2SQL, not text2Cypher; name-drop only, no dependency
- [ ] Write-path APIs (any graph mutation from the UI)
- [ ] Multi-tenant / bring-your-own-corpus *in-app* upload flow (submission-README teaser only in MVP)
- [ ] MCP Apps in-Claude dashboard (Track-2 pattern; not needed here)

**Fallback (emergency switch, not a feature)**
- [ ] Fictional startup corpus — pre-authored, committed, same schema — activated **only if** the RFC ingestion stalls at end of Day 1. Decision must not eat half a day: spike the RFC pull on Day 0. *(Locked decision #3.)*

**Infrastructure**
- [ ] GPU acceleration (VPS is CPU-only — badge is designed CPU-first, async)
- [ ] SSR, Kubernetes, autoscaling — Compose + Caddy is the whole deployment story
- [ ] Auth/multi-user (public read-only demo; admin ops local-only)

---

## 5. User Stories

**U1 — Trace a decision to its source.**
As a *judge*, I want to ask "What did the language team decide about trait objects, and who objected?", so that I can verify the answer rather than trust it.
*Example:* the AnswerCard builds sentence-by-sentence; clicking a chip opens the exact GitHub comment (author, date, extracted stance); then the objection list — handle, evidence link, confidence — renders inline.

**U2 — Prove a negative.**
As a *judge*, I want to fire "Did Rust ever decide to require attachments in `unsafe` code?" and get an honest no-record verdict with receipts, so that I can see the system doesn't confabulate.
*Example:* the NoRecordCard shows "searched N nodes · M evidence chains · 0 matches"; then the twist — "…but three proposals came close" — with their real evidence trails.

**U3 — See the blast radius.**
As a *judge*, I want to click a Decision/Concept and watch the dependent subgraph bloom, so that impact analysis feels like the traversal it is.
*Example:* clicking the async/await decision highlights decisions superseding it, concepts touching it, and teams owning the area, edges colored/labeled by evidence type: "if we revisit async trails, what's in the blast radius?"

**U4 — Read a decision's lifecycle.**
As a *demo viewer*, I want the Timeline with supersede arrows and the scripted async/await story, so that a decade of contentious decisions becomes legible in 60 seconds.
*Example:* proposed → revised → accepted → implementation evidence, each stage a real RFC number, real dates, real stances of the loudest voices.

**U5 — Inspect the agent's spine.**
As a *judge*, I want the show-your-work strip and decision ledger, so that I can see the system is genuinely graph-driven and understand its economics.
*Example:* the strip reads `router: decision-provenance → retrieval: multi-hop (46 candidates) → gates: 8/8 claims cited → faithfulness 1.0`; the footer ledger ticks with model, confidence, latency, cost, escalated flag.

**U6 — Run it locally for free.**
As a *judge*, I want `docker compose up --build` + one OpenRouter key to give me a seeded, queryable brain, so that I can verify the demo myself without setup pain.
*Example:* first boot replays the committed JSONL snapshot in fast mode — no GitHub rate limits, no extraction tokens; replaying the demo Q&A costs $0.

**U7 — Trust the provenance story.**
As a *judge*, I want every stance edge to jump to the comment that produced it, so that a misclassified stance is visible rather than hidden.
*Example:* `@person — OBJECTED (conf 0.83)` chips into the FCP comment; the UI never hides the source (hard rule).

**U8 — Check faithfulness is real.**
As a *judge*, I want the faithfulness badge showing live HHEM/RAGAS numbers per answer, so that "citation-first" isn't a marketing claim.
*Example:* badge lands after the answer completes ("faithfulness 1.0 · 8/8 claims cited"); a scoring placeholder shows until HHEM finishes on CPU.

**Technical stories**

**T1 —** As the *system*, I want content-hash incremental ingestion so that re-ingestion and round-the-clock agent writes are no-ops (never duplicate graph data). *(locked idempotency rule)*

**T2 —** As the *system*, I want `decide()` behind one typed wrapper (1-of-N / 0–5 / y-n, calibrated confidence) with a small-model strict-JSON fallback and slugs as `.env` config, so that model availability is a config change, not a fire. *(locked risk rule)*

**T3 —** As a *solo entrant running three tracks*, I want the same dark "graph-ops" component kit and ledger footer as Briefs 1–2, so that the three products read as a family and kit code is copy-paste.

---

## 6. Core Architecture & Patterns

### 6.1 Pipeline

```
Snapshot (JSONL: rfcs, pr-comments, commits, issues — committed in repo)
   │  ingest (GraphRAG-SDK v1.1.0: ontology-constrained extraction +
   │          MENTIONED_IN provenance edges; content-hash incremental)
   ▼
FalkorDB 6.x: Decision/Evidence/Person/Project/Area/Concept graph
   ▲                            ▲
   │ MCP tools (query/read)     │ exports
Agent core (FastAPI):
   System 1 — OpenRouter decision model (Jev-class via decide()):
        question router (1-of-4: fact · decision-provenance · impact · out-of-graph)
        claim↔evidence gate per answer sentence (y/n + confidence)
        impact-node relevance (0–5) · recall-sufficiency stop
   System 2 — reasoning LLM via reason(): answer synthesis sentence-by-sentence,
        impact narratives, no-record verdicts
   RAGAS faithfulness (HHEM-2.1-Open, local CPU) scored per answer
        → "faithfulness 1.0 · 8/8 claims cited" badge (async, post-stream)
   Decision ledger → live UI footer (family pattern across Briefs 1–2)
   ▼ AG-UI (SSE) → React (Vite) + CopilotKit UI
```

### 6.2 Key patterns

- **System 1 / System 2 separation.** All typing/classification/rating work runs on the cheap decision model (`decide()`); only synthesis, impact narratives, and no-record verdicts run on the frontier reasoner (`reason()`). Escalation: S1 confidence < threshold → S2 handles that step. Every decision call lands in the ledger; retrieval embeddings record their cost/latency on the retrieval row.
- **Ontology-constrained extraction.** GraphRAG-SDK's `GraphSchema`/`EntityType`/`RelationType` constrain what gets extracted; `grounded_answers_with_abstention` is a *shipping SDK example* we adapt — abstention is the vendor's own pattern (cite it), not a custom hack.
- **Claim gate = the citation mechanism.** S2 emits sentence-by-sentence; per sentence, `decide()` maps it to evidence nodes (y/n + confidence). Uncited sentences are flagged; uncited key claims trigger abstention. The gate *is* the provenance path to the chips.
- **Retrieval = graph-native.** Vector seed + full-text + multi-hop traversal in FalkorDB. Text-to-Cypher (SDK experimental) is a display flourish (CypherPeek), never the backbone.
- **Idempotent ingestion.** Content-hash no-op writes via the SDK's incremental `apply_changes`; the committed snapshot makes judge-local replays deterministic and free.
- **Generative UI.** Every backend tool call renders as a registered React component (render props fed by tool outputs), per the CopilotKit Jev-generative-UI pattern. AG-UI wiring decision at build time: LangGraph-native adapter vs. plain FastAPI emitting AG-UI events via the official Python SDK; fallback = hand-rolled SSE with the same event schema (UI unchanged).
- **Demo determinism.** Seed-on-boot; scripted scenario buttons first, free chat second; demo answers cached.

### 6.3 Repository layout (suggested)

```
track3-decision-cortex/
├── AGENTS.md                # architecture pinned + workstream split (pre-event deliverable)
├── .agents/PRDs/PRD.md      # this document
├── snapshot/                # committed one-time corpus: rfcs.jsonl, pr-comments.jsonl, commits.jsonl
├── ingest/                  # parsers (emit plain dicts, no FalkorDB calls) + GraphRAG-SDK ingestion
├── api/                     # FastAPI agent core: router, gates, retrieval, synthesis, ledger
├── web/                     # React + Vite SPA + CopilotKit components + shared kit
├── verification/            # 30 gold + 10 no-record questions + eval runner
├── infra/                   # docker-compose.yml, Caddyfile, .env.example, CI
├── docs/                    # submission README, schema reference, blog seed
└── scripts/                 # factory verification entrypoints (run_scenario_api.sh)
```

---

## 7. Tools / Features

### 7.1 Agent tools (FastAPI backend)

| Tool | Purpose | Key behavior |
|---|---|---|
| `router_classify` (S1 `decide`) | 1-of-4: fact · decision-provenance · impact · out-of-graph | Calibrated confidence; low confidence → escalate/re-route; out-of-graph routes toward abstention |
| `retrieve_evidence` | Seed evidence candidates for a query | Vector seed + full-text + multi-hop FalkorDB traversal; returns evidence nodes + query path; logs candidate count |
| `claim_gate` (S1 `decide`) | Per answer sentence: supported by which evidence? | y/n + confidence per claim; uncited key claims → abstain path |
| `impact_walk` | Blast-radius of a node | `ABOUT\|AREA\|RELATES*1..3` traversal (verify `rels` var syntax against FalkorDB docs); S1 rates node relevance 0–5; edges typed by evidence |
| `timeline_query` | Decisions over time + supersede chains | Sorted `Decision` stream + `SUPERSEDES` edges + stance summaries for loudest voices |
| `sufficiency_stop` (S1 `decide`) | Recall-sufficiency check | Stops retrieval expansion when evidence is sufficient (Jev economics) |
| `synthesize` (S2 `reason`) | Answer synthesis | Sentence-by-sentence, feeds claim gate; also writes impact narratives and no-record verdicts |
| `record_abstention` | Negative-verdict packaging | Compiles receipts: nodes searched, evidence chains walked, "close proposals" trail |
| `ledger_append` | Decision ledger | Input digest, choice, confidence, model, latency, cost, escalated flag (locked ledger schema) |

### 7.2 UI components (React, shared dark "graph-ops" kit)

| Component | Spec |
|---|---|
| `AnswerCard` | Sentence-by-sentence render; each sentence carries `CitationChip`(s); uncited sentences visually flagged |
| `CitationChip` → `SourcePanel` | Chip opens the actual source: RFC section (markdown), GitHub comment (author, date, stance), or commit |
| `NoRecordCard` | Abstention UI: "searched N nodes · M evidence chains · 0 matches"; the "three proposals came close" trail; runs on the verification set's no-record buttons |
| `ImpactGraph` | React Flow; evidence-type edge colors/labels; node click → subgraph blooms; hover-focus beat |
| `TimelineView` | Decisions over time, supersede arrows, stance highlights; scripted async/await tour |
| `FaithfulnessBadge` | RAGAS + HHEM numbers per answer; "scoring…" state until CPU scoring completes (async, never blocks the stream) |
| `CypherPeek` | Collapsible generated-Cypher display (flourish only) |
| Show-your-work strip | `router class → retrieval mode → evidence count → faithfulness`, collapsible, on every answer |
| Decision-ledger footer | Live call counter: model, confidence, latency, cost, escalated flag (family pattern) |
| Landing | Big search box + the four verification-set buttons: "Ask the corpus", "Prove the negative", "Impact tour", "The async/await story" |

### 7.3 MCP surface (minimal)

Read-peephole using `@falkordb/mcpserver`: list node labels/relations, run read-only Cypher. Exists to satisfy the ingestion/inspection story for agents — the product surface is the web app.

---

## 8. Technology Stack

| Layer | Technology | Notes |
|---|---|---|
| App language | Python | Locked decision #4 (LLM-bound workload → velocity wins) |
| Graph DB | **FalkorDB 6.x** | Mandatory primary DB, central to the product; Rust engine = the perf story |
| Ingestion engine | GraphRAG-SDK v1.1.0 (Apache-2.0) | Ontology-constrained extraction, `MENTIONED_IN` edges, incremental `apply_changes`, `grounded_answers_with_abstention` pattern |
| Backend | FastAPI (uvicorn) | Agent core, AG-UI/SSE events, REST, exports |
| S1 decision model | OpenRouter `decide()` — **slug TBD at build** | Jev-class candidate decided at build; wrapper abstracts the provider; **default config = small model with strict JSON schema** behind the same interface |
| S2 synthesis model | OpenRouter `reason()` | Frontier reasoning LLM; slugs as config |
| Faithfulness | RAGAS + **HHEM-2.1-Open** (local, **CPU-only** design) | Scored async post-stream; never blocks the answer |
| UI | React + Vite SPA (no SSR/Next.js) + CopilotKit + AG-UI | Locked decision #5; static bundle via Caddy; AG-UI via official Python SDK first, hand-rolled SSE fallback |
| Graph viz | React Flow | ImpactGraph |
| MCP | `@falkordb/mcpserver` | Read-only peephole |
| Deployment | Docker Compose + Caddy (TLS) on Techa's VPS | `falkordb` (volume) + `api` + `web`; seed-on-boot |
| CI | lint + unit + compose smoke | Pre-event deliverable |

**Explicit non-dependencies:** QueryWeaver (Text2SQL ≠ text2Cypher); Graphiti library (temporal-field *concept* adopted, no library dependency).

---

## 9. Security & Configuration

### 9.1 Environment / configuration

| Variable | Required | Purpose |
|---|---|---|
| `OPENROUTER_API_KEY` | Yes (runtime) | S1 + S2 calls; **dedicated per-deploy key, hard spend cap: $10** |
| `GITHUB_TOKEN` | No (runtime) | Free GitHub PAT for the one-time snapshot pull and *refresh only* — the snapshot ships committed, so judge runs need no token |
| `DECIDE_MODEL_SLUG` | No | OpenRouter slug for S1; default = fallback small model (strict JSON) until pinned |
| `REASON_MODEL_SLUG` | No | OpenRouter slug for S2 |
| `SPEND_CAP_USD` | No | Hard-stop guard + ledger alerting (default 10) |
| `DB_FALKORDB_URL` etc. | No | Compose-internal defaults |

### 9.2 Security scope

- **In scope:** spend-capped key per deploy; response cache for demo queries; pre-baked dev cache for backup footage; read-only graph from the UI/MCP (no mutation endpoints); local-only admin/refresh ops; idempotent writes.
- **Out of scope:** user accounts, RBAC, tenancy, PII handling (the corpus is fully public and dual Apache-2.0/MIT), HTTPS hardening beyond Caddy defaults.

### 9.3 Deployment considerations

- Live URL on VPS (locked decision #6); demo video recorded regardless of deployment success.
- Seed-on-boot (empty graph → fast-mode snapshot replay); `.env` with one OpenRouter key = the entire judge setup.
- Budget doctrine ($10 cap): committed snapshot + cached demo answers + cheap-model(S1) extraction means judge replay ≈ $0; owner's dev spend during event is the only meaningful cost.

---

## 10. API Specification (lean)

REST + AG-UI/SSE from the FastAPI `api` service; all state flows over SSE + REST (no SSR).

| Endpoint | Method | Purpose |
|---|---|---|
| `/healthz` | GET | Liveness + ingestion/seed status |
| `/ask` | POST → SSE | AG-UI event stream (the product runtime) |
| `/graph/impact/{node_id}` | GET | Subgraph for ImpactGraph (nodes, edges, evidence types, depths) |
| `/timeline` | GET | Decisions + `SUPERSEDES` edges + stances (filterable by area/team) |
| `/node/{id}` | GET | Node detail (SourcePanel & inspector backing) |
| `/verification` | GET | The 30 gold + 10 no-record questions (pinned set) |
| `/verification/run` | POST | Executes the set; returns accuracy + abstention-correctness report |
| `/exports/report` | POST | Markdown report generation → download |
| `/exports/graph` | POST | JSON graph dump → download |

**`/ask` payload sketch:**
```json
{
  "question": "What did the language team decide about trait objects, and who objected?",
  "scenario": null,          // or: "ask_corpus" | "prove_negative" | "impact_tour" | "async_story"
  "mode": "free"             // "scripted" buttons first (deterministic), "free" second
}
```

**SSE event flow (AG-UI schema):** `RUN_STARTED` → tool-call events (`router_classify`, `retrieve_evidence`, `claim_gate`, …) each rendering as registered generative-UI components with render props → `TEXT_MESSAGE_CONTENT` deltas (sentence-by-sentence, chips attached) → custom events (`cypher_preview` for CypherPeek, `ledger_update` for the footer, `faithfulness_pending`) → `RUN_FINISHED` (ledger summary + citation count).

**MCP tools:** `list_labels`, `list_relations`, `query_cypher` (read-only, timeout-guarded) — via `@falkordb/mcpserver` (streamable HTTP).

---

## 11. Success Criteria

### 11.1 Definition of done (verbatim intent)

- [ ] Live URL with the verification-set buttons + free search
- [ ] Every answer chip-deep-links to real sources (RFC text, comment, commit)
- [ ] Abstention moment with receipts works (NoRecordCard + "came close" trail)
- [ ] Impact Explorer + Timeline functional (real RFC numbers on supersede chains)
- [ ] Faithfulness badge real (HHEM-2.1-Open, local)
- [ ] 4-min video (+ backup footage) featuring the negative-proof beat
- [ ] README with MADR/Graphiti/ARE positioning + snapshot methodology
- [ ] `docker compose up --build` + one key = judge-local brain, $0 LLM cost for replay
- [ ] Decision ledger in the UI footer

### 11.2 Quality indicators (measured by the verification set, which doubles as the regression eval)

- [ ] Golden set: **≥ 90% of the 30 gold questions** answer correctly with the *known decision citation* (target; calibrated when the set is authored against the snapshot in Phase 0 — misses triaged, never silently dropped)
- [ ] No-record set: **10/10 of the no-record questions abstain** with receipts (zero confabulations on the pinned negative set)
- [ ] Claim-citation integrity: on scripted scenarios, **key claims 100% cited** or the answer abstains — no silently-uncited key claim ships
- [ ] Faithfulness badge: real HHEM numbers on every scripted answer; badge CPU latency doesn't block the answer stream
- [ ] Local replay: demo scenario answers served from cache (≈ $0) on a fresh judge machine
- [ ] Judge-borne rehearsal: two full dress rehearsals (Day 3) with zero crashes on the scripted path

### 11.3 Compliance (event hard rules)

- [ ] FalkorDB is the primary, central graph DB; the graph demonstrably shapes agent behavior (router/gates/impact/stops all read it)
- [ ] Main FalkorDB implementation (schema, queries, agent loop) is new work during the event; pre-event work stays legal (scaffold, parsers, snapshot, prompt drafts, UI mockups — no schema/queries written into FalkorDB, no agent loop)
- [ ] Owner can explain the whole system (build for explainability in docs and video)

---

## 12. Implementation Phases

> Event timeline: today is Oct 13; submissions close 11:59 PM IST Oct 18. UTC/NIST pace is pre-plan; estimates are in event days.

### Phase 0 — Pre-event prep (Oct 13–14, "Day 0")
**Goal:** Everything that is legal-before-the-event, so Day 1 starts with ingestion only. *(Prep-line rule — see `AGENTS.md`: no schema/queries into FalkorDB, no agent loop, before Oct 15.)*

**Deliverables:**
- [ ] Codebase scaffold + CI (lint, unit, compose smoke) — `AGENTS.md` already covers rules, workstream split, and demo beats; keep it current
- [x] **Day-0 spike: JSONL snapshot pipeline against GitHub REST** (rate-limit-safe; PAT from vault `GITHUB_TOKEN`) — **pin the snapshot by Oct 14**
- [x] Verification set authored AND checked against the snapshot (every no-record question verified absent)
- [x] Parsers emitting plain dicts (no FalkorDB calls); ontology drafts (GraphSchema/EntityType/RelationType)
- [ ] Prompt drafts for `decide` tollgates + `reason` roles
- [ ] UI mockups + shared dark "graph-ops" component kit skeleton
- [ ] Submission-README skeleton under `docs/` with the positioning paragraph; VPS/domain/Compose template + `.env.example`

**Validation:** snapshot covers all merged+active+rejected RFCs and PR-comment harvest with truncation flags; verification set passes a full manual check; `docker compose up --build` boots api+web (empty graph OK).

### Phase 1 — Ingestion into FalkorDB (Day 1, Oct 15)
**Goal:** The graph is real, provenance-edged, and entity-resolved.

**Deliverables:**
- [ ] GraphRAG-SDK ingestion (ontology-constrained) into FalkorDB 6.x with `MENTIONED_IN`/provenance edges
- [ ] Entity nodes from GitHub handles (canonical `:Person` ids); teams/areas from RFC fields + OWNERS files where parseable
- [ ] Content-hash incremental re-ingestion proven (idempotency check)
- [ ] Smoke-test: 20 Q&A against the live graph

**Validation:** graph node/edge counts match snapshot expectations; a hand-checkable decision (e.g., a known RFC) traced end-to-end (RFC → PR comments → versions → teams); 20-question smoke notes recorded.

### Phase 2 — Answer pipeline & abstention (Day 2, Oct 16)
**Goal:** The core product surface works end-to-end: router → retrieval → S2 synthesis → claim gates → chips; and the negative path abstains with receipts.

**Deliverables:**
- [ ] Agent core: `router_classify` → `retrieve_evidence` → `synthesize` (S2, sentence-by-sentence) → `claim_gate` per sentence → chips + SourcePanel
- [ ] Abstention path + `NoRecordCard` (receipts + "came close" trail); verification-set no-record buttons fire it
- [ ] RAGAS/HHEM-2.1-Open faithfulness badge (async CPU scoring)
- [ ] Decision ledger + show-your-work strip + CypherPeek wired into the stream
- [ ] Demo-answer response cache

**Validation:** on the gold set, answers carry correct citations; 10/10 negatives abstain; uncited-sentence flagging demonstrable; ledger tick visible; badge shows real HHEM numbers.

### Phase 3 — Surfaces, deployment & polish (Day 3, Oct 17)
**Goal:** All three product surfaces done; live on the VPS; rehearsed.

**Deliverables:**
- [ ] Impact Explorer (React Flow, evidence-typed edges) + Timeline (supersede arrows, async/await scripted tour) + exports (MD + JSON dump)
- [ ] Agent polish: sufficiency stop, confidence-stamped stance edges with jump-to-evidence
- [ ] *(Stretch, only if all green)* rust-lang/rust Issues sub-corpus
- [ ] Deploy to VPS (seed-on-boot, spend-capped key); free-search polishing; landing buttons finalized
- [ ] **Dress rehearsal ×2** (full video path, scripted buttons → free chat)

**Validation:** zero crashes across both rehearsals; live URL healthy end-to-end; exports download correct artifacts; supersede chain in the tour uses real RFC numbers chosen at build time.

### Phase 4 — Readme, video, submit (Day 4, Oct 18)
**Goal:** Submitted with buffer-to-burn.

**Deliverables:**
- [ ] README: positioning, schema, verification-set results, snapshot methodology, MADR/Graphiti/ARE citations, bring-your-own-corpus teaser
- [ ] 4-minute video + backup footage (incl. Vector-RAG ablation flash on the negative-proof beat); blog seed
- [ ] Submission uploaded with **≥ 3 h buffer** before 11:59 PM IST

**Validation:** judge-lens pass on live URL + video; hard-rule checklist (§11.3) green; submission confirmation logged.

---

## 13. Future Considerations (post-MVP)

- **Bring-your-own-corpus in-app:** any MADR-shaped repo or GitHub org as a drop-in ingestion target (schema is deliberately portable; canonical GitHub identity makes this a re-run, not a rewrite)
- **Reopen the `rust-lang/rust` Issues sub-corpus** as permanent implementation evidence beyond the Event-window stretch
- **Decision-model A/B panel:** runner-up Jev-class decision models swapped in via `DECIDE_MODEL_SLUG` against the ledger's economics
- **Write-path APIs + ADR intake:** proposals enter the graph as first-class records and mature like an RFC (supersede chains maintained automatically)
- **QueryWeaver-style natural-language analytics** once text2Cypher matures (display-only today)

---

## 14. Risks & Mitigations

| # | Risk | Mitigation |
|---|---|---|
| 1 | **Corpus gravity:** rust-issues cross-linking eats days and could sink completeness | Locked as stretch-only; the brain must be complete on RFCs alone; submission README mentions it as future work |
| 2 | **LLM spend past the $10 cap** (S2 on every answer, extraction over ~600 docs) | Batch extraction with the cheap model; S2 only for synthesis; re-use cached extractions; committed snapshot → judges pay $0; response cache + pre-baked dev cache for demo/backup; ledger exposes cost live so overspend is visible immediately |
| 3 | **Stance classification mistakes** poison the objection story | Every stance edge carries confidence + jumps to its evidence comment; UI never hides the source (brief guard) |
| 4 | **Ingestion stalls** (rate limits, pagination, SDK surprises) | Snapshot-first: JSONL committed by Oct 14 so re-ingestion is local and quota-free; fictional-corpus fallback is pre-authored and committed (same schema) — but the decision to switch must not eat half a Day 1; PR-comment harvest capped at first ~100 per PR with honest `truncated: true` flags |
| 5 | **HHEM on CPU is slow at answer-time** | CPU-first design: scored async after the stream completes; badge shows "scoring…" then lands; per-answer scope (~8 claims) keeps the model tractable; never blocks text |
| 6 | **Decision-model availability/renaming on OpenRouter** | Fallback small model with strict JSON schema behind the same `decide()` interface (default config until a slug is pinned); provider swap is a config change (locked risk rule) |
| 7 | **AG-UI/CopilotKit wiring mismatch** | Pre-decided ladder: LangGraph-native adapter → official AG-UI Python SDK from plain FastAPI → hand-rolled SSE with the same event schema (UI unchanged) |
| 8 | **Verification-set honesty challenged** ("did you really verify negatives?") | Every no-record question verified against the corpus during authoring; README documents the method; the set ships pinned in-repo and runs as a regression eval from the UI |
| 9 | **Solo-entrant scope melt** across 4 days | Brief's scope guards are binding (this PRD §4 out-of-scope list); scripted-buttons-first demo determinism; ≥ 3 h upload buffer enforced in Phase 4 |

---

## 15. Appendix

### 15.1 Related documents
- `../../AGENTS.md` — project rules, workstream split, demo-script beats, judge Q&A crib
- The original Track 3 brief and the shared battle-plan README were removed by the owner (Oct 13); their content lives entirely in this PRD and `AGENTS.md`
- Sibling PRDs (when written): `.agents/PRDs/PRD.md` in `track1-iam-attack-path-finder`, `track2-engram-graph-memory-mcp`

### 15.2 Key dependencies & links
- rust-lang/rfcs — https://github.com/rust-lang/rfcs (dual Apache-2.0/MIT, verified)
- GraphRAG-SDK v1.1.0 — Apache-2.0 (ingestion engine + `grounded_answers_with_abstention` shipping example)
- MADR 4.0.0 — https://github.com/adr/madr (the citable ADR standard behind the schema)
- Graphiti — temporal-field *concept* adopted (`decided_on` / `superseded_on`); no library dependency
- Claim-level attribution research: ARE arXiv:2410.16708; RAGentA arXiv:2506.16988
- FalkorDB 6.x · `@falkordb/mcpserver` · RAGAS · HHEM-2.1-Open (Vectara) · CopilotKit · AG-UI · React Flow · Caddy

### 15.3 Graph schema reference (canonical)

```
(:Decision  {rfc, title, status: proposed|accepted|rejected|replaced|closed,
             proposed_on, decided_on, supersedes_rfc, madr_link})
(:Person    {handle, name})
(:Team      {name})
(:Area      {name})
(:Concept   {key, name})
(:DocVersion{sha, ts, content_ref})
(:Message   {pr_id, comment_id, author, ts, text_ref, stance_hint, truncated})
(:Commit    {sha, ts, message})
(:Issue     {number, ts, title})

(:Decision)-[:PROPOSED_BY]->(:Person)
(:Decision)-[:ASSOCIATED_TEAM]->(:Team)
(:Decision)-[:ABOUT]->(:Concept)
(:Decision)-[:AREA]->(:Area)
(:Decision)-[:HAS_VERSION]->(:DocVersion)
(:Decision)-[:EVIDENCED_BY {type: discussion|vote|revision|implementation}]
     ->(:Message|DocVersion|Commit|Issue)
(:Person)-[:OBJECTED|SUPPORTED|MODERATED {evidence, confidence}]->(:Decision)
(:Decision)-[:SUPERSEDES]->(:Decision)
(:Person)-[:MEMBER_OF]->(:Team)
(:Concept)-[:RELATES {strength}]->(:Concept)
```
Corpus RFC statuses (`active | merged | accepted | rejected | replaced | closed`) normalize onto schema status; `merged` maps to `accepted` (shipped as merged FCP), `active` to `proposed`.

**Retrieval indexes (derived, out-of-band).** The query-side retrieval (PRD §6.2, §7.1 `retrieve_evidence`) needs indexes that are derived index data, not canonical payload properties, so they are created by the loader and never written through a `Payload` node:

- a **vector index** on `Decision.embedding`, where `embedding` is a `vecf32` stamped from the committed `snapshot/decision-embeddings.jsonl` (produced once by `ingest.embeddings` with the same OpenRouter embedding slug/dimension used for query embeddings);
- a **full-text index** on `Decision.title` (the only node property the full-text seed queries; the graph stores no Message body or RFC content — only refs — so there is nothing else to index).

`embedding` is deliberately **not** added to the `Decision` property list above: `validate_payload` still rejects it inside a payload, because a plain float array stored through `upsert_nodes` would not be a `vecf32` and would break the vector index. Model slug and dimension must match between document and query embeddings.

**Reference Cypher flavors:**
```cypher
// decisions + who objected:
MATCH (d:Decision)-[e:ABOUT]->(c:Concept {name:"trait objects"})
MATCH (p:Person)-[o:OBJECTED]->(d)
RETURN d.title, d.status, o.evidence, collect(p.handle);

// impact walk ("what touches soundness/thrift?"):
MATCH (d)-[:ABOUT|AREA|RELATES*1..3]-(x {name:"async"})
RETURN d, type(last(rels)), x   // verify rels var syntax against FalkorDB docs
```

### 15.4 Verification-set methodology (summary)
- 30 golden questions: each pinned with its known decision citation (RFC number / PR comment); authored *against* the snapshot, not from memory.
- 10 no-record questions: genuinely unproposed topics (e.g., "which planet does the Rust team list as its mascot?") — each verified absent by corpus search during authoring; README lists the full method.
- Doubles as the regression eval (§11.2) and the UI's abstention-button source.
