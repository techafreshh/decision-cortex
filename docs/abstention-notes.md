# Abstention notes — the negative-proof path

Decisions behind `api/abstention.py` and the `record_abstention` tool call
(PRD §7.1, §10). These are the choices the PRD leaves to the implementation, so
a reviewer can overrule them explicitly.

## The receipt rides the frozen event schema

`record_abstention` is emitted as an ordinary AG-UI tool call
(`TOOL_CALL_START` → `ARGS` → `END` → `RESULT`), and the NoRecordCard payload is
the `result` object. No new event type is added: the `events.py` schema is
frozen and the web side already renders every backend tool call as a registered
component, so a new constant would be a cross-lane contract change with no
renderer to consume it. The payload field set is fixed by PRD §10:

| field | meaning |
|---|---|
| `nodes_searched` | `RetrievalResult.candidate_count` — how many evidence nodes the walk gathered |
| `evidence_chains` | traversed (non-seed) query-path steps — the real graph hops behind the search |
| `matches` | `claims_cited` — 0 for a true negative, and the ledger row's `choice` |
| `came_close` | up to three real Decisions the search reached but that did not answer |

## Came-close is seed-only and can never fabricate

Only *seed* Decisions count as "close": the nodes retrieval started from, found
by the vector or full-text index with a relevance score. A node reached by
traversal was found *through* a seed, so it did not itself come close, and a
traversed Decision is excluded. Entries are ranked by normalized relevance — a
vector seed's cosine distance is inverted to a similarity (`1 - score`), a
full-text score is used as-is — and tie-broken by ascending id, so the same
graph always yields the same trail. Every entry is built from a node already in
the retrieval result, so the trail can only name proposals the search actually
found. The card is evidence of a near-miss, not a second search result page.

`CAME_CLOSE_LIMIT = 3` bounds the trail; the demo needs a handful of near-misses,
not a ranked list that competes with the answer.

## An abstention is not an LLM call

Each `record_abstention` appends one decision-ledger row with
`model = "abstention:no-record"`, `choice = matches`, `confidence = None`,
`latency_ms = 0`, `cost_usd = 0.0`, `escalated = False`, and the question's
sha256 as `input_digest`. It is a deterministic compilation of the retrieval
result, so it has no model cost; recording it keeps the ledger a complete trace
of every gate the answer passed, including the one that returned nothing.

The row is appended in `record_abstention`, which `answer_question` calls at
plan-build time. `ask_events` only recomputes a plan on a scenario cache miss,
so a cached replay emits zero new ledger rows — the same rule the other plan
steps follow.

## One abstention trigger, two shapes

`abstention_required = claims_total == 0 or claims_cited < claims_total`
(`api/answer.py`), unchanged from #8. It fires two ways:

- **out-of-graph route** — no synthesis runs, so `claims_total == 0`; the card
  is a pure "no record" with the came-close trail.
- **uncited claim** — synthesis produced sentences but the gate cited fewer than
  all of them; `matches = claims_cited` shows how many *were* grounded.

Both carry the same four fields, so the web has one component to render.

## `record_abstention` takes no route argument

The tracked plan sketched `record_abstention(question, route, retrieval, ...)`,
but `route` has no consumer: it is not a receipt field (the PRD fixes the four
above), it is not in the ledger row, and the tool call's `args` already carry
`{"route": plan.route}`. An unused parameter is speculative surface, so it is
dropped; the route still reaches the UI through the tool-call args.

## `SEED_RELATIONS` is public

`api/retrieval.py`'s seed-relation tuple was private (`_SEED_RELATIONS`). Both
`abstention.evidence_chains` (non-seed steps) and the existing
`retrieval._relation_counts` need it, and `api.abstention` imports it across the
module boundary, so it is now `SEED_RELATIONS`. It is a module constant, not an
interface method, and has a current caller in another module.
