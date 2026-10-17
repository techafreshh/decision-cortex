# Impact Explorer, Timeline & exports

How the three graph surfaces work, what they read, and the two data gaps they
live with today. Plain language — the "explain everything" rule.

## Impact Explorer — `GET /graph/impact/{node_id}`

`api/impact.py::build_impact(reader, node_id, depth=3)` walks the graph
**undirected, depth 1..3**, starting from `{id: node_id}` at depth 0, and returns

```
{ seed, nodes: [{id, label, name, depth}], edges: [{src, dst, type, properties}],
  evidence_types: [str], truncated: bool }
```

- **Relation set** (`IMPACT_RELATIONS`): `ABOUT`, `AREA`, `RELATES`, `SUPERSEDES`,
  `ASSOCIATED_TEAM`, `PROPOSED_BY`, `OBJECTED`, `SUPPORTED`, `MODERATED`. This is a
  **superset of the invariant's `ABOUT|AREA|RELATES`**: the three concept-blast-radius
  relations stay in the query so the invariant is visibly satisfied, and the other six
  are the lifecycle/ownership/people edges the PRD U3 example ("decisions superseding it,
  concepts touching it, teams owning the area") and the §7.2 "click any
  Decision/Concept/Person" seed require. `EVIDENCED_BY` and `HAS_VERSION` are excluded:
  they are evidence leaves (up to ~9 `Message` nodes per RFC, plus `DocVersion`/`Commit`)
  reached through `SourcePanel`, not the impact canvas.
- **"Evidence type" = the edge's relation name.** Each edge carries `type`, and the
  response carries `evidence_types` (the sorted distinct set). The React Flow edge
  colour/label is keyed on that `type` via `web/src/lib/evidenceStyle.ts`.
- **Traversal is BFS, one hop per frontier** (`_SEED_QUERY` + `_NEIGHBORS_QUERY`),
  not a single variable-length Cypher match. Bounded, testable, and immune to
  `AREA` fan-out path explosion; the 200-node cap sets `truncated: true`
  (provenance honesty).
- **Data-driven:** on the committed snapshot only `AREA`, `ASSOCIATED_TEAM`,
  `PROPOSED_BY`, `EVIDENCED_BY` and `SUPERSEDES` exist (see gaps below). The
  endpoint lights up `ABOUT`/`RELATES`/stances with **no code change** when the
  sibling enrichment lands.

## Timeline — `GET /timeline` and `GET /timeline?tour=async_await`

`api/timeline.py::build_timeline(reader, area=None, team=None)` returns

```
{ decisions: [{rfc, id, title, status, proposed_on, decided_on, areas, teams,
               supersedes, superseded_by, stances: [{handle, kind, evidence, confidence}]}],
  supersede_edges: [{src, dst}], areas: [...], teams: [...], tours: ["async_await"] }
```

- Decisions are sorted by `decided_on` (falling back to `proposed_on`);
  `supersedes`/`superseded_by` are the real `SUPERSEDES` edges; `?area=`/`?team=`
  filter on the `AREA`/`ASSOCIATED_TEAM` relations.
- `stances` is grouped from confidence-stamped stance edges, ordered by
  confidence desc ("loudest voices"), each carrying its `evidence` permalink. On
  the committed graph it is `[]`.
- **`tours: ["async_await"]`** is always present so the UI can offer the scripted
  beat without a second contract. `?tour=async_await` returns
  `{tour, stages, transitions}`. An unknown `tour` is `400`, matching the
  `POST /ask` unknown-scenario behaviour.

### The async/await tour provenance

`api/tours.py::ASYNC_AWAIT_TOUR` is a **curated, committed constant**: a real
chronology of RFC numbers, statuses, dates and a one-line narrative, **every
field copied from `snapshot/rfcs.jsonl`**. The spine is
`53 → 1083 → 1823 → 2033 → 2394 → 2592 → 2932 → 3083 → 3185 → 3668`
(chronological by `proposed_on`; `53`, `1083`, `1823`, `3083` were rejected, the
rest merged). `test_tour.py` re-reads the snapshot and fails if any field drifts,
so the demo cannot silently change.

Tour arrows are labelled by **lifecycle transition, not `SUPERSEDES`** — honest
chronology. None of the async RFCs carry `supersedes_rfc`, and the snapshot's
three real `SUPERSEDES` edges (`1426→1401`, `2103→1755`, `3396→1861`) are
unrelated to async; inventing supersede edges would be fabrication. A stage whose
RFC is absent from the graph is **dropped, never fabricated**.

## Exports — `POST /exports/report`, `POST /exports/graph`

`api/exports.py`; both are **read-only and make zero LLM calls**.

- `POST /exports/report` takes `{node_id? | scenario?}` and returns
  `text/markdown` as an attachment. A `node_id` report is a pure graph read
  (node detail + a compact impact section); a `scenario` report reads the
  scenario cache warmed by a prior `POST /ask`.
- `POST /exports/graph` takes `{node_id, depth?}` and returns the impact payload
  as an `application/json` attachment.
- **Error contract:** missing both/neither selector → `400`; unknown node → `404`;
  a cold scenario cache → `409` (rather than spending on synthesis). No export
  path can trigger an LLM call.

## Data gaps (honest, not defects)

1. **No `Concept` nodes and no stance edges in the committed snapshot.** The
   `snapshot/` carries no `concepts.jsonl`/`stances.jsonl`, so `ABOUT`/`RELATES`
   and `OBJECTED|SUPPORTED|MODERATED` are empty today. Deriving them is the
   sibling Phase-3 polish deliverable (`docs/graph-schema-notes.md`), and the
   stance-edge polish line in the PRD is left **open**. The fixture-backed
   integration test (`api/tests/test_impact_integration.py`) proves the
   ABOUT/AREA/stance mapping the moment the data exists.
2. **The async headline RFCs have no harvested comments** (0 comments for
   1823/2033/2394/2592/3185/3668), so no stance summaries can be derived for the
   core of the tour even if stance derivation were in scope. Only the two
   rejected precursors carry comments (`rfc:53` 12, `rfc:1083` 6).

## Where the code lives

- Backend: `api/impact.py`, `api/timeline.py`, `api/tours.py`, `api/exports.py`;
  routes in `api/main.py`.
- Web: `web/src/api/graph.ts` (client; the plan named `impact.ts`/`timeline.ts`
  — consolidated into one graph client), `web/src/lib/impactFlow.ts`,
  `web/src/lib/evidenceStyle.ts`, `web/src/components/ImpactGraph.tsx`,
  `ImpactView.tsx`, `TimelineView.tsx`; mounted by `web/src/App.tsx`.
