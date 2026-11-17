"""Rate limiting.

A fixed-window counter in process memory. This is honest about its limits: with
N workers behind a load balancer you get N times the configured rate, because
each process counts separately. A real deployment puts Redis here.

It is still worth having. The threat this addresses is a single client hammering
the translate endpoint and burning the provider's free daily allowance, and one
process is enough to stop that.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass

from fastapi import HTTPException, Request, status


@dataclass(slots=True)
class _Window:
    count: int
    reset_at: float


class RateLimiter:
    """Fixed-window limiter keyed by an arbitrary string."""

    def __init__(self, limit: int, window_seconds: int) -> None:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        if window_seconds < 1:
            raise ValueError("window_seconds must be at least 1")
        self.limit = limit
        self.window = window_seconds
        self._windows: dict[str, _Window] = defaultdict(lambda: _Window(0, 0.0))

    def check(self, key: str) -> tuple[bool, int, float]:
        """Record a hit. Returns (allowed, remaining, seconds_until_reset)."""
        now = time.monotonic()
        window = self._windows[key]

        if window.reset_at <= now:
            window.count = 0
            window.reset_at = now + self.window

        window.count += 1
        remaining = max(0, self.limit - window.count)
        return window.count <= self.limit, remaining, max(0.0, window.reset_at - now)

    def reset(self, key: str | None = None) -> None:
        if key is None:
            self._windows.clear()
        else:
            self._windows.pop(key, None)

    def prune(self) -> int:
        """Drop expired windows. Called opportunistically to bound memory."""
        now = time.monotonic()
        dead = [k for k, w in self._windows.items() if w.reset_at <= now]
        for k in dead:
            self._windows.pop(k, None)
        return len(dead)


def client_key(request: Request) -> str:
    """Identify the caller.

    Behind a proxy the real address is in X-Forwarded-For. We take the first
    entry, which is the client as the proxy saw it. This is spoofable if the app
    is exposed directly, which is why the app is meant to run behind a proxy.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def make_limiter(limit: int, window_seconds: int):
    """Build a FastAPI dependency that enforces a limit."""

    limiter = RateLimiter(limit, window_seconds)

    async def dependency(request: Request) -> None:
        key = client_key(request)
        allowed, _remaining, reset_in = limiter.check(key)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "code": "rate_limited",
                    "message": (f"Too many requests. Try again in {int(reset_in) + 1} seconds."),
                },
                headers={
                    "Retry-After": str(int(reset_in) + 1),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                },
            )
        # Opportunistic cleanup so the dict cannot grow without bound.
        if limiter.prune() > 512:
            pass

    dependency.limiter = limiter  # type: ignore[attr-defined]
    return dependency


__all__ = ["RateLimiter", "client_key", "make_limiter"]
