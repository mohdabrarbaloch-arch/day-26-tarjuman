"""Translation provider client.

MyMemory is the default because it needs no API key, which means the project
runs for anyone who clones it. It has three properties that shape this module:

1. A hard 500-character limit, returning HTTP 403 above it. We chunk.
2. A ``match`` field that is a constant 0.85 regardless of quality. We ignore it
   entirely and verify independently -- see ``app.core.verify``.
3. It returns HTTP 200 with the input echoed back for text it cannot translate.
   We treat that as a failure, not a success.

The client is deliberately thin. It translates one chunk and reports what
happened. All judgement lives in the verification layer, so the two can be
tested separately and the provider can be swapped without touching the verdict
logic.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings


class ProviderError(Exception):
    """The provider could not be reached or refused the request."""

    def __init__(self, message: str, *, status: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


class QuotaExceeded(ProviderError):
    """The provider's daily allowance is gone."""


@dataclass(frozen=True, slots=True)
class TranslationResult:
    """What the provider gave us for one chunk."""

    text: str
    provider: str
    cached: bool = False
    latency_ms: int = 0


# --- a small in-process cache ---------------------------------------------
#
# Translation is deterministic for a given (text, source, target), so caching is
# free accuracy. The cache is bounded and TTL'd because this is a single-process
# demo; a real deployment would put Redis here, and the interface is shaped so
# that swap is a one-line change.

_CACHE: dict[str, tuple[float, str]] = {}
_CACHE_MAX = 2048


def _cache_key(text: str, source: str, target: str) -> str:
    digest = hashlib.sha256(f"{source}|{target}|{text}".encode()).hexdigest()
    return digest


def _cache_get(key: str) -> str | None:
    entry = _CACHE.get(key)
    if entry is None:
        return None
    expires, value = entry
    if expires < time.monotonic():
        _CACHE.pop(key, None)
        return None
    return value


def _cache_put(key: str, value: str) -> None:
    if len(_CACHE) >= _CACHE_MAX:
        # Drop the oldest quarter. Cheap and good enough; a real cache would be
        # an LRU, but this keeps the module dependency-free.
        for old in list(_CACHE)[: _CACHE_MAX // 4]:
            _CACHE.pop(old, None)
    _CACHE[key] = (time.monotonic() + settings.cache_ttl_seconds, value)


def clear_cache() -> None:
    _CACHE.clear()


def cache_size() -> int:
    return len(_CACHE)


# --- the provider ----------------------------------------------------------


class MyMemoryProvider:
    """MyMemory's free GET endpoint. No key required."""

    name = "mymemory"
    max_chars = 500

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client
        self._owns_client = client is None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(settings.provider_timeout_seconds),
                headers={"User-Agent": settings.user_agent},
            )
        return self._client

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def translate(self, text: str, source: str, target: str) -> TranslationResult:
        """Translate one chunk. Raises :class:`ProviderError` on failure."""
        if not text.strip():
            return TranslationResult(text, self.name)

        key = _cache_key(text, source, target)
        hit = _cache_get(key)
        if hit is not None:
            return TranslationResult(hit, self.name, cached=True)

        if len(text) > self.max_chars:
            raise ProviderError(
                f"Chunk is {len(text)} characters; the provider accepts {self.max_chars}. "
                "This is a bug in the chunker, not in the input.",
                retryable=False,
            )

        params: dict[str, Any] = {
            "q": text,
            "langpair": f"{source}|{target}",
        }
        if settings.mymemory_email:
            # MyMemory raises the daily allowance when you identify yourself.
            params["de"] = settings.mymemory_email

        started = time.perf_counter()
        client = await self._get_client()

        last_error: Exception | None = None
        for attempt in range(settings.provider_max_retries + 1):
            try:
                response = await client.get(settings.mymemory_endpoint, params=params)
            except httpx.TimeoutException as exc:
                last_error = exc
                if attempt < settings.provider_max_retries:
                    await asyncio.sleep(0.4 * (2**attempt))
                    continue
                raise ProviderError(
                    "The translation service did not respond in time.", retryable=True
                ) from exc
            except httpx.HTTPError as exc:
                raise ProviderError(
                    f"Could not reach the translation service: {exc}", retryable=True
                ) from exc

            if response.status_code == 429:
                raise QuotaExceeded(
                    "The translation service is rate limiting us. Try again in a minute.",
                    status=429,
                    retryable=True,
                )
            if response.status_code == 403:
                detail = _safe_detail(response)
                if "QUERY LENGTH" in detail.upper():
                    raise ProviderError(
                        f"The provider rejected a {len(text)}-character chunk: {detail}",
                        status=403,
                    )
                raise QuotaExceeded(
                    f"The translation service refused the request: {detail}",
                    status=403,
                )
            if response.status_code >= 500:
                last_error = ProviderError(
                    f"The translation service returned {response.status_code}.",
                    status=response.status_code,
                    retryable=True,
                )
                if attempt < settings.provider_max_retries:
                    await asyncio.sleep(0.4 * (2**attempt))
                    continue
                raise last_error
            if response.status_code != 200:
                raise ProviderError(
                    f"The translation service returned {response.status_code}.",
                    status=response.status_code,
                )

            payload = _parse(response)
            translated = payload.get("translatedText")
            if not isinstance(translated, str):
                raise ProviderError("The translation service returned an unexpected shape.")

            # MyMemory signals some failures inside a 200 body.
            status = payload.get("responseStatus")
            if isinstance(status, int) and status != 200:
                detail = str(payload.get("responseDetails") or "").strip()
                if "QUOTA" in detail.upper() or "MYMEMORY WARNING" in detail.upper():
                    raise QuotaExceeded(detail or "Daily translation quota reached.", status=status)
                raise ProviderError(detail or f"Provider reported status {status}.", status=status)

            latency = int((time.perf_counter() - started) * 1000)
            _cache_put(key, translated)
            return TranslationResult(translated, self.name, latency_ms=latency)

        raise ProviderError(f"Translation failed after retries: {last_error}", retryable=True)


def _parse(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError as exc:
        raise ProviderError("The translation service returned a non-JSON response.") from exc
    if not isinstance(data, dict):
        raise ProviderError("The translation service returned an unexpected shape.")
    response_data = data.get("responseData")
    if not isinstance(response_data, dict):
        raise ProviderError("The translation service returned no translation data.")
    return response_data


def _safe_detail(response: httpx.Response) -> str:
    """Pull a short human-readable error out of a provider response."""
    try:
        data = response.json()
    except ValueError:
        return response.text[:200] or f"HTTP {response.status_code}"
    if isinstance(data, dict):
        for key in ("responseDetails", "error", "message"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:200]
    return f"HTTP {response.status_code}"


_provider: MyMemoryProvider | None = None


def get_provider() -> MyMemoryProvider:
    """The process-wide provider instance."""
    global _provider
    if _provider is None:
        _provider = MyMemoryProvider()
    return _provider


async def close_provider() -> None:
    global _provider
    if _provider is not None:
        await _provider.aclose()
        _provider = None


__all__ = [
    "MyMemoryProvider",
    "ProviderError",
    "QuotaExceeded",
    "TranslationResult",
    "cache_size",
    "clear_cache",
    "close_provider",
    "get_provider",
]
