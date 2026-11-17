"""History routes.

Every query is scoped to the signed-in user. A record belonging to someone else
returns 404, not 403 -- telling a caller "this exists but is not yours" leaks the
existence of other users' data.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from app.db.models import Translation
from app.deps import CurrentUser, DbSession
from app.schemas import FavouriteRequest, HistoryPage, TranslationOut

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("", response_model=HistoryPage, summary="Your translation history")
def list_history(
    user: CurrentUser,
    db: DbSession,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    favourites_only: bool = Query(default=False),
    verdict: str | None = Query(default=None, max_length=16),
) -> HistoryPage:
    conditions = [Translation.user_id == user.id]
    if favourites_only:
        conditions.append(Translation.is_favourite.is_(True))
    if verdict:
        conditions.append(Translation.verdict == verdict.strip().lower())

    total = db.scalar(select(func.count()).select_from(Translation).where(*conditions)) or 0

    rows = db.scalars(
        select(Translation)
        .where(*conditions)
        .order_by(Translation.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    return HistoryPage(
        items=[TranslationOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{translation_id}", response_model=TranslationOut, summary="One saved translation")
def get_translation(translation_id: str, user: CurrentUser, db: DbSession) -> TranslationOut:
    record = db.get(Translation, translation_id)
    if record is None or record.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "No such translation."},
        )
    return TranslationOut.model_validate(record)


@router.patch(
    "/{translation_id}/favourite",
    response_model=TranslationOut,
    summary="Star or unstar a translation",
)
def set_favourite(
    translation_id: str, payload: FavouriteRequest, user: CurrentUser, db: DbSession
) -> TranslationOut:
    record = db.get(Translation, translation_id)
    if record is None or record.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "No such translation."},
        )
    record.is_favourite = payload.is_favourite
    db.commit()
    db.refresh(record)
    return TranslationOut.model_validate(record)


@router.delete(
    "/{translation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a saved translation",
)
def delete_translation(translation_id: str, user: CurrentUser, db: DbSession) -> None:
    record = db.get(Translation, translation_id)
    if record is None or record.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "No such translation."},
        )
    db.delete(record)
    db.commit()
