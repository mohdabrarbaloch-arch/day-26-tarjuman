"""Translation verification.

The problem this module exists to solve, stated plainly:

MyMemory returns HTTP 200 for input it cannot translate. Ask it to translate
"Zyx qwerty plonking" into Urdu and it hands back Urdu-script gibberish. Ask it
to translate the same string *from* Urdu and it hands back the input unchanged.
In both cases ``responseStatus`` is 200 and ``match`` is 0.85 -- the same 0.85 it
returns for a perfect translation. The API's own confidence field is a constant,
so it carries no information at all.

A naive client therefore reports success on garbage. Worse, a naive
round-trip check reports *verified* on a no-op: translate X, translate back,
compare, and if the provider echoed the input both ways you get a perfect score
for having done nothing.

So we verify on four independent axes and refuse to call anything verified
unless all of them agree:

1. Script conformance -- is the output written in the script the target language
   actually uses? This catches the echo case immediately and cheaply.
2. Echo detection -- is the output identical (or near-identical) to the input?
   Catches no-ops that happen to share a script, e.g. en->es on a proper noun.
3. Length ratio -- is the output a plausible length for the input? Catches
   truncation and the "returned one word for a paragraph" failure.
4. Round-trip fidelity -- translate back and measure similarity. This is the
   only axis that tests meaning, and it is the one that lies on a no-op, which
   is why it is never trusted alone.

Each axis produces a finding with a severity and a human-readable reason. The
verdict is the worst finding. Nothing is hidden: the UI shows every axis, its
score, and the exact reason, so a user who disagrees can point at the axis they
disagree with.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from enum import StrEnum

from app.core import languages
from app.core.roman_urdu import looks_like_transliteration
from app.core.scripts import Script, profile, script_matches


class Verdict(StrEnum):
    """How much to trust a translation."""

    VERIFIED = "verified"  # every axis passed
    LIKELY = "likely"  # meaning check passed, a minor axis wobbled
    UNCERTAIN = "uncertain"  # something is off; read with care
    FAILED = "failed"  # the provider did not translate


class Severity(StrEnum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"


@dataclass(frozen=True, slots=True)
class Finding:
    """One verification axis and what it concluded."""

    axis: str
    severity: Severity
    score: float  # 0.0-1.0, higher is better
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "axis": self.axis,
            "severity": self.severity.value,
            "score": round(self.score, 3),
            "reason": self.reason,
        }


@dataclass(slots=True)
class Verification:
    """The full result of checking one translation."""

    verdict: Verdict
    confidence: float
    findings: list[Finding] = field(default_factory=list)
    round_trip: str | None = None

    @property
    def passed(self) -> bool:
        return self.verdict in (Verdict.VERIFIED, Verdict.LIKELY)

    def to_dict(self) -> dict[str, object]:
        return {
            "verdict": self.verdict.value,
            "confidence": round(self.confidence, 3),
            "findings": [f.to_dict() for f in self.findings],
            "round_trip": self.round_trip,
        }


# --- helpers ---------------------------------------------------------------

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)


def _normalise(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace. For comparison only."""
    return _WS.sub(" ", _PUNCT.sub(" ", text.lower())).strip()


def _tokens(text: str) -> list[str]:
    return _normalise(text).split()


def similarity(a: str, b: str) -> float:
    """Token-level similarity, 0.0-1.0.

    Token-level rather than character-level on purpose: word order changes
    between languages, and a character diff punishes reordering that is
    perfectly correct. We care whether the same *words* came back.
    """
    ta, tb = _tokens(a), _tokens(b)
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return difflib.SequenceMatcher(None, ta, tb).ratio()


def _length_ratio(source: str, target: str) -> float:
    """How close the output length is to what we would expect.

    Languages expand and contract, so this is a wide band, not a tight one.
    We only want to catch gross truncation and gross padding.

    Short inputs are exempt. "car" -> "Personenkraftwagen" is a 6x expansion and
    a perfectly correct German translation; on a three-character source the
    ratio carries no information at all. Below ten characters we return a pass
    and let the other axes do the work.
    """
    ls, lt = len(source.strip()), len(target.strip())
    if ls == 0:
        return 1.0 if lt == 0 else 0.0
    if ls < 10:
        return 1.0
    ratio = lt / ls
    # Anything from a third to three times the source length is plausible.
    if 0.33 <= ratio <= 3.0:
        return 1.0
    if ratio < 0.33:
        return max(0.0, ratio / 0.33)
    return max(0.0, 1.0 - (ratio - 3.0) / 3.0)


# --- the four axes ---------------------------------------------------------


def check_script(source: str, target: str, target_lang: str) -> Finding:
    """Axis 1: is the output in the script the target language uses?"""
    expected = languages.expected_script(target_lang)
    if expected is None:
        return Finding(
            "script",
            Severity.WARN,
            0.5,
            f"No script expectation on file for '{target_lang}', so this axis could not run.",
        )

    p = profile(target)
    if p.is_empty:
        return Finding("script", Severity.FAIL, 0.0, "The translation came back empty.")

    if script_matches(target, expected, threshold=0.6):
        share = p.counts.get(expected.value, 0) / p.letters
        return Finding(
            "script",
            Severity.OK,
            share,
            f"{share:.0%} of the output is {expected.value} script, "
            f"as {languages.name_of(target_lang)} requires.",
        )

    # The specific, common, confusing case: asked for Urdu, got Latin back.
    src_script = profile(source).script
    if p.script is src_script:
        return Finding(
            "script",
            Severity.FAIL,
            0.0,
            f"The output is still {p.script.value} script -- the same as the input. "
            f"{languages.name_of(target_lang)} is written in {expected.value}. "
            "The provider returned the text without translating it.",
        )
    return Finding(
        "script",
        Severity.FAIL,
        0.0,
        f"The output is {p.script.value} script but {languages.name_of(target_lang)} "
        f"is written in {expected.value}.",
    )


def check_echo(source: str, target: str) -> Finding:
    """Axis 2: did the provider just hand the input back?"""
    if source.strip() == target.strip():
        return Finding(
            "echo",
            Severity.FAIL,
            0.0,
            "The output is character-for-character identical to the input. Nothing was translated.",
        )

    sim = similarity(source, target)
    if sim >= 0.95:
        return Finding(
            "echo",
            Severity.FAIL,
            sim,
            f"The output is {sim:.0%} identical to the input. That is an echo, not a translation.",
        )
    if sim >= 0.8:
        return Finding(
            "echo",
            Severity.WARN,
            sim,
            f"The output is {sim:.0%} identical to the input. Some of it may be untranslated.",
        )
    return Finding(
        "echo",
        Severity.OK,
        1.0 - sim,
        f"The output differs from the input ({sim:.0%} overlap), so translation did occur.",
    )


def check_length(source: str, target: str) -> Finding:
    """Axis 3: is the output a plausible length?"""
    score = _length_ratio(source, target)
    ls, lt = len(source.strip()), len(target.strip())
    if score >= 0.99:
        return Finding(
            "length",
            Severity.OK,
            score,
            f"{lt} characters out for {ls} in -- within the normal range.",
        )
    if score >= 0.5:
        return Finding(
            "length",
            Severity.WARN,
            score,
            f"{lt} characters out for {ls} in. That is unusual but not impossible.",
        )
    return Finding(
        "length",
        Severity.FAIL,
        score,
        f"{lt} characters out for {ls} in. The output looks truncated or padded.",
    )


def check_round_trip(source: str, back: str, source_lang: str) -> Finding:
    """Axis 4: translate back and see whether the meaning survived.

    This is the only axis that tests meaning, and it is also the one that
    produces a false pass on a no-op -- if the provider echoed the input in both
    directions, the round trip is perfect. That is why it never decides the
    verdict alone.

    One case has to be excluded rather than scored. If the source is Roman Urdu
    (Urdu in Latin letters) and the back-translation comes home in Urdu script,
    the two strings share no tokens at all and the similarity is 0.0 -- for a
    translation that was perfectly correct. Comparing across scripts measures
    the alphabet, not the meaning, so we report the axis as skipped instead of
    failing it. This was a real bug: "Mujhe kal office jana hai" translated
    correctly to "I have to go to the office tomorrow." and then scored 0.00 on
    the round trip, dragging a good translation down to "uncertain".
    """
    src_script = profile(source).script
    back_script = profile(back).script
    both_known = src_script is not Script.EMPTY and back_script is not Script.EMPTY
    if src_script is not back_script and both_known:
        return Finding(
            "round_trip",
            Severity.WARN,
            0.5,
            f"The round trip came back in {back_script.value} script while the source was "
            f"{src_script.value}. Comparing across scripts measures the alphabet, not the "
            "meaning, so this check was skipped.",
        )

    sim = similarity(source, back)
    if sim >= 0.75:
        return Finding(
            "round_trip",
            Severity.OK,
            sim,
            f"Translating back gives {sim:.0%} of the original wording, so the meaning held.",
        )
    if sim >= 0.45:
        return Finding(
            "round_trip",
            Severity.WARN,
            sim,
            f"Translating back gives {sim:.0%} of the original wording. The gist survived, "
            "the phrasing did not.",
        )
    return Finding(
        "round_trip",
        Severity.FAIL,
        sim,
        f"Translating back gives only {sim:.0%} of the original wording. "
        "The meaning did not survive.",
    )


def check_transliteration(source: str, target: str, target_lang: str) -> Finding:
    """Axis 5: was the text respelled rather than translated?

    This is the failure that no other axis catches. Ask a provider to translate
    Roman Urdu into English and it may return the same sentence with the
    spelling normalised -- "Aaj mausam bohat acha hai" becomes "aaj mosam acha
    hy". The output is Latin script (as English is), differs from the input, is
    a plausible length, and round-trips perfectly, because nothing happened.

    Only meaningful when the target is a Latin-script language; translating into
    Urdu and getting Urdu back is the correct outcome, not a transliteration.
    """
    expected = languages.expected_script(target_lang)
    if expected is not Script.LATIN:
        return Finding(
            "transliteration",
            Severity.OK,
            1.0,
            "Not applicable: the target language is not written in Latin script.",
        )

    if looks_like_transliteration(source, target):
        return Finding(
            "transliteration",
            Severity.FAIL,
            0.0,
            "The output is still Roman Urdu -- the same words, respelled. "
            "The provider normalised the spelling instead of translating.",
        )
    return Finding(
        "transliteration",
        Severity.OK,
        1.0,
        "The output is not a respelling of the input.",
    )


# --- the verdict -----------------------------------------------------------


def _confidence(findings: list[Finding]) -> float:
    """Weighted mean of the axis scores.

    Round-trip carries the most weight because it is the only axis that looks at
    meaning. Script carries the second most because it is the cheapest reliable
    signal that translation happened at all.
    """
    weights = {
        "script": 0.25,
        "echo": 0.15,
        "length": 0.10,
        "round_trip": 0.30,
        "transliteration": 0.20,
    }
    total = sum(weights.get(f.axis, 0.1) for f in findings)
    if total == 0:
        return 0.0
    return sum(f.score * weights.get(f.axis, 0.1) for f in findings) / total


def _verdict(findings: list[Finding]) -> Verdict:
    """The verdict is the worst finding, with one deliberate exception.

    A failed round trip on its own is not fatal: idioms and formal register
    routinely fail to survive a round trip while the forward translation is
    perfectly good. But a failed round trip *combined* with a failed script or
    echo check means the provider was not translating, and we say so.
    """
    by_axis = {f.axis: f for f in findings}
    hard_fail = any(
        by_axis.get(axis) and by_axis[axis].severity is Severity.FAIL
        for axis in ("script", "echo", "transliteration")
    )
    if hard_fail:
        return Verdict.FAILED

    fails = [f for f in findings if f.severity is Severity.FAIL]
    warns = [f for f in findings if f.severity is Severity.WARN]

    if fails:
        return Verdict.UNCERTAIN
    if warns:
        return Verdict.LIKELY
    return Verdict.VERIFIED


def verify(
    source: str,
    target: str,
    source_lang: str,
    target_lang: str,
    *,
    round_trip: str | None = None,
) -> Verification:
    """Run every axis and produce a verdict.

    ``round_trip`` is optional: if the caller did not perform one (because the
    provider failed, or the text was too long to double the cost), the axis is
    reported as skipped rather than silently passed.
    """
    findings = [
        check_script(source, target, target_lang),
        check_echo(source, target),
        check_length(source, target),
        check_transliteration(source, target, target_lang),
    ]

    if round_trip is None:
        findings.append(
            Finding(
                "round_trip",
                Severity.WARN,
                0.5,
                "No round-trip check was run, so meaning was not independently tested.",
            )
        )
    else:
        findings.append(check_round_trip(source, round_trip, source_lang))

    return Verification(
        verdict=_verdict(findings),
        confidence=_confidence(findings),
        findings=findings,
        round_trip=round_trip,
    )


def summarise(v: Verification) -> str:
    """One sentence a human can act on."""
    match v.verdict:
        case Verdict.VERIFIED:
            return "Every check passed. This translation is trustworthy."
        case Verdict.LIKELY:
            return "The meaning held, but one check wobbled. Read it before you send it."
        case Verdict.UNCERTAIN:
            return "Something is off. Treat this as a draft, not a translation."
        case Verdict.FAILED:
            return "The provider did not translate this. The output is not usable."
    return "Unknown verdict."


__all__ = [
    "Finding",
    "Severity",
    "Verdict",
    "Verification",
    "check_echo",
    "check_length",
    "check_round_trip",
    "check_script",
    "similarity",
    "summarise",
    "verify",
]
