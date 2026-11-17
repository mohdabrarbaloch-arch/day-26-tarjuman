"""Database models.

SQLite by default so the app runs with no setup; PostgreSQL via
``DATABASE_URL`` for anything real. The schema is deliberately small -- users,
their translation history, and saved conversation sessions -- because the
interesting work in this project is in the verification layer, not the tables.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now(), nullable=False
    )

    translations: Mapped[list[Translation]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<User {self.email}>"


class Translation(Base):
    """One saved translation, with the verdict it earned at the time.

    The verdict is stored rather than recomputed because the verification rules
    will change over time, and a user looking at their history should see what
    the app told them then, not what it would say now.
    """

    __tablename__ = "translations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    translated_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_lang: Mapped[str] = mapped_column(String(16), nullable=False)
    target_lang: Mapped[str] = mapped_column(String(16), nullable=False)
    verdict: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="mymemory")
    char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_favourite: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="translations")

    __table_args__ = (
        Index("ix_translations_user_created", "user_id", "created_at"),
        Index("ix_translations_user_favourite", "user_id", "is_favourite"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Translation {self.source_lang}->{self.target_lang} {self.verdict}>"


class ConversationSession(Base):
    """A two-way conversation, for conversation mode.

    Each turn is stored as a row so the transcript can be replayed and exported
    without re-translating anything.
    """

    __tablename__ = "conversation_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(120), nullable=False, default="Conversation")
    lang_a: Mapped[str] = mapped_column(String(16), nullable=False, default="en")
    lang_b: Mapped[str] = mapped_column(String(16), nullable=False, default="ur")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now(), nullable=False
    )

    turns: Mapped[list[ConversationTurn]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ConversationTurn.created_at",
        lazy="selectin",
    )


class ConversationTurn(Base):
    __tablename__ = "conversation_turns"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("conversation_sessions.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    speaker: Mapped[str] = mapped_column(String(1), nullable=False)  # "a" or "b"
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    translated_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_lang: Mapped[str] = mapped_column(String(16), nullable=False)
    target_lang: Mapped[str] = mapped_column(String(16), nullable=False)
    verdict: Mapped[str] = mapped_column(String(16), nullable=False, default="verified")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now(), nullable=False
    )

    session: Mapped[ConversationSession] = relationship(back_populates="turns")


__all__ = [
    "Base",
    "ConversationSession",
    "ConversationTurn",
    "Translation",
    "User",
]
