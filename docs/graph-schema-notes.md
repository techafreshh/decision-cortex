# Graph schema notes — Phase-1 ingestion

Decisions behind the Phase-1 loader (`ingest/graph.py`) that are not obvious
from the code. The canonical schema itself is `PRD.md` §15.3; these notes
record the choices the loader had to make where the PRD or the tracker issue
was ambiguous, so a reviewer can overrule them explicitly.

## Provenance edge: `EVIDENCED_BY`, not `MENTIONED_IN`

The tracker issue's invariant says "every decision carries
`MENTIONED_IN`/`EVIDENCED_BY` provenance edges", while its first invariant says
node labels and relationship types must **exactly match** PRD §15.3. Those pull
apart, because §15.3 declares only `EVIDENCED_BY`:

- `PRD.md` §15.3 (canonical schema, line 491) declares
  `(:Decision)-[:EVIDENCED_BY {type: discussion|vote|revision|implementation}]->(:Message|DocVersion|Commit|Issue)`
  and no `MENTIONED_IN` relation.
- `MENTIONED_IN` appears only in PRD prose (lines 34, 78, 174, 263, 388) — it is
  the SDK's own entity→chunk edge, describing the retrieval trail, not a
  `Decision`→evidence relation.

**Resolution: `EVIDENCED_BY` is the provenance edge; `MENTIONED_IN` is not
added.** Adding it as a relation type would be a PRD schema change, which
`AGENTS.md` requires owner sign-off for (cross-lane rule: schema changes land in
the PRD before code). The issue's own acceptance criteria never use
`MENTIONED_IN`; they assert §15.3's reference query.

Phase 1 emits `EVIDENCED_BY` with three of the four §15.3 `type` values:
`discussion` (Decision→Message), `implementation` (Decision→Commit), and
`revision` (Decision→DocVersion). `vote` has no snapshot source and is not
emitted.

## Id namespacing

Node ids are globally unique and namespaced by label, so a handle equal to an
RFC number cannot collide:

| Node | id |
|---|---|
| Decision | `rfc:{rfc}` |
| Person | `person:{handle}` |
| Message | `message:{comment_id}` |
| Commit | `commit:{sha}` |
| DocVersion | `docversion:{rfc}` |
| Team | `team:{label}` |
| Area | `area:{label}` |
| Concept | `concept:{key}` |

## Team / Area derivation

The committed snapshot contains no `OWNERS` files, so the only derivation
source is the RFC's `labels`:

- a label starting `T-` becomes `:Team {name: <label>}`
- a label starting `A-` becomes `:Area {name: <label>}`
- every other label is ignored

Verified against the pinned snapshot: 20 distinct `T-` labels and 166 distinct
`A-` labels; 1,323 RFCs carry a `T-` label and 730 an `A-` label. `MEMBER_OF`
(Person→Team) has no snapshot source and is not emitted.

## `DocVersion` is one content-hash snapshot per RFC

Each RFC whose `content` is non-null gets exactly one `DocVersion`
(`docversion:{rfc}`) carrying `sha = sha256(content)`, `ts = decided_on or
proposed_on`, and `content_ref = url`. It is linked to its Decision by both
`HAS_VERSION` and `EVIDENCED_BY {type: "revision"}`. 642 of the 2,309 RFCs
carry markdown. Per-commit `DocVersion`s were rejected: `Commit` nodes already
capture revision events, and duplicating them would muddy `EVIDENCED_BY`
typing.

The parser contract is why `build_payload` takes a separate `contents`
mapping: `ingest.parsers.parse_decision` deliberately drops the RFC markdown
(it is only needed for this hash), so the loader passes the raw
`rfc -> content` mapping alongside the parsed decisions.

## Concepts and stance edges are deferred to Phase 2/3

The §15.3 reference query needs `Concept {name: "trait objects"}` and
`OBJECTED` edges, but deriving them over the real corpus is model work:

- `ingest.parsers.parse_message` leaves `stance_hint = None` "for Phase-3
  classification".
- `PRD.md` §12 Phase 3 assigns "confidence-stamped stance edges" to the polish
  phase.

Phase 1 therefore provides the **seam**, not the derivation:
`build_payload(..., concepts=(), stances=())` maps explicit enrichment records
to `Concept` nodes + `ABOUT` edges and to
`OBJECTED|SUPPORTED|MODERATED {evidence, confidence}` edges. The integration
fixture carries `concepts.jsonl` / `stances.jsonl` so the reference query is
proven in CI; the committed `snapshot/` has neither, so the real graph has zero
`Concept` and zero stance nodes today (verified: `MATCH (d)-[:ABOUT]->(c)
RETURN count(c)` → 0).

## Load, don't extract (Phase 1)

Phase 1 loads the already schema-shaped parser dicts deterministically through
GraphRAG-SDK v1.1.0's connection and storage layer (`FalkorDBConnection` +
`GraphStore`). It does **not** run the SDK's LLM extraction pipeline:

- The extraction pipeline unconditionally builds `Document`/`Chunk` nodes and
  `MENTIONED_IN` edges and indexes chunks through an embedder. Those labels and
  relationships are outside §15.3 (violating the "exactly match" invariant) and
  would drag an embedder into a path CI runs with an empty `OPENROUTER_API_KEY`.
- The parser output is already schema-shaped, so LLM extraction on it is
  redundant.

The SDK's extraction path is reserved for the Phase-2/3 Concept/stance
derivation behind the same `SCHEMA`.

## Idempotency rides on `MERGE`-on-`id`, not `apply_changes`

`GraphStore.upsert_nodes` runs `MERGE (n:Label {id}) SET n += properties` and
`upsert_relationships` runs `MATCH ... MERGE (a)-[r:TYPE]->(b) SET r +=
properties`. Re-running an unchanged payload therefore only re-`MERGE`s and
leaves node and edge counts unchanged. The SDK's `GraphRAG.apply_changes` file
content-hash path is not used: it is file-path based, drives the extraction
pipeline, and there are no per-RFC files (only JSONL).

## `id` indexes are required, not an optimisation

The SDK's `MERGE`/`MATCH` on `{id}` full-scans a label when no index exists.
On the real corpus (28,483 nodes) a relationship batch exceeds the connection's
10 s query timeout, the circuit breaker opens, and the relationship load writes
**zero** edges while still reporting success. `load_payload` therefore creates
an `id` index per schema label (plus `__Entity__`, which every node carries)
before writing; creating an existing index raises "already indexed", which is
swallowed so re-runs stay idempotent. With the indexes the full load runs in
~7 s (measured) instead of timing out.

## Data honesty: RFCs with no evidence

1,110 of the 2,309 RFCs have no PR comment, no commit, and no `content` in the
pinned snapshot, so no provenance edge exists for them. The `PROPOSED_BY` edge
is emitted wherever an author exists (all 2,309 RFCs have one); the
`EVIDENCED_BY` invariant is emitted wherever evidence exists. The 1,110 is
recorded rather than papered over.

## Retrieval indexes are derived, out-of-band data (Phase 2)

`retrieve_evidence` (PRD §7.1) seeds from a FalkorDB vector index and a
full-text index. Neither is a canonical §15.3 property, so the loader creates
them and never writes them through a `Payload` node:

- **Full-text:** `Decision.title`. The graph deliberately stores no Message
  body or RFC content (only `text_ref`/`content_ref`), so there is nothing else
  to index; indexing the missing bodies would be a separate schema decision.
  Only `Decision.title` is indexed because the full-text seed queries only
  Decisions (a `Commit.message` index would have no caller).
- **Vector:** `Decision.embedding`, a `vecf32` stamped from committed vectors.

The full-text index is created **before** `upsert_nodes` because FalkorDB only
picks up entities written after the index exists (an index created after the
nodes stays empty until the next write). Index creation is idempotent the same
way the `id` indexes are: re-creating an existing index raises "already
indexed", which `_create_index` swallows.

### The vector seed is committed data, not a boot-time embed

`snapshot/decision-embeddings.jsonl` holds a metadata row (`model`,
`dimension`) followed by one `{rfc, vector}` per RFC, produced once by
`python -m ingest.embeddings` with the OpenRouter embeddings endpoint.
Committing them (rather than embedding at seed-on-boot) is the only route that
keeps automated CI at **zero LLM calls** *and* keeps judge replay at **≈ $0**,
while still doing the vector search **in FalkorDB** (no in-memory side channel).
Boot-time embedding would need a key and spend money on every fresh boot;
a local CPU model would drag a model download into every deploy and into CI.

The vector is written by raw Cypher (`SET d.embedding = vecf32(item.vector)`),
never through `upsert_nodes`: `GraphStore` would store a plain float array,
which is not a `vecf32` and would break the vector index. `validate_payload`
therefore still rejects an `embedding` key in a payload. The embedding model
slug and dimension are shared config (`EMBEDDING_MODEL_SLUG` /
`EMBEDDING_DIMENSION`, default `openai/text-embedding-3-small`, 1536) so
document and query embeddings come from the same space. The artifact records
the model slug and dimension that produced its vectors; `load_payload` compares
them against that config and refuses to build the index when they disagree —
otherwise a dimension mismatch would fail every vector query and a
same-dimension/different-model mismatch would silently search with vectors from
another space. `read_decision_embeddings` also rejects a vector whose length
disagrees with the recorded dimension.

When the embeddings file is absent (as in CI), the loader creates no vector
index and `retrieve_evidence` degrades to full-text plus traversal — so the
real FalkorDB path is exercised with no LLM call, and the demo still works if
the embeddings artifact is missing.

