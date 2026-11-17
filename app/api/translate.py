"""Translation routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.core import languages
from app.core.config import settings
from app.core.ratelimit import make_limiter
from app.core.translator import TranslationError, translate
from app.db.models import Translation
from app.deps import DbSession, OptionalUser
from app.schemas import (
    ChunkOut,
    FindingOut,
    LanguageOut,
    TranslateRequest,
    TranslateResponse,
    VerificationOut,
)

router = APIRouter(prefix="/api", tags=["translate"])

# Translation is the expensive endpoint: every call costs provider quota, and a
# round trip doubles it. The limit is tighter than the global one for that reason.
translate_limiter = make_limiter(
    settings.translate_rate_limit_requests,
    settings.translate_rate_limit_window_seconds,
)


@router.get("/languages", response_model=list[LanguageOut], summary="Supported languages")
def list_languages() -> list[LanguageOut]:
    return [
        LanguageOut(
            code=lang.code,
            name=lang.name,
            native_name=lang.native_name,
            script=lang.script.value,
            rtl=lang.rtl,
            verified=lang.verified,
        )
        for lang in languages.LANGUAGES
    ]


@router.post(
    "/translate",
    response_model=TranslateResponse,
    dependencies=[Depends(translate_limiter)],
    summary="Translate text and verify the result",
)
async def translate_text(
    payload: TranslateRequest,
    db: DbSession,
    user: OptionalUser,
) -> TranslateResponse:
    try:
        outcome = await translate(
            payload.text,
            payload.source_lang,
            payload.target_lang,
            round_trip=payload.round_trip,
        )
    except TranslationError as exc:
        raise HTTPException(
            status_code=exc.status,
            detail={"code": exc.code, "message": exc.message},
        ) from exc

    saved_id: str | None = None
    if payload.save and user is not None:
        record = Translation(
            user_id=user.id,
            source_text=outcome.source_text,
            translated_text=outcome.translated_text,
            source_lang=outcome.source_lang,
            target_lang=outcome.target_lang,
            verdict=outcome.verification.verdict.value,
            confidence=outcome.verification.confidence,
            provider=outcome.provider,
            char_count=len(outcome.source_text),
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        saved_id = record.id

    v = outcome.verification
    return TranslateResponse(
        source_text=outcome.source_text,
        translated_text=outcome.translated_text,
        source_lang=outcome.source_lang,
        target_lang=outcome.target_lang,
        detected_source=outcome.detected_source,
        source_script=outcome.source_script,
        target_rtl=outcome.target_rtl,
        roman_urdu_source=outcome.roman_urdu_source,
        provider=outcome.provider,
        cached=outcome.cached,
        latency_ms=outcome.latency_ms,
        summary=outcome.summary,
        verification=VerificationOut(
            verdict=v.verdict.value,
            confidence=v.confidence,
            findings=[
                FindingOut(axis=f.axis, severity=f.severity.value, score=f.score, reason=f.reason)
                for f in v.findings
            ],
            round_trip=v.round_trip,
        ),
        chunks=[
            ChunkOut(
                source=c.source,
                target=c.target,
                verification=VerificationOut(
                    verdict=c.verification.verdict.value,
                    confidence=c.verification.confidence,
                    findings=[
                        FindingOut(
                            axis=f.axis,
                            severity=f.severity.value,
                            score=f.score,
                            reason=f.reason,
                        )
                        for f in c.verification.findings
                    ],
                    round_trip=c.verification.round_trip,
                ),
            )
            for c in outcome.chunks
        ],
        saved_id=saved_id,
    )


@router.get("/stats", summary="Provider and cache status")
def stats() -> dict[str, object]:
    from app.core.provider import cache_size

    return {
        "provider": "mymemory",
        "cache_entries": cache_size(),
        "max_input_chars": settings.max_input_chars,
        "round_trip_enabled": settings.enable_round_trip,
        "languages": len(languages.LANGUAGES),
    }


__all__ = ["router", "translate_limiter"]
