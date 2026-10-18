# Decision Cortex — a company brain over `rust-lang/rfcs`

**Graph Hacks (WeMakeDevs × FalkorDB) · Track 3 · Oct 15–18, 2026**

2,309 real RFC decisions, 21,623 debate comments, and 2,704 classified
stances — one graph in FalkorDB, one question box. Answers arrive
sentence-by-sentence with a citation chip on every claim that opens the exact
GitHub comment it came from; questions the corpus never answered get an honest
*no record* verdict with receipts instead of a confabulation.

**Live demo:** https://decision-cortex.techa.pro (four scripted demo buttons
first, free chat second)

**Run it (one key, $0 to replay the demo):**

```bash
cp infra/.env.example infra/.env   # set OPENROUTER_API_KEY
docker compose -f infra/docker-compose.yml up -d --build
# -> http://localhost:8080  (healthz: seeded from the committed snapshot)
```

**Read next — the submission README:** [`docs/README.md`](docs/README.md)
(positioning, the graph mapped with live counts, an unedited production trace
of the graph shaping an answer, verification-set methodology, faithfulness
scoring, honest what's-real ledger)

Repo map: `snapshot/` the committed corpus · `ingest/` loader + stance/embedding
builders · `api/` the FastAPI agent core · `web/` the React SPA ·
`verification/` the pinned 40-question set · `infra/` compose + Caddy ·
`docs/` decision notes.
