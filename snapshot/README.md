# Snapshot — the committed `rust-lang/rfcs` corpus

This directory is the one-time corpus snapshot the whole product replays: a
committed, quota-free copy of the RFC decision record so re-ingestion is local
and judges pay nothing to run it (`PRD.md` §4 "One-time RFC snapshot", §12
Phase 0).

Three newline-terminated JSONL files, one UTF-8 JSON object per line:

| File | One record per | Key fields |
|---|---|---|
| `rfcs.jsonl` | pull request (RFC) | `rfc`, `title`, `status`, `proposed_on`, `decided_on`, `supersedes_rfc`, `author`, `url`, `labels`, `body`, `content` |
| `pr-comments.jsonl` | PR conversation comment | `pr_id`, `comment_id`, `author`, `ts`, `body`, `url`, `truncated` |
| `commits.jsonl` | commit touching an RFC text file | `sha`, `rfc`, `ts`, `message`, `url` |

The record shapes are pinned by the validators in
[`ingest/snapshot_pipeline.py`](../ingest/snapshot_pipeline.py) and exercised by
the offline test `ingest/tests/test_snapshot_pipeline.py`.

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

## PAT scope

The harvest only reads public repository data, so **no token scope is
required** — an unauthenticated run works, just with a lower rate limit. The
token used for the pinned run was a classic PAT carrying `public_repo` (read);
the one provided for this run additionally carried `repo`, `workflow`, `gist`
and `read:org`, none of which the fetcher uses. Use the narrowest scope you
have that still reads a public repo (`public_repo`, or none).

## Methodology

- **RFCs** are the repository's pull requests (`GET /pulls?state=all`).
  `status` is derived from the PR: merged → `merged`; open → `active`; closed
  without a merge → `rejected` (`PRD.md` §15.3 normalizes `merged`→`accepted`
  and `active`→`proposed` downstream). `content` is the RFC markdown read from
  the matching `text/NNNN-*.md` file for merged RFCs. `supersedes_rfc` is a
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
