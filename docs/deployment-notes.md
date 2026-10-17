# Deployment notes — the one-command local brain

Evidence and rationale for `infra/` (issue #12): the `docker compose up --build`
path a judge runs with a single OpenRouter key. Everything below is a decision
that a reader should be able to re-derive, not a magic incantation.

## Topology

Three long-running services, matching `PRD.md` §8:

| Service | Image | Role | Reachable from host |
|---|---|---|---|
| `falkordb` | `falkordb/falkordb:6.0.2` | the graph (named volume `falkordb-data`) | no |
| `api` | built from `infra/api.Dockerfile` | FastAPI (`api.main:app`) + seed-on-boot | via `web` |
| `web` | built from `infra/web.Dockerfile` | Caddy: SPA `dist` + reverse proxy to `api` | `http://localhost:8080` |

`falkordb` has **no host port**: the graph is reachable only by the `api` (and,
later, the read-only MCP peephole) — the browser never mutates it. The `api`
waits on `falkordb`'s `redis-cli ping` healthcheck, so it never seeds against a
half-open database.

```bash
cp infra/.env.example infra/.env   # set OPENROUTER_API_KEY
docker compose -f infra/docker-compose.yml up -d --build
curl -fsS http://localhost:8080/healthz   # -> {"status":"ok","seeded":true}
```

## Seed-on-boot lives in the `api` entrypoint

The `api` container command is
`python -m api.seed && exec uvicorn api.main:app --host 0.0.0.0 --port 8000`.
`api.seed.seed_if_empty` counts `Decision` nodes and their edges and skips the
load when the graph is already complete, printing
`seed-on-boot: graph already seeded`; a graph with no Decisions (or Decisions but
no edges — the loader commits nodes before relationships, so an interrupted boot
can leave exactly that) is loaded from the committed snapshot and prints
`seed-on-boot: seeded snapshot`. `uvicorn` is `exec`'d so it owns PID 1 and
receives stop signals.

Two alternatives were rejected:

- **A FastAPI lifespan/startup hook.** It would put a 28k-node database write
  inside app startup, so any `TestClient(app)` in the unit suite could trigger a
  full ingest whenever a developer has a local FalkorDB, and it couples
  `api.main` to `ingest` at import time. The entrypoint keeps the app
  side-effect-free and the tests hermetic.
- **A separate one-shot `seed` init service.** It adds a fourth service beyond
  the issue's three-service topology and shows an exited container in the
  judge's `up` output. The entrypoint keeps the seed inside `api`.

The loader (`ingest.graph.ingest_snapshot`) is idempotent and LLM-free, so even
a fresh load costs no GitHub fetch and no extraction tokens; the guard just
makes a restart cheap and observable.

## Why the `api` image copies `ingest/` and `snapshot/`

`pyproject.toml` declares `packages = ["api"]`, and `api/retrieval.py` records
that the wheel ships without `ingest`. Rather than broaden the published wheel,
the image copies `ingest/` and `snapshot/` into `/app` and sets
`PYTHONPATH=/app`, so `import ingest` resolves at container runtime. `api.main`
never imports `ingest`; only `api.seed` does, and lazily inside
`_load_snapshot`. The wheel boundary is untouched.

The builder stage installs `build-essential` because `hnswlib` — a transitive
`graphrag-sdk` dependency — ships **sdist-only** and must compile. It is
discarded in the runtime stage, so the toolchain never reaches the shipped
image.

## `/healthz` reports the real seed state

`GET /healthz` returns exactly `{"status": "ok", "seeded": <bool>}`. `seeded`
comes from a live `MATCH (d:Decision) RETURN count(d)` plus
`MATCH ()-[r]->() RETURN count(r)` through `api.seed.graph_is_seeded`, so a
partial load (Decisions with no edges) reports `seeded: false` and the next boot
heals it; any read failure (including an unreachable database) is caught and
reported as `seeded: false`, never a crash or a non-200. That keeps two things
true at once: the probe answers offline (`scripts/run_scenario_api.sh` polls
`/healthz` with no database), and it tells the truth once a graph is present
instead of a startup flag that can go stale.

## Caddy routing and the `try_files` ordering pitfall

`infra/Caddyfile` puts the API routes in their own `handle` blocks:

```
handle /ask*     { reverse_proxy api:8000 }
handle /node/*   { reverse_proxy api:8000 }
handle /healthz  { reverse_proxy api:8000 }
handle           { root * /srv; try_files {path} /index.html; file_server }
```

Caddy runs `try_files` **before** `reverse_proxy`, so a bare site-level
`try_files {path} /index.html` would rewrite `/ask` to the SPA shell before it
could be proxied. `handle` blocks are mutually exclusive and Caddy sorts them by
matcher specificity, so the specific API matchers are evaluated before the
unmatched catch-all. The SPA calls relative paths (`web/src/api/ask.ts`
`fetch('/ask')`, `web/src/api/node.ts` `fetch('/node/…')`), so serving both from
one origin needs no CORS.

`SITE_ADDRESS` defaults to `:80` (plain HTTP, published on host `8080`). Set it
to a hostname on a VPS and Caddy provisions automatic HTTPS.

## `.env` and the `.gitignore` gotcha

`.gitignore` ignores `.env` and `.env.*`, which also matched
`infra/.env.example`; a negation (`!infra/.env.example`) keeps the committed
template tracked while secrets stay ignored. The template documents
`OPENROUTER_API_KEY` (required for answers, empty is legal for boot/seed/healthz)
and `SPEND_CAP_USD=10`. The spend cap needs no new code — `api/llm.py` already
enforces `SPEND_CAP_USD` and the ledger is surfaced live in the UI footer.

## Verification

`compose-smoke.yml` boots the stack, polls `/healthz` until `seeded: true`,
checks Caddy serves the SPA and proxies an API-only route (`/node/__probe__`
returns the API's 404, not the SPA's 200), then restarts `api` and asserts the
logs contain `graph already seeded` (the guard path, acceptance criterion 5).
Locally the same steps are the `curl` calls above plus `docker compose restart api`.
The route set itself is bound to the app by `api/tests/test_route_contract.py`,
which fails if an `api.main` route has no Caddy `handle` matcher or Vite proxy
entry.
