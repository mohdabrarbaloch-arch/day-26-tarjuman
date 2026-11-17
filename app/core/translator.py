"""The translation service.

This is where the pieces meet: detect the source language, chunk the text to fit
the provider, translate each chunk, translate back for the round-trip check, and
hand everything to the verifier.

Two design decisions worth stating.

**Chunks are verified individually, then the whole is verified again.** A single
bad chunk in a ten-chunk document is invisible in an aggregate score, so each
chunk carries its own verdict and the response reports the worst one. The user
can see exactly which paragraph failed.

**Round-trip is skipped for long text.** It doubles the provider cost, and on a
5000-character document that is 26 extra calls against a free tier. Above
``round_trip_max_chars`` we skip it and the verifier reports the axis as
skipped rather than passed -- an honest gap, not a silent one.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from app.core import languages, roman_urdu
from app.core.chunker import Chunk, chunk
from app.core.config import settings
from app.core.provider import ProviderError, QuotaExceeded, get_provider
from app.core.scripts import Script, detect, is_rtl
from app.core.verify import Verdict, Verification, summarise, verify


class TranslationError(Exception):
    """Translation could not be completed. Carries a user-facing message."""

    def __init__(self, message: str, *, status: int = 502, code: str = "translation_failed"):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


@dataclass(slots=True)
class ChunkResult:
    """One translated chunk and its own verdict."""

    source: str
    target: str
    verification: Verification

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "target": self.target,
            "verification": self.verification.to_dict(),
        }


@dataclass(slots=True)
class TranslationOutcome:
    """The full result of translating a piece of text."""

    source_text: str
    translated_text: str
    source_lang: str
    target_lang: str
    detected_source: str
    source_script: str
    target_rtl: bool
    verification: Verification
    chunks: list[ChunkResult] = field(default_factory=list)
    provider: str = "mymemory"
    cached: bool = False
    latency_ms: int = 0
    roman_urdu_source: bool = False

    @property
    def summary(self) -> str:
        return summarise(self.verification)

    def to_dict(self) -> dict[str, object]:
        return {
            "source_text": self.source_text,
            "translated_text": self.translated_text,
            "source_lang": self.source_lang,
            "target_lang": self.target_lang,
            "detected_source": self.detected_source,
            "source_script": self.source_script,
            "target_rtl": self.target_rtl,
            "roman_urdu_source": self.roman_urdu_source,
            "provider": self.provider,
            "cached": self.cached,
            "latency_ms": self.latency_ms,
            "summary": self.summary,
            "verification": self.verification.to_dict(),
            "chunks": [c.to_dict() for c in self.chunks],
        }


# --- source language resolution -------------------------------------------


def resolve_source(text: str, declared: str) -> tuple[str, bool]:
    """Work out what language the text is really in.

    Returns ``(language_code, is_roman_urdu)``.

    The interesting case is Roman Urdu. A user types "Mujhe kal jana hai" and
    picks Urdu as the source, because that is what the sentence is. But the
    provider has no code for Urdu-in-Latin-letters, and telling it "ur" makes it
    treat Latin text as Urdu script -- which is how you get a respelling back
    instead of a translation.

    So when the declared source is Urdu but the text is Latin script and reads as
    Roman Urdu, we keep the declared language for display and flag it, so the
    verifier can run the transliteration check.
    """
    declared = declared.strip().lower()
    script = detect(text)

    if declared == "ur" and script is Script.LATIN:
        if roman_urdu.is_roman_urdu(text):
            return "ur", True
        # Declared Urdu, Latin script, but not Roman Urdu: probably English.
        return "en", False

    if declared == "auto":
        if script is Script.LATIN:
            return ("ur" if roman_urdu.is_roman_urdu(text) else "en"), roman_urdu.is_roman_urdu(
                text
            )
        if script is Script.ARABIC:
            return "ur", False
        if script is Script.DEVANAGARI:
            return "hi", False
        if script is Script.CYRILLIC:
            return "ru", False
        if script is Script.CJK:
            return "zh", False
        return "en", False

    return declared, False


# --- the service -----------------------------------------------------------


async def _translate_chunks(
    chunks: list[Chunk], source: str, target: str
) -> tuple[list[str], bool, int]:
    """Translate every chunk. Returns (texts, any_cached, total_latency)."""
    provider = get_provider()
    texts: list[str] = []
    any_cached = False
    latency = 0

    for c in chunks:
        result = await provider.translate(c.text, source, target)
        texts.append(result.text)
        any_cached = any_cached or result.cached
        latency += result.latency_ms
    return texts, any_cached, latency


async def translate(
    text: str,
    source_lang: str,
    target_lang: str,
    *,
    round_trip: bool | None = None,
) -> TranslationOutcome:
    """Translate ``text`` and verify the result.

    Raises :class:`TranslationError` with a user-facing message on failure.
    """
    text = text.strip()
    if not text:
        raise TranslationError("There is nothing to translate.", status=422, code="empty_input")
    if len(text) > settings.max_input_chars:
        raise TranslationError(
            f"That is {len(text)} characters. The limit is {settings.max_input_chars}.",
            status=422,
            code="too_long",
        )

    target_lang = target_lang.strip().lower()
    if not languages.exists(target_lang):
        raise TranslationError(
            f"'{target_lang}' is not a language this app knows about.",
            status=422,
            code="unknown_target",
        )

    resolved_source, is_roman = resolve_source(text, source_lang)
    if not languages.exists(resolved_source):
        raise TranslationError(
            f"'{resolved_source}' is not a language this app knows about.",
            status=422,
            code="unknown_source",
        )

    if resolved_source == target_lang and not is_roman:
        raise TranslationError(
            "The source and target languages are the same.",
            status=422,
            code="same_language",
        )

    # Roman Urdu is Urdu written in Latin letters. The provider needs a real
    # language code, and "ur" is the honest one -- the text *is* Urdu. The
    # transliteration check is what catches the provider failing to handle it.
    provider_source = resolved_source

    pieces = chunk(text)
    if not pieces:
        raise TranslationError("There is nothing to translate.", status=422, code="empty_input")

    try:
        translated_parts, any_cached, latency = await _translate_chunks(
            pieces, provider_source, target_lang
        )
    except QuotaExceeded as exc:
        raise TranslationError(
            str(exc) or "The translation service's daily allowance is used up.",
            status=429,
            code="quota_exceeded",
        ) from exc
    except ProviderError as exc:
        raise TranslationError(
            str(exc) or "The translation service is unavailable right now.",
            status=503,
            code="provider_unavailable",
        ) from exc

    translated_text = "".join(
        part + piece.separator for part, piece in zip(translated_parts, pieces, strict=True)
    )

    # --- round trip ---
    do_round_trip = settings.enable_round_trip if round_trip is None else round_trip
    back_text: str | None = None
    if do_round_trip and len(text) <= settings.round_trip_max_chars:
        try:
            back_parts, _, back_latency = await _translate_chunks(
                chunk(translated_text), target_lang, provider_source
            )
            back_text = "".join(
                part + piece.separator
                for part, piece in zip(back_parts, chunk(translated_text), strict=True)
            )
            latency += back_latency
        except (ProviderError, QuotaExceeded):
            # A failed round trip is not a failed translation. The verifier
            # reports the axis as skipped, which is the honest outcome.
            back_text = None

    # --- per-chunk verification ---
    chunk_results: list[ChunkResult] = []
    for piece, part in zip(pieces, translated_parts, strict=True):
        if not piece.text.strip():
            continue
        v = verify(piece.text, part, provider_source, target_lang, round_trip=None)
        chunk_results.append(ChunkResult(piece.text, part, v))

    # --- whole-document verification ---
    overall = verify(
        text,
        translated_text,
        provider_source,
        target_lang,
        round_trip=back_text,
    )

    # If any single chunk failed, the document failed. An aggregate score hides
    # one bad paragraph in ten, and that paragraph is the one the user needs to
    # know about.
    worst = _worst_chunk_verdict(chunk_results)
    if worst is Verdict.FAILED and overall.verdict is not Verdict.FAILED:
        overall.verdict = Verdict.FAILED
        overall.confidence = min(overall.confidence, 0.4)

    return TranslationOutcome(
        source_text=text,
        translated_text=translated_text,
        source_lang=resolved_source,
        target_lang=target_lang,
        detected_source=resolved_source,
        source_script=detect(text).value,
        target_rtl=is_rtl(translated_text),
        verification=overall,
        chunks=chunk_results,
        cached=any_cached,
        latency_ms=latency,
        roman_urdu_source=is_roman,
    )


_VERDICT_ORDER = {
    Verdict.VERIFIED: 0,
    Verdict.LIKELY: 1,
    Verdict.UNCERTAIN: 2,
    Verdict.FAILED: 3,
}


def _worst_chunk_verdict(chunks: list[ChunkResult]) -> Verdict:
    if not chunks:
        return Verdict.VERIFIED
    return max((c.verification.verdict for c in chunks), key=lambda v: _VERDICT_ORDER[v])


async def translate_many(
    items: list[tuple[str, str, str]],
) -> list[TranslationOutcome | TranslationError]:
    """Translate several texts concurrently.

    Used by conversation mode, where two speakers' turns are translated at once.
    Errors are returned in place rather than raised, so one bad turn does not
    lose the rest of the conversation.
    """

    async def one(item: tuple[str, str, str]) -> TranslationOutcome | TranslationError:
        text, src, tgt = item
        try:
            return await translate(text, src, tgt)
        except TranslationError as exc:
            return exc

    return list(await asyncio.gather(*(one(i) for i in items)))


__all__ = [
    "ChunkResult",
    "TranslationError",
    "TranslationOutcome",
    "resolve_source",
    "translate",
    "translate_many",
]
