"""Conformance between the FastAPI route set and its two hand-written mirrors.

The SPA calls the API by relative path, so both the Vite dev proxy
(``web/vite.config.ts``) and the Caddy production front door (``infra/Caddyfile``)
must forward every API route. Neither can import ``api.main``, so this test binds
their route sets to the app's declared routes and runs in the CI python job: a
route added to ``api.main`` without a matching proxy entry fails the build
instead of silently returning the SPA shell through Caddy.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.routing import APIRoute

from api.main import app

_ROOT = Path(__file__).resolve().parents[2]
_CADDYFILE = _ROOT / "infra" / "Caddyfile"
_VITE_CONFIG = _ROOT / "web" / "vite.config.ts"


def _api_route_prefixes() -> set[str]:
    """The first path segment of every route declared with ``@app.<method>``.

    FastAPI's built-in ``/docs``/``/openapi.json``/``/redoc`` handlers are
    Starlette ``Route``s, not ``APIRoute``s, so they are excluded.
    """
    return {
        "/" + route.path.strip("/").split("/", 1)[0]
        for route in app.routes
        if isinstance(route, APIRoute)
    }


@pytest.fixture(scope="module")
def caddy_source() -> str:
    if not _CADDYFILE.exists():
        pytest.skip(f"front door not present: {_CADDYFILE}")
    return _CADDYFILE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def vite_source() -> str:
    if not _VITE_CONFIG.exists():
        pytest.skip(f"dev proxy not present: {_VITE_CONFIG}")
    return _VITE_CONFIG.read_text(encoding="utf-8")


def _caddy_prefixes(source: str) -> set[str]:
    """The prefixes covered by the ``handle`` matchers (``/ask*`` -> ``/ask``)."""
    return {
        matcher.rstrip("*").rstrip("/")
        for matcher in re.findall(r"^\s*handle\s+(\S+)\s*\{", source, re.MULTILINE)
    }


def _vite_prefixes(source: str) -> set[str]:
    """The keys of the Vite ``proxy`` map."""
    return set(re.findall(r"'(/[^']*)':\s*apiTarget", source))


def test_caddy_proxies_every_api_route(caddy_source: str) -> None:
    missing = _api_route_prefixes() - _caddy_prefixes(caddy_source)
    assert not missing, f"Caddyfile has no handle matcher for {sorted(missing)}"


def test_vite_proxies_every_api_route(vite_source: str) -> None:
    missing = _api_route_prefixes() - _vite_prefixes(vite_source)
    assert not missing, f"vite proxy has no entry for {sorted(missing)}"
