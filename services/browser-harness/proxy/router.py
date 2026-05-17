"""Host pattern → (platform, backend) routing.

Decision order, per PROTOCOL_v2.md §3:
  1. Explicit X-Aki-Platform header (handled in server.py).
  2. Last-bound platform for this (org, agent) (handled in pool).
  3. Host pattern lookup (this module).
  4. Default fallback ("default" platform, Steel backend).

The default table is deliberately small — adding more sites is a
config change, not a code change. Customers extend via the
BROWSER_HARNESS_PLATFORM_ROUTES env var (JSON map).
"""
from __future__ import annotations

import fnmatch
import json
import logging
import os
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

log = logging.getLogger(__name__)

# Backends. Strings, not enums, because they flow through to the
# manifest JSON in R2 — easier to add a new vendor later without a
# migration if we just append a string.
BACKEND_STEEL = "steel"
BACKEND_BROWSERBASE = "browserbase"
KNOWN_BACKENDS = (BACKEND_STEEL, BACKEND_BROWSERBASE)

DEFAULT_PLATFORM = "default"


@dataclass(frozen=True)
class Route:
    platform: str
    backend: str


# Default routing table. Pattern is glob (fnmatch), matched against the
# lowercased hostname only (no port, no path).
DEFAULT_ROUTES: list[tuple[str, Route]] = [
    ("linkedin.com",       Route("linkedin", BACKEND_BROWSERBASE)),
    ("*.linkedin.com",     Route("linkedin", BACKEND_BROWSERBASE)),
    ("twitter.com",        Route("twitter",  BACKEND_BROWSERBASE)),
    ("x.com",              Route("twitter",  BACKEND_BROWSERBASE)),
    ("*.x.com",            Route("twitter",  BACKEND_BROWSERBASE)),
    # Add more (instagram, facebook, …) here as they prove out.
]


def _load_extra_routes() -> list[tuple[str, Route]]:
    """Parse BROWSER_HARNESS_PLATFORM_ROUTES env (a JSON map) into
    Route entries. Silent skip on bad entries — we'd rather degrade to
    default routing than fail to boot on a typo."""
    raw = os.environ.get("BROWSER_HARNESS_PLATFORM_ROUTES")
    if not raw:
        return []
    try:
        m = json.loads(raw)
    except json.JSONDecodeError as e:
        log.warning("BROWSER_HARNESS_PLATFORM_ROUTES is not valid JSON: %s", e)
        return []
    out: list[tuple[str, Route]] = []
    for pattern, spec in (m or {}).items():
        if not isinstance(spec, dict):
            continue
        platform = spec.get("platform")
        backend = spec.get("backend")
        if not platform or backend not in KNOWN_BACKENDS:
            log.warning("skipping invalid route %r: %r", pattern, spec)
            continue
        out.append((pattern.lower(), Route(platform, backend)))
    return out


_ROUTES: list[tuple[str, Route]] = DEFAULT_ROUTES + _load_extra_routes()


def default_route() -> Route:
    """Where unknown hosts go. Configurable via BROWSER_HARNESS_DEFAULT_BACKEND
    (steel|browserbase). Default is steel — cheaper and the free tier
    covers most non-protected sites."""
    backend = os.environ.get("BROWSER_HARNESS_DEFAULT_BACKEND", BACKEND_STEEL).lower()
    if backend not in KNOWN_BACKENDS:
        log.warning(
            "BROWSER_HARNESS_DEFAULT_BACKEND=%r is not in %s; using steel",
            backend, KNOWN_BACKENDS,
        )
        backend = BACKEND_STEEL
    return Route(DEFAULT_PLATFORM, backend)


def route_for_url(url: str) -> Route:
    """Pick a Route for a navigation target. Always returns something —
    falls back to default_route() if no pattern matches."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        host = ""
    if not host:
        return default_route()
    for pattern, route in _ROUTES:
        if fnmatch.fnmatch(host, pattern):
            return route
    return default_route()


def route_for_platform(platform: str) -> Route:
    """Look up the Route for a platform name. If the platform name was
    set via X-Aki-Platform but doesn't match any configured route, we
    have to guess a backend — fall back to default_route()'s backend
    so explicit-header callers still work."""
    for _, route in _ROUTES:
        if route.platform == platform:
            return route
    # Custom platform name (e.g. "internal-tool"); honor it but route
    # to the default backend.
    return Route(platform, default_route().backend)
