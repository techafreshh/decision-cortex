# Phase-1 smoke — snapshot → FalkorDB 6.x

Evidence that the Phase-1 ingestion (issue #5) loads the committed snapshot as
the canonical `PRD.md` §15.3 graph, provenance-edged, and that a re-run is a
count no-op. Recorded against a local FalkorDB reached through the same
`FALKORDB_HOST` / `FALKORDB_PORT` interface the CI service container
(`.github/workflows/falkordb-integration.yml`, image `falkordb/falkordb:6.0.2`)
exposes.

## Command

```bash
FALKORDB_HOST=127.0.0.1 FALKORDB_PORT=6379 FALKORDB_GRAPH=decision_cortex \
  python -m ingest.graph snapshot
```

## Counts and the idempotency no-op

Two consecutive runs over the unchanged `snapshot/`:

| Run | CLI output | `MATCH (n)` | `MATCH ()-[r]->()` |
|---|---|---|---|
| 1 | `28483 nodes, 31938 edges` | 28,483 | 31,938 |
| 2 | `28483 nodes, 31938 edges` | 28,483 | 31,938 |

Per-label node counts (identical both runs): Decision 2,309 · Person 1,272 ·
Message 21,623 · Commit 2,451 · DocVersion 642 · Team 20 · Area 166.
Per-type edge counts: `PROPOSED_BY` 2,309 · `EVIDENCED_BY` 25,821 (discussion
21,623 + implementation 3,556 + revision 642) · `HAS_VERSION` 642 ·
`ASSOCIATED_TEAM` 1,554 · `AREA` 1,609 · `SUPERSEDES` 3.

The second run re-`MERGE`s every node/edge on its id and changes no count. The
automated form of this assertion is
`ingest/tests/test_graph_integration.py::test_reingest_is_count_idempotent`.

## End-to-end trace: RFC 1398 ("Allocators, take III")

| Step | Question | Cypher | Result |
|---|---|---|---|
| Decision | What did RFC 1398 decide? | `MATCH (d:Decision {rfc:1398}) RETURN d.title, d.status` | `Allocators, take III`, `accepted` |
| Proposer | Who proposed it? | `MATCH (d:Decision {rfc:1398})-[:PROPOSED_BY]->(p:Person) RETURN p.handle` | `pnkfelix` |
| Comments | How many PR comments? | `MATCH (d:Decision {rfc:1398})-[:EVIDENCED_BY {type:'discussion'}]->(m:Message) RETURN count(m)` | `100` |
| Comment sample | What do the first comments look like? | `... RETURN m.comment_id, m.author, m.truncated, m.text_ref ORDER BY m.ts LIMIT 3` | `162336346 / pnkfelix / true`, `162367202 / arielb1 / true`, `162368163 / arielb1 / true` |
| Version | What is its content hash? | `MATCH (d:Decision {rfc:1398})-[:HAS_VERSION]->(v:DocVersion) RETURN v.sha, v.ts` | `940fa5b8…8752c1`, `2016-04-08T20:58:11Z` |
| Commit | What commit implemented it? | `MATCH (d:Decision {rfc:1398})-[:EVIDENCED_BY {type:'implementation'}]->(c:Commit) RETURN c.sha ORDER BY c.ts LIMIT 1` | `bdbe73d1…130bcf` (`merge rfc #1398`) |
| Teams | Which teams own it? | `MATCH (d:Decision {rfc:1398})-[:ASSOCIATED_TEAM]->(t:Team) RETURN t.name` | `T-libs-api`, `T-lang` |
| Areas | Which areas does it touch? | `MATCH (d:Decision {rfc:1398})-[:AREA]->(a:Area) RETURN a.name` | `A-traits-libstd`, `A-machine`, `A-allocation` |

Every comment in this thread is `truncated: true` because the harvest hit the
100-comment-per-PR cap (`AGENTS.md` provenance honesty) — the flag is preserved
in the graph, not hidden.

## 20-question smoke Q&A

| # | Question | Cypher (abbreviated) | Observed result |
|---|---|---|---|
| 1 | What did RFC 1398 decide? | `MATCH (d:Decision {rfc:1398}) RETURN d.title, d.status` | Allocators, take III / accepted |
| 2 | Who proposed RFC 1398? | `MATCH (d:Decision {rfc:1398})-[:PROPOSED_BY]->(p) RETURN p.handle` | pnkfelix |
| 3 | Which teams own RFC 1398? | `MATCH (d:Decision {rfc:1398})-[:ASSOCIATED_TEAM]->(t) RETURN t.name` | T-libs-api, T-lang |
| 4 | How many comments on RFC 1398? | `MATCH (d:Decision {rfc:1398})-[:EVIDENCED_BY {type:'discussion'}]->(m) RETURN count(m)` | 100 |
| 5 | How many of them are truncated? | `... WHERE m.truncated RETURN count(m)` | 100 |
| 6 | RFC 1398 content hash? | `MATCH (d:Decision {rfc:1398})-[:HAS_VERSION]->(v) RETURN v.sha` | 940fa5b8…8752c1 |
| 7 | Commit that implemented RFC 1398? | `MATCH (d:Decision {rfc:1398})-[:EVIDENCED_BY {type:'implementation'}]->(c) RETURN c.sha ORDER BY c.ts LIMIT 1` | bdbe73d1…130bcf |
| 8 | How many decisions did `T-lang` own? | `MATCH (d:Decision)-[:ASSOCIATED_TEAM]->(:Team {name:'T-lang'}) RETURN count(d)` | 741 |
| 9 | How many decisions did `A-syntax` cover? | `MATCH (d:Decision)-[:AREA]->(:Area {name:'A-syntax'}) RETURN count(d)` | 143 |
| 10 | How many decisions did nikomatsakis propose? | `MATCH (:Person {handle:'nikomatsakis'})<-[:PROPOSED_BY]-(d) RETURN count(d)` | 69 |
| 11 | Status distribution? | `MATCH (d:Decision) RETURN d.status, count(*) ORDER BY d.status` | accepted 1130 · proposed 214 · rejected 965 |
| 12 | How many truncated threads overall? | `MATCH (m:Message) RETURN m.truncated, count(*) ORDER BY m.truncated` | false 18523 · true 3100 |
| 13 | How many people are in the graph? | `MATCH (n:Person) RETURN count(n)` | 1272 |
| 14 | How many commits? | `MATCH (n:Commit) RETURN count(n)` | 2451 |
| 15 | How many decisions carry a DocVersion? | `MATCH (n:DocVersion) RETURN count(n)` | 642 |
| 16 | Which RFCs supersede which? | `MATCH (a:Decision)-[:SUPERSEDES]->(b:Decision) RETURN a.rfc, b.rfc` | 1426→1401 · 2103→1755 · 3396→1861 |
| 17 | How many PROPOSED_BY edges? | `MATCH ()-[r:PROPOSED_BY]->() RETURN count(r)` | 2309 |
| 18 | How many distinct teams? | `MATCH (t:Team) RETURN count(t)` | 20 |
| 19 | Who objected to RFC 1398? | `MATCH (p:Person)-[o:OBJECTED]->(d:Decision {rfc:1398}) RETURN p.handle` | (no rows — stance edges are Phase 2/3, see below) |
| 20 | What concepts are about RFC 1398? | `MATCH (d:Decision {rfc:1398})-[:ABOUT]->(c:Concept) RETURN c.name` | (no rows — Concept/`ABOUT` is Phase 2/3) |

Rows 19–20 are honest zero-answers, not failures: Phase 1 defers stance and
Concept derivation to Phases 2/3 (`docs/graph-schema-notes.md`). The §15.3
reference query is proven end-to-end in CI against a fixture that carries
`concepts.jsonl` / `stances.jsonl`
(`ingest/tests/test_graph_integration.py::test_reference_query_returns_expected_rows`);
on the real corpus it returns no rows because the committed snapshot has no
enrichment.
