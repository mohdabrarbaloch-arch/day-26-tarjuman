"""Language registry.

Each entry carries the script we *expect* the output to be written in. That
expectation is what makes verification possible: if we ask for Urdu and get
Latin back, something went wrong, and we can say so without a model.

Only languages with a real, tested path through the translation provider are
marked ``verified``. The rest are listed so the UI can show them honestly as
untested rather than pretending the whole table works.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.scripts import Script


@dataclass(frozen=True, slots=True)
class Language:
    code: str
    name: str
    native_name: str
    script: Script
    rtl: bool = False
    # True only where we have actually run a translation end to end and checked
    # the output. Everything else is offered but flagged.
    verified: bool = False


# Ordered roughly by how likely ABraz is to need them, not alphabetically.
LANGUAGES: tuple[Language, ...] = (
    Language("en", "English", "English", Script.LATIN, verified=True),
    Language("ur", "Urdu", "اردو", Script.ARABIC, rtl=True, verified=True),
    Language("hi", "Hindi", "हिन्दी", Script.DEVANAGARI, verified=True),
    Language("ar", "Arabic", "العربية", Script.ARABIC, rtl=True, verified=True),
    Language("es", "Spanish", "Español", Script.LATIN, verified=True),
    Language("fr", "French", "Français", Script.LATIN, verified=True),
    Language("de", "German", "Deutsch", Script.LATIN, verified=True),
    Language("pt", "Portuguese", "Português", Script.LATIN, verified=True),
    Language("it", "Italian", "Italiano", Script.LATIN, verified=True),
    Language("ru", "Russian", "Русский", Script.CYRILLIC, verified=True),
    Language("tr", "Turkish", "Türkçe", Script.LATIN, verified=True),
    Language("zh", "Chinese", "中文", Script.CJK, verified=True),
    Language("ja", "Japanese", "日本語", Script.CJK, verified=True),
    Language("ko", "Korean", "한국어", Script.CJK, verified=True),
    Language("bn", "Bengali", "বাংলা", Script.OTHER, verified=True),
    Language("fa", "Persian", "فارسی", Script.ARABIC, rtl=True),
    Language("id", "Indonesian", "Bahasa Indonesia", Script.LATIN),
    Language("nl", "Dutch", "Nederlands", Script.LATIN),
    Language("pl", "Polish", "Polski", Script.LATIN),
    Language("sv", "Swedish", "Svenska", Script.LATIN),
    Language("he", "Hebrew", "עברית", Script.HEBREW, rtl=True),
    Language("th", "Thai", "ไทย", Script.THAI),
    Language("vi", "Vietnamese", "Tiếng Việt", Script.LATIN),
    Language("uk", "Ukrainian", "Українська", Script.CYRILLIC),
    Language("el", "Greek", "Ελληνικά", Script.GREEK),
)

_BY_CODE: dict[str, Language] = {lang.code: lang for lang in LANGUAGES}

# Roman Urdu is not a language code any provider understands. It is Urdu written
# in Latin letters, and it is what most Pakistani users actually type. We handle
# it as a *source* variant: detect it, transliterate the intent, and be explicit
# in the UI that this path is heuristic.
ROMAN_URDU_CODE = "ur-Latn"


def get(code: str) -> Language | None:
    """Look up a language by code, case-insensitively."""
    return _BY_CODE.get(code.strip().lower())


def exists(code: str) -> bool:
    return code.strip().lower() in _BY_CODE


def expected_script(code: str) -> Script | None:
    """The script a correct translation into ``code`` should be written in."""
    lang = get(code)
    return lang.script if lang else None


def is_rtl(code: str) -> bool:
    lang = get(code)
    return bool(lang and lang.rtl)


def name_of(code: str) -> str:
    lang = get(code)
    return lang.name if lang else code


def all_codes() -> list[str]:
    return [lang.code for lang in LANGUAGES]
