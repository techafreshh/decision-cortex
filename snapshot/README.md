# Snapshot — the committed `rust-lang/rfcs` corpus

This directory is the one-time corpus snapshot the whole product replays: a
committed, quota-free copy of the RFC decision record so re-ingestion is local
and judges pay nothing to run it (`PRD.md` §4 "One-time RFC snapshot", §12
Phase 0).

Three newline-terminated JSONL files, one UTF-8 JSON object per line, plus an
optional fourth (`decision-embeddings.jsonl`) that the retrieval vector seed
reads:

| File | One record per | Key fields |
|---|---|---|
| `rfcs.jsonl` | pull request (RFC) | `rfc`, `title`, `status`, `proposed_on`, `decided_on`, `supersedes_rfc`, `author`, `url`, `labels`, `body`, `content` (markdown, or `null`) |
| `pr-comments.jsonl` | PR conversation comment | `pr_id`, `comment_id`, `author`, `ts`, `body`, `url`, `truncated` |
| `commits.jsonl` | commit touching an RFC text file | `sha`, `rfc`, `ts`, `message`, `url` |
| `decision-embeddings.jsonl` | embedder metadata (first line), then one RFC embedding per line | metadata: `model`, `dimension`; vectors: `rfc`, `vector` (float array) |

The three harvest record shapes are pinned by the validators in
[`ingest/snapshot_pipeline.py`](../ingest/snapshot_pipeline.py) and exercised by
the offline test `ingest/tests/test_snapshot_pipeline.py`; the optional
`decision-embeddings.jsonl` shape is read by
[`ingest/embeddings.py`](../ingest/embeddings.py) and exercised by
`ingest/tests/test_embeddings.py`.

## Fetch command

```bash
GITHUB_TOKEN=<pat> python -m ingest.fetch_snapshot
```

Optional flags: `--repo` (default `rust-lang/rfcs`), `--out` (default
`snapshot`), `--cache` (default `.snapshot-cache`). The command writes the three
files in place; there is no separate build step.

## Pinned run

- **Pinned date:** 2026-10-14 (the Phase-0 deadline; `PRD.md` §12).
- **Corpus:** `rust-lang/rfcs` at `main` (`pushed_at` 2026-10-05).
- **Record counts:** 2,309 RFCs (1,130 merged · 214 active · 965 rejected),
  21,623 PR comments, 3,552 commits.

## Decision embeddings (retrieval vector seed)

`decision-embeddings.jsonl` is **not** part of the GitHub harvest and is **not
committed** until it has been generated with a real key. It is produced once,
at event time, from `rfcs.jsonl`:

```bash
OPENROUTER_API_KEY=<key> python -m ingest.embeddings
```

Each RFC's title plus a bounded prefix of its markdown is embedded with
`openai/text-embedding-3-small` (1536 dims by default; override with
`EMBEDDING_MODEL_SLUG`/`EMBEDDING_DIMENSION`). The file's first line records the
`model` and `dimension` that produced the vectors, so the loader can refuse an
artifact that does not match the query embedder's configuration (see
`docs/graph-schema-notes.md`). The vectors are committed so the loader can stamp
them onto `Decision` nodes and build the FalkorDB vector index with no LLM call
at seed time — keeping CI at zero LLM calls and judge replay at ≈ $0. The loader
treats the file as optional: without it there is no vector index and retrieval
falls back to full-text plus traversal.

## PAT scope

`GITHUB_TOKEN` (or `GH_TOKEN`) **must be set** — `python -m ingest.fetch_snapshot`
exits with an error otherwise — but **no token scope is required**: the harvest
only reads public repository data, so any token that can read `rust-lang/rfcs`
works, including a classic PAT with no scopes. The token used for the pinned run
was a classic PAT carrying `public_repo` (read); the one provided for this run
additionally carried `repo`, `workflow`, `gist` and `read:org`, none of which
the fetcher uses. Use the narrowest token that still reads the public repo.

## Methodology

- **RFCs** are the repository's pull requests (`GET /pulls?state=all`).
  `status` is derived from the PR: merged → `merged`; open → `active`; closed
  without a merge → `rejected` (`PRD.md` §15.3 normalizes `merged`→`accepted`
  and `active`→`proposed` downstream). `content` is the RFC markdown the pull
  request owns (`text/NNNN-*.md`); ownership is the file's leading number, and
  for the one file whose number has no pull request it is resolved from the
  pull request that introduced the file's earliest commit. A pull request that
  owns several files (a rename leaves a redirect stub) takes the longest as its
  RFC, and a pull request that owns no markdown carries `null` — so a genuine
  absence is never confused with a harvest miss. `supersedes_rfc` is a
  best-effort link parsed from an explicit `supersedes #N` in the PR body or
  RFC text (rare in this corpus; the graph phase derives real supersede chains).
- **PR comments** are the pull request conversation comments
  (`GET /issues/comments`, filtered to PR numbers). `pr-comments.jsonl` holds at
  most **100 comments per PR**; every retained comment carries `truncated`,
  `true` when the cap clipped a longer thread (`AGENTS.md` provenance honesty).
- **Commits** are the commits that touched each RFC text file
  (`GET /commits?path=text/…`), tagged with the RFC number.
- **Rate-limit safety:** honors `GITHUB_TOKEN`/`GH_TOKEN`, retries with backoff
  on 403/429/5xx and transient network errors, waits out the primary rate-limit
  reset window, and caches every raw response under `--cache` so an interrupted
  run resumes instead of restarting.
- **Idempotency:** output is de-duplicated by identity, rendered
  deterministically, and rewritten only when the rendered content changes, so
  re-running over an unchanged corpus is a content-hash no-op with no duplicate
  lines.

No FalkorDB import and no LLM call: the fetcher and pipeline are pure GitHub
REST plus file I/O (`AGENTS.md` prep line).
