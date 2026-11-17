"""Tests for the verification engine.

These are the tests that matter most. Each one encodes a real failure observed
against the live provider, so a regression here means the app has gone back to
reporting success on garbage.
"""

from __future__ import annotations

from app.core.verify import (
    Severity,
    Verdict,
    check_echo,
    check_length,
    check_round_trip,
    check_script,
    check_transliteration,
    similarity,
    summarise,
    verify,
)

URDU_INVOICE = "براہ کرم جمعہ تک انوائس بھیج دیں"


class TestSimilarity:
    def test_identical_is_one(self) -> None:
        assert similarity("hello world", "hello world") == 1.0

    def test_completely_different_is_zero(self) -> None:
        assert similarity("hello", "xyz") == 0.0

    def test_both_empty_is_one(self) -> None:
        assert similarity("", "") == 1.0

    def test_one_empty_is_zero(self) -> None:
        assert similarity("hello", "") == 0.0

    def test_punctuation_ignored(self) -> None:
        assert similarity("Hello, world!", "hello world") == 1.0

    def test_case_ignored(self) -> None:
        assert similarity("HELLO", "hello") == 1.0

    def test_partial_overlap(self) -> None:
        score = similarity("the cat sat", "the dog sat")
        assert 0.5 < score < 1.0


class TestScriptAxis:
    def test_correct_script_passes(self) -> None:
        f = check_script("Please send it", URDU_INVOICE, "ur")
        assert f.severity is Severity.OK

    def test_echoed_latin_fails_urdu_target(self) -> None:
        f = check_script("Please send it", "Please send it", "ur")
        assert f.severity is Severity.FAIL
        assert "without translating" in f.reason

    def test_empty_output_fails(self) -> None:
        f = check_script("hello", "", "ur")
        assert f.severity is Severity.FAIL

    def test_unknown_language_warns(self) -> None:
        f = check_script("hello", "hola", "xx")
        assert f.severity is Severity.WARN


class TestEchoAxis:
    def test_identical_fails(self) -> None:
        f = check_echo("Zyx qwerty", "Zyx qwerty")
        assert f.severity is Severity.FAIL
        assert f.score == 0.0

    def test_near_identical_fails(self) -> None:
        f = check_echo("the quick brown fox", "the quick brown fox.")
        assert f.severity is Severity.FAIL

    def test_real_translation_passes(self) -> None:
        f = check_echo("Please send the invoice", URDU_INVOICE)
        assert f.severity is Severity.OK

    def test_partial_overlap_warns(self) -> None:
        # Mostly the same words, one changed: suspicious but not an echo.
        f = check_echo("send the invoice by friday", "send the invoice by monday")
        assert f.severity in (Severity.WARN, Severity.OK)


class TestLengthAxis:
    def test_similar_length_passes(self) -> None:
        f = check_length("hello there friend", "hola amigo querido")
        assert f.severity is Severity.OK

    def test_severe_truncation_fails(self) -> None:
        f = check_length("The quick brown fox jumps over the lazy dog", "لومڑی")
        assert f.severity is Severity.FAIL

    def test_empty_output_fails(self) -> None:
        f = check_length("some text here", "")
        assert f.severity is Severity.FAIL

    def test_expansion_within_range_passes(self) -> None:
        # German compounds are long; 2x is normal.
        f = check_length("car", "Personenkraftwagen")
        assert f.severity is Severity.OK


class TestRoundTripAxis:
    def test_good_round_trip_passes(self) -> None:
        f = check_round_trip(
            "Please send the invoice by Friday",
            "Please send the invoice by Friday",
            "en",
        )
        assert f.severity is Severity.OK

    def test_bad_round_trip_fails(self) -> None:
        f = check_round_trip("The cat sat on the mat", "xyz abc", "en")
        assert f.severity is Severity.FAIL

    def test_cross_script_is_skipped_not_failed(self) -> None:
        """The bug this test exists for.

        Roman Urdu source, Urdu-script back-translation: zero token overlap for
        a perfectly correct translation. Must be a skip, not a failure.
        """
        f = check_round_trip("Mujhe kal office jana hai", "مجھے کل آفس جانا ہے", "ur")
        assert f.severity is Severity.WARN
        assert "skipped" in f.reason


class TestTransliterationAxis:
    def test_respelling_fails(self) -> None:
        """The trap: same words, normalised spelling, reported as success."""
        f = check_transliteration("Aaj mausam bohat acha hai", "aaj mosam acha hy", "en")
        assert f.severity is Severity.FAIL
        assert "respelled" in f.reason

    def test_real_translation_passes(self) -> None:
        f = check_transliteration(
            "Mujhe kal office jana hai",
            "I have to go to the office tomorrow.",
            "en",
        )
        assert f.severity is Severity.OK

    def test_not_applicable_for_non_latin_target(self) -> None:
        f = check_transliteration("hello", URDU_INVOICE, "ur")
        assert f.severity is Severity.OK
        assert "Not applicable" in f.reason


class TestVerdict:
    def test_good_translation_is_verified(self) -> None:
        v = verify(
            "Please send the invoice by Friday",
            URDU_INVOICE,
            "en",
            "ur",
            round_trip="Please send the invoice by Friday",
        )
        assert v.verdict is Verdict.VERIFIED
        assert v.confidence > 0.9

    def test_echo_is_failed(self) -> None:
        v = verify("Zyx qwerty", "Zyx qwerty", "ur", "en", round_trip="Zyx qwerty")
        assert v.verdict is Verdict.FAILED

    def test_transliteration_is_failed(self) -> None:
        v = verify(
            "Aaj mausam bohat acha hai",
            "aaj mosam acha hy",
            "ur",
            "en",
            round_trip="Aaj mausam bohat acha hai",
        )
        assert v.verdict is Verdict.FAILED

    def test_truncation_is_uncertain(self) -> None:
        v = verify(
            "The quick brown fox jumps over the lazy dog and keeps running",
            "لومڑی",
            "en",
            "ur",
            round_trip="x",
        )
        assert v.verdict is Verdict.UNCERTAIN

    def test_missing_round_trip_warns(self) -> None:
        v = verify("Please send it", URDU_INVOICE, "en", "ur", round_trip=None)
        rt = next(f for f in v.findings if f.axis == "round_trip")
        assert rt.severity is Severity.WARN
        assert "not independently tested" in rt.reason

    def test_all_five_axes_present(self) -> None:
        v = verify("hello", "hola", "en", "es", round_trip="hello")
        axes = {f.axis for f in v.findings}
        assert axes == {"script", "echo", "length", "transliteration", "round_trip"}

    def test_passed_property(self) -> None:
        v = verify(
            "Please send the invoice by Friday",
            URDU_INVOICE,
            "en",
            "ur",
            round_trip="Please send the invoice by Friday",
        )
        assert v.passed is True

    def test_failed_is_not_passed(self) -> None:
        v = verify("Zyx", "Zyx", "ur", "en", round_trip="Zyx")
        assert v.passed is False


class TestSerialisation:
    def test_to_dict_shape(self) -> None:
        v = verify("hello", "hola", "en", "es", round_trip="hello")
        d = v.to_dict()
        assert set(d) == {"verdict", "confidence", "findings", "round_trip"}
        assert isinstance(d["findings"], list)
        assert all(set(f) == {"axis", "severity", "score", "reason"} for f in d["findings"])

    def test_summarise_every_verdict(self) -> None:
        for verdict in Verdict:
            v = verify("hello", "hola", "en", "es", round_trip="hello")
            v.verdict = verdict
            assert summarise(v)
