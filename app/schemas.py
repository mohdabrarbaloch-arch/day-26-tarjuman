"""Request and response schemas.

Validation lives here so the routes stay thin. Every field that reaches the
provider is bounded: length, language code, and character set. An unbounded
string field is how you get a 10MB request into a 500-character API.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core import languages
from app.core.config import settings

# --- auth ---


class RegisterRequest(BaseModel):
    email: EmailStr
    password: Annotated[str, Field(min_length=8, max_length=128)]
    display_name: Annotated[str, Field(default="", max_length=80)]

    @field_validator("password")
    @classmethod
    def _password_strength(cls, value: str) -> str:
        if value.isdigit():
            raise ValueError("Password cannot be all digits.")
        if len(set(value)) < 4:
            raise ValueError("Password is too repetitive.")
        return value

    @field_validator("display_name")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        return value.strip()


class LoginRequest(BaseModel):
    email: EmailStr
    password: Annotated[str, Field(min_length=1, max_length=128)]


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    display_name: str
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: UserOut


# --- translation ---


class TranslateRequest(BaseModel):
    text: Annotated[str, Field(min_length=1, max_length=settings.max_input_chars)]
    source_lang: Annotated[str, Field(default="auto", max_length=16)]
    target_lang: Annotated[str, Field(min_length=2, max_length=16)]
    round_trip: bool | None = None
    save: bool = False

    @field_validator("text")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Text cannot be blank.")
        return value

    @field_validator("source_lang", "target_lang")
    @classmethod
    def _known_language(cls, value: str) -> str:
        code = value.strip().lower()
        if code == "auto":
            return code
        if not languages.exists(code):
            raise ValueError(f"'{value}' is not a supported language code.")
        return code


class FindingOut(BaseModel):
    axis: str
    severity: str
    score: float
    reason: str


class VerificationOut(BaseModel):
    verdict: str
    confidence: float
    findings: list[FindingOut]
    round_trip: str | None = None


class ChunkOut(BaseModel):
    source: str
    target: str
    verification: VerificationOut


class TranslateResponse(BaseModel):
    source_text: str
    translated_text: str
    source_lang: str
    target_lang: str
    detected_source: str
    source_script: str
    target_rtl: bool
    roman_urdu_source: bool
    provider: str
    cached: bool
    latency_ms: int
    summary: str
    verification: VerificationOut
    chunks: list[ChunkOut]
    saved_id: str | None = None


# --- history ---


class TranslationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_text: str
    translated_text: str
    source_lang: str
    target_lang: str
    verdict: str
    confidence: float
    provider: str
    char_count: int
    is_favourite: bool
    created_at: datetime


class HistoryPage(BaseModel):
    items: list[TranslationOut]
    total: int
    limit: int
    offset: int


class FavouriteRequest(BaseModel):
    is_favourite: bool


# --- conversation ---


class ConversationCreate(BaseModel):
    title: Annotated[str, Field(default="Conversation", max_length=120)]
    lang_a: Annotated[str, Field(default="en", max_length=16)]
    lang_b: Annotated[str, Field(default="ur", max_length=16)]

    @field_validator("lang_a", "lang_b")
    @classmethod
    def _known(cls, value: str) -> str:
        code = value.strip().lower()
        if not languages.exists(code):
            raise ValueError(f"'{value}' is not a supported language code.")
        return code


class TurnRequest(BaseModel):
    speaker: Literal["a", "b"]
    text: Annotated[str, Field(min_length=1, max_length=settings.max_input_chars)]


class TurnOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    speaker: str
    original_text: str
    translated_text: str
    source_lang: str
    target_lang: str
    verdict: str
    created_at: datetime


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    lang_a: str
    lang_b: str
    created_at: datetime
    turns: list[TurnOut] = []


# --- misc ---


class LanguageOut(BaseModel):
    code: str
    name: str
    native_name: str
    script: str
    rtl: bool
    verified: bool


class HealthOut(BaseModel):
    status: str
    version: str
    environment: str
    provider: str
    languages: int


class ErrorOut(BaseModel):
    code: str
    message: str


__all__ = [
    "ChunkOut",
    "ConversationCreate",
    "ConversationOut",
    "ErrorOut",
    "FavouriteRequest",
    "FindingOut",
    "HealthOut",
    "HistoryPage",
    "LanguageOut",
    "LoginRequest",
    "RegisterRequest",
    "TokenResponse",
    "TranslateRequest",
    "TranslateResponse",
    "TranslationOut",
    "TurnOut",
    "TurnRequest",
    "UserOut",
    "VerificationOut",
]
