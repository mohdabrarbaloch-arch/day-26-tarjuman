"""Conversation mode.

Two people, two languages, one screen. Speaker A types in their language, the
other side sees it translated; speaker B replies and the same happens in reverse.

The design decision that matters: each turn is translated and verified
independently, and the verdict is stored with the turn. In a live conversation
you cannot stop to check a translation, so the app has to tell you which turns
to trust -- a failed turn is marked in the transcript rather than silently
passed through.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.core.config import settings
from app.core.ratelimit import make_limiter
from app.core.translator import TranslationError, translate
from app.db.models import ConversationSession, ConversationTurn
from app.deps import CurrentUser, DbSession
from app.schemas import ConversationCreate, ConversationOut, TurnOut, TurnRequest

router = APIRouter(prefix="/api/conversations", tags=["conversation"])

turn_limiter = make_limiter(
    settings.translate_rate_limit_requests,
    settings.translate_rate_limit_window_seconds,
)


def _load(session_id: str, user_id: str, db: DbSession) -> ConversationSession:
    session = db.get(ConversationSession, session_id)
    if session is None or session.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "No such conversation."},
        )
    return session


@router.post(
    "",
    response_model=ConversationOut,
    status_code=status.HTTP_201_CREATED,
    summary="Start a conversation",
)
def create_conversation(
    payload: ConversationCreate, user: CurrentUser, db: DbSession
) -> ConversationOut:
    if payload.lang_a == payload.lang_b:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "same_language",
                "message": "The two speakers need different languages.",
            },
        )
    session = ConversationSession(
        user_id=user.id,
        title=payload.title.strip() or "Conversation",
        lang_a=payload.lang_a,
        lang_b=payload.lang_b,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return ConversationOut.model_validate(session)


@router.get("", response_model=list[ConversationOut], summary="Your conversations")
def list_conversations(user: CurrentUser, db: DbSession) -> list[ConversationOut]:
    rows = db.scalars(
        select(ConversationSession)
        .where(ConversationSession.user_id == user.id)
        .order_by(ConversationSession.created_at.desc())
        .limit(50)
    ).all()
    return [ConversationOut.model_validate(r) for r in rows]


@router.get("/{session_id}", response_model=ConversationOut, summary="One conversation")
def get_conversation(session_id: str, user: CurrentUser, db: DbSession) -> ConversationOut:
    return ConversationOut.model_validate(_load(session_id, user.id, db))


@router.post(
    "/{session_id}/turns",
    response_model=TurnOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(turn_limiter)],
    summary="Add a turn and get it translated",
)
async def add_turn(
    session_id: str, payload: TurnRequest, user: CurrentUser, db: DbSession
) -> TurnOut:
    session = _load(session_id, user.id, db)

    # Speaker A speaks lang_a and is translated into lang_b, and vice versa.
    if payload.speaker == "a":
        source_lang, target_lang = session.lang_a, session.lang_b
    else:
        source_lang, target_lang = session.lang_b, session.lang_a

    try:
        outcome = await translate(payload.text, source_lang, target_lang)
    except TranslationError as exc:
        raise HTTPException(
            status_code=exc.status,
            detail={"code": exc.code, "message": exc.message},
        ) from exc

    turn = ConversationTurn(
        session_id=session.id,
        speaker=payload.speaker,
        original_text=payload.text,
        translated_text=outcome.translated_text,
        source_lang=outcome.source_lang,
        target_lang=outcome.target_lang,
        verdict=outcome.verification.verdict.value,
    )
    db.add(turn)
    db.commit()
    db.refresh(turn)
    return TurnOut.model_validate(turn)


@router.delete(
    "/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a conversation",
)
def delete_conversation(session_id: str, user: CurrentUser, db: DbSession) -> None:
    session = _load(session_id, user.id, db)
    db.delete(session)
    db.commit()
