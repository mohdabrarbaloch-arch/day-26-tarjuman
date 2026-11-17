"""Writing-system detection.

The whole point of this module is that a translation API will happily return
HTTP 200 with the input echoed back unchanged. Before we can judge whether a
translation actually happened, we need to know what script the text is in.

We deliberately do not use a statistical language identifier. Those need a
model, a download, and they are confidently wrong on short strings -- which is
exactly the input a chat translator gets. Character ranges are boring, exact,
and explainable, which is what this project is about.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from enum import StrEnum


class Script(StrEnum):
    """A writing system, not a language. Urdu and Arabic share one."""

    LATIN = "latin"
    ARABIC = "arabic"
    DEVANAGARI = "devanagari"
    CJK = "cjk"
    CYRILLIC = "cyrillic"
    GREEK = "greek"
    HEBREW = "hebrew"
    THAI = "thai"
    OTHER = "other"
    EMPTY = "empty"


# Unicode blocks, inclusive. Kept explicit rather than clever so the table can
# be read and argued with.
_RANGES: tuple[tuple[int, int, Script], ...] = (
    (0x0041, 0x005A, Script.LATIN),  # A-Z
    (0x0061, 0x007A, Script.LATIN),  # a-z
    (0x00C0, 0x024F, Script.LATIN),  # Latin-1 supplement + extended A/B
    (0x0370, 0x03FF, Script.GREEK),
    (0x0400, 0x04FF, Script.CYRILLIC),
    (0x0590, 0x05FF, Script.HEBREW),
    (0x0600, 0x06FF, Script.ARABIC),  # Arabic block (includes Urdu letters)
    (0x0750, 0x077F, Script.ARABIC),  # Arabic supplement
    (0x08A0, 0x08FF, Script.ARABIC),  # Arabic extended-A
    (0x0900, 0x097F, Script.DEVANAGARI),
    (0x0980, 0x09FF, Script.OTHER),  # Bengali
    (0x0A00, 0x0A7F, Script.OTHER),  # Gurmukhi
    (0x0E00, 0x0E7F, Script.THAI),
    (0x3040, 0x30FF, Script.CJK),  # Hiragana + Katakana
    (0x3400, 0x4DBF, Script.CJK),  # CJK ext A
    (0x4E00, 0x9FFF, Script.CJK),  # CJK unified
    (0xAC00, 0xD7AF, Script.CJK),  # Hangul syllables
    (0xFB50, 0xFDFF, Script.ARABIC),  # Arabic presentation forms A
    (0xFE70, 0xFEFF, Script.ARABIC),  # Arabic presentation forms B
)

# Urdu-specific letters that do not exist in standard Arabic. Their presence is
# strong evidence the text is Urdu rather than Arabic or Persian.
_URDU_MARKERS = frozenset("ٹڈڑںھہےۓکیگچپژۂۃ")


@dataclass(frozen=True, slots=True)
class ScriptProfile:
    """What scripts a string is made of, and in what proportion."""

    script: Script
    counts: dict[str, int]
    letters: int
    urdu_markers: int

    @property
    def is_empty(self) -> bool:
        return self.letters == 0

    @property
    def purity(self) -> float:
        """Share of letters belonging to the dominant script, 0.0-1.0."""
        if self.letters == 0:
            return 0.0
        return self.counts.get(self.script.value, 0) / self.letters

    @property
    def looks_urdu(self) -> bool:
        """Arabic script carrying Urdu-only letters."""
        return self.script is Script.ARABIC and self.urdu_markers > 0


def _classify(ch: str) -> Script | None:
    """Return the script of a single character, or None if it is not a letter."""
    if not ch.isalpha():
        return None
    cp = ord(ch)
    for lo, hi, script in _RANGES:
        if lo <= cp <= hi:
            return script
    # Anything alphabetic we did not enumerate: fall back to Unicode's own name.
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return Script.OTHER
    for script in (Script.LATIN, Script.ARABIC, Script.CYRILLIC, Script.GREEK):
        if script.name in name:
            return script
    return Script.OTHER


def profile(text: str) -> ScriptProfile:
    """Classify every letter in ``text`` and report the dominant script."""
    counts: dict[str, int] = {}
    letters = 0
    urdu_markers = 0

    for ch in text:
        script = _classify(ch)
        if script is None:
            continue
        letters += 1
        counts[script.value] = counts.get(script.value, 0) + 1
        if ch in _URDU_MARKERS:
            urdu_markers += 1

    if letters == 0:
        return ScriptProfile(Script.EMPTY, counts, 0, 0)

    dominant = max(counts.items(), key=lambda kv: kv[1])[0]
    return ScriptProfile(Script(dominant), counts, letters, urdu_markers)


def detect(text: str) -> Script:
    """Convenience wrapper returning just the dominant script."""
    return profile(text).script


def is_rtl(text: str) -> bool:
    """True when the text is predominantly right-to-left."""
    return detect(text) in (Script.ARABIC, Script.HEBREW)


def script_matches(text: str, expected: Script, *, threshold: float = 0.6) -> bool:
    """Does ``text`` read as ``expected``, allowing for loanwords and names?

    A translation into Urdu that leaves "WhatsApp" in Latin is still Urdu. A
    translation that leaves the *entire sentence* in Latin is not. The threshold
    is the line between those two cases.
    """
    p = profile(text)
    if p.is_empty:
        return False
    if p.script is expected:
        return True
    return p.counts.get(expected.value, 0) / p.letters >= threshold
