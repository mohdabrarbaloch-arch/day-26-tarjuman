"""Tests for Roman Urdu detection."""

from __future__ import annotations

import pytest

from app.core.roman_urdu import analyse, is_roman_urdu, looks_like_transliteration

ROMAN_URDU = [
    "Aaj mausam bohat acha hai",
    "Mujhe kal office jana hai",
    "Kya aap angrezi bolte hain",
    "Bhai pani de do",
    "Yeh kitab bohat achi hai",
    "Main ghar ja raha hoon",
    "Aap kaise hain",
    "Mujhe madad chahiye",
]

ENGLISH = [
    "Please send the invoice by Friday",
    "The meeting is at four o clock",
    "I will call you tomorrow morning",
    "Hello, how are you doing today?",
    "My name is Ali and I need water",
    "We should review the quarterly report",
    "Zyx qwerty plonking",
    "The quick brown fox jumps over the lazy dog",
]


class TestDetection:
    @pytest.mark.parametrize("text", ROMAN_URDU)
    def test_roman_urdu_detected(self, text: str) -> None:
        assert is_roman_urdu(text) is True, f"missed: {text}"

    @pytest.mark.parametrize("text", ENGLISH)
    def test_english_not_flagged(self, text: str) -> None:
        assert is_roman_urdu(text) is False, f"false positive: {text}"

    def test_empty_is_not_roman_urdu(self) -> None:
        assert is_roman_urdu("") is False

    def test_punctuation_only(self) -> None:
        assert is_roman_urdu("!!! ???") is False

    def test_single_urdu_word_in_english_sentence(self) -> None:
        # One "hai" should not flip an English sentence.
        assert is_roman_urdu("The report is ready and I will send it hai") is False


class TestProfile:
    def test_ratio_reported(self) -> None:
        p = analyse("Aaj mausam bohat acha hai")
        assert p.ratio > 0.5
        assert p.hits >= 3
        assert p.tokens == 5

    def test_matched_words_listed(self) -> None:
        p = analyse("Mujhe pani chahiye")
        assert "mujhe" in p.matched
        assert "chahiye" in p.matched

    def test_to_dict_shape(self) -> None:
        d = analyse("Aaj mausam acha hai").to_dict()
        assert set(d) == {"is_roman_urdu", "ratio", "hits", "tokens", "matched"}


class TestTransliteration:
    def test_respelling_detected(self) -> None:
        """The exact failure the live provider produced."""
        assert looks_like_transliteration("Aaj mausam bohat acha hai", "aaj mosam acha hy") is True

    def test_real_translation_not_flagged(self) -> None:
        assert (
            looks_like_transliteration(
                "Mujhe kal office jana hai", "I have to go to the office tomorrow."
            )
            is False
        )

    def test_english_source_never_flagged(self) -> None:
        assert looks_like_transliteration("Please send it", "Please send it") is False

    def test_urdu_script_target_not_flagged(self) -> None:
        assert looks_like_transliteration("Aaj mausam acha hai", "آج موسم اچھا ہے") is False
