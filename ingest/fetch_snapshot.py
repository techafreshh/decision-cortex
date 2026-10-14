"""Rate-limit-safe GitHub REST fetcher that builds the committed snapshot corpus.

Usage (from the repository root)::

    GITHUB_TOKEN=<pat> python -m ingest.fetch_snapshot

Harvests every pull request of ``rust-lang/rfcs`` (the RFC records), the
conversation comments on those pull requests (capped at
``snapshot_pipeline.COMMENT_CAP`` per PR), and the commit history of each
merged RFC text file, writing ``snapshot/rfcs.jsonl``, ``snapshot/pr-comments.jsonl``
and ``snapshot/commits.jsonl`` — one UTF-8, newline-terminated JSON object per
line. See ``snapshot/README.md`` for the pinned run and the methodology.

Rate-limit safety: honors ``GITHUB_TOKEN``/``GH_TOKEN``, retries with backoff
on 403/429 and 5xx (waiting out the reset window when the primary rate limit is
exhausted), and caches every raw response under ``--cache`` so an interrupted
run resumes instead of restarting. Output writes are idempotent.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ingest import snapshot_pipeline as pipeline

API_ROOT = "https://api.github.com"
USER_AGENT = "decision-cortex-snapshot"
DEFAULT_REPO = "rust-lang/rfcs"
DEFAULT_OUT = "snapshot"
DEFAULT_CACHE = ".snapshot-cache"
PER_PAGE = 100


class GitHubClient:
    """Cached, retrying GitHub REST client.

    Every response body is stored under ``cache_dir`` keyed by request URL, so
    a re-run (or a resumed run) performs no network calls for what it already
    fetched.
    """

    def __init__(
        self,
        token: str,
        cache_dir: str | Path,
        *,
        max_retries: int = 6,
        timeout: float = 30.0,
    ) -> None:
        self._token = token
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._max_retries = max_retries
        self._timeout = timeout

    def get(self, url: str) -> Any:
        return self._get_page(url)[0]

    def paginate(
        self, path: str, *, params: dict[str, Any] | None = None
    ) -> Iterator[Any]:
        """Yield items, following GitHub's ``Link: rel="next"`` until exhausted."""
        query = dict(params or {}, per_page=PER_PAGE)
        url = f"{API_ROOT}{path}?{urllib.parse.urlencode(query)}"
        while url:
            items, url = self._get_page(url)
            if not isinstance(items, list):
                raise TypeError(f"expected a list from {url}")
            yield from items

    def _get_page(self, url: str) -> tuple[Any, str | None]:
        cache_path = self._cache_path(url)
        if cache_path.exists():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
        else:
            cached = self._request(url)
            cache_path.write_text(json.dumps(cached), encoding="utf-8")
        return cached["data"], cached.get("next")

    def _cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self._cache_dir / f"{digest}.json"

    def _request(self, url: str) -> dict[str, Any]:
        headers = {"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        for attempt in range(self._max_retries + 1):
            request = urllib.request.Request(url, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=self._timeout) as response:
                    return {
                        "data": json.loads(response.read().decode("utf-8")),
                        "next": _next_link(response.headers.get("Link")),
                    }
            except urllib.error.HTTPError as error:
                delay = self._retry_delay(error, attempt)
                if delay is None:
                    raise RuntimeError(f"github {error.code} for {url}") from error
                print(
                    f"github {error.code} on {url}; retrying in {delay:.0f}s",
                    file=sys.stderr,
                )
                time.sleep(delay)
            except OSError as error:
                if attempt >= self._max_retries:
                    raise
                delay = min(2.0**attempt, 60.0)
                print(
                    f"network error on {url}: {error!r}; retrying in {delay:.0f}s",
                    file=sys.stderr,
                )
                time.sleep(delay)
        raise RuntimeError(f"exhausted retries for {url}")

    def _retry_delay(self, error: urllib.error.HTTPError, attempt: int) -> float | None:
        """Seconds to wait before retrying, or ``None`` to surface the error."""
        status = error.code
        if status not in (403, 429) and not 500 <= status < 600:
            return None
        retry_after = error.headers.get("Retry-After")
        if retry_after:
            return float(retry_after)
        if error.headers.get("X-RateLimit-Remaining") == "0":
            reset = error.headers.get("X-RateLimit-Reset")
            if reset:
                return max(0.0, float(reset) - time.time()) + 1.0
        return min(2.0**attempt, 60.0)


def fetch(repo: str, out_dir: Path, cache_dir: Path, token: str) -> None:
    """Harvest the corpus and write the three JSONL files."""
    client = GitHubClient(token, cache_dir)

    pulls = list(
        client.paginate(
            f"/repos/{repo}/pulls",
            params={"state": "all", "sort": "created", "direction": "asc"},
        )
    )
    print(f"pulls: {len(pulls)}", file=sys.stderr)
    pull_numbers = {pull["number"] for pull in pulls}

    text_paths = _rfc_text_paths(client, repo)

    rfcs = [
        pipeline.normalize_rfc(
            pull, content=_rfc_content(client, repo, text_paths.get(pull["number"]))
        )
        for pull in pulls
    ]
    print(
        f"rfcs: {len(rfcs)} (text bodies: {len(text_paths)})",
        file=sys.stderr,
    )
    pipeline.merge_jsonl(out_dir / "rfcs.jsonl", rfcs, key=lambda record: record["rfc"])

    comments_by_pr: dict[int, list[dict[str, Any]]] = {}
    for comment in client.paginate(
        f"/repos/{repo}/issues/comments",
        params={"sort": "created", "direction": "asc"},
    ):
        number = _issue_number(comment["issue_url"])
        if number in pull_numbers:
            comments_by_pr.setdefault(number, []).append(comment)

    comments = []
    for number, thread in comments_by_pr.items():
        kept, truncated = pipeline.cap_comments(thread)
        comments.extend(
            pipeline.normalize_comment(
                comment, pr_id=number, truncated=truncated
            )
            for comment in kept
        )
    print(f"pr-comments: {len(comments)}", file=sys.stderr)
    pipeline.merge_jsonl(
        out_dir / "pr-comments.jsonl",
        comments,
        key=lambda record: record["comment_id"],
    )

    commits = []
    for number, path in sorted(text_paths.items()):
        for commit in client.paginate(f"/repos/{repo}/commits", params={"path": path}):
            commits.append(pipeline.normalize_commit(commit, rfc=number))
    print(f"commits: {len(commits)}", file=sys.stderr)
    pipeline.merge_jsonl(
        out_dir / "commits.jsonl",
        commits,
        key=lambda record: (record["rfc"], record["sha"]),
    )


def _rfc_text_paths(client: GitHubClient, repo: str) -> dict[int, str]:
    """Map RFC number -> ``text/NNNN-*.md`` path from the repository tree."""
    tree = client.get(f"{API_ROOT}/repos/{repo}/git/trees/main?recursive=1")
    paths: dict[int, str] = {}
    for entry in tree.get("tree", []):
        path = entry.get("path", "")
        if entry.get("type") != "blob" or not path.startswith("text/"):
            continue
        if not path.endswith(".md"):
            continue
        number = _leading_number(Path(path).name)
        if number is not None:
            paths[number] = path
    return paths


def _rfc_content(client: GitHubClient, repo: str, path: str | None) -> str:
    if path is None:
        return ""
    payload = client.get(f"{API_ROOT}/repos/{repo}/contents/{path}")
    return base64.b64decode(payload["content"]).decode("utf-8")


def _next_link(link_header: str | None) -> str | None:
    """Extract the ``rel="next"`` URL from a GitHub ``Link`` header, if any."""
    if not link_header:
        return None
    for part in link_header.split(","):
        url, _, rel = part.partition(";")
        if rel.strip() == 'rel="next"':
            return url.strip().strip("<>")
    return None


def _leading_number(name: str) -> int | None:
    digits = ""
    for char in name:
        if not char.isdigit():
            break
        digits += char
    return int(digits) if digits else None


def _issue_number(issue_url: str) -> int:
    return int(issue_url.rstrip("/").rsplit("/", 1)[-1])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=DEFAULT_REPO, help="owner/name to harvest")
    parser.add_argument("--out", default=DEFAULT_OUT, help="snapshot output directory")
    parser.add_argument("--cache", default=DEFAULT_CACHE, help="raw response cache")
    args = parser.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        parser.error("GITHUB_TOKEN (or GH_TOKEN) must be set")

    fetch(args.repo, Path(args.out), Path(args.cache), token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
