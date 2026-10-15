# Verification set — 30 gold + 10 no-record questions

The pinned regression eval and the honesty backbone of the submission
(`PRD.md` §11.2, §15.4; `AGENTS.md` "Verification-set honesty"). It doubles as
the source for the UI's abstention buttons and as the input to the owner-only
`eval-run` workflow (`.github/workflows/eval-run.yml`).

## Files

| File | Purpose |
|---|---|
| `questions.jsonl` | The pinned set: exactly 40 newline-terminated JSON objects |
| `test_questions.py` | Offline shape + corpus-grounding validator (runs in offline CI) |

## Entry shapes

Gold entry — a question whose answer is a known decision in the snapshot:

```json
{"type":"gold","question":"…","expected_rfc":2394,"expected_citation":"https://github.com/rust-lang/rfcs/commit/…"}
```

- `question` — the natural-language question.
- `expected_rfc` — the RFC (pull request) number the answer must resolve to.
- `expected_citation` — the exact source URL of a PR comment or commit in the
  snapshot that records the decision.

No-record entry — a decision that does **not** exist in the corpus:

```json
{"type":"no_record","question":"…","verified_absent":true,"verification_method":"…"}
```

- `verified_absent` — always `true`; the question is asserted absent.
- `verification_method` — the concrete search performed during authoring and
  its result.

## Authoring method

The set is authored **against the committed snapshot**, never from memory
(`PRD.md` §15.4). Each gold entry was built by:

1. Selecting a decision from `snapshot/rfcs.jsonl` (its `rfc` number and
   `title`/`content`) and confirming the record's `status` is `merged`.
2. Finding the source that records the decision in `snapshot/commits.jsonl`
   (the commit whose message introduces/merges the RFC) or, for older RFCs
   predating the 2014 file-layout commit, a PR comment in
   `snapshot/pr-comments.jsonl`.
3. Pinning `expected_rfc` to the record's `rfc` and `expected_citation` to that
   source's `url`.

`test_questions.py` re-checks all of this offline: every `expected_rfc` must
exist in `snapshot/rfcs.jsonl`, and every `expected_citation` must be a URL
present in the snapshot whose owning RFC equals `expected_rfc`. A citation
that drifts from its RFC fails the build.

## Absence-verification method

Each no-record question is verified absent by a case-insensitive substring
search over all three snapshot files:

- `snapshot/rfcs.jsonl` — `title` + `body` + `content`
- `snapshot/pr-comments.jsonl` — `body`
- `snapshot/commits.jsonl` — `message`

The exact search terms and the match count (always 0 for the decision) are
recorded per entry in `verification_method`, including near-miss terms that
match only unrelated material. Example: the planet-mascot question searches
`'mascot planet'`, `'planet mascot'` and `'official mascot planet'` (0
matches), and notes that `'mascot'` alone matches only RFC 2328, a *rejected*
proposal to adopt Ferris.

## Honesty rule

Questions are never edited to make a metric pass (`AGENTS.md`). If a gold
question misses, it is triaged and recorded — never silently dropped or
reworded; if a no-record question turns out to be answerable, it is removed
from the negative set rather than the search being narrowed.

## Running

```bash
# Offline shape + grounding validator (also part of the repo's offline CI):
pytest -q -m 'not integration and not live'

# Owner-only real eval against the live stack (spend-capped, never on push/PR):
gh workflow run eval-run
```
