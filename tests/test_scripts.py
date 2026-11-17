"""Tests for script detection."""

from __future__ import annotations

import pytest

from app.core.scripts import (
    Script,
    detect,
    is_rtl,
    profile,
    script_matches,
)


class TestDetection:
    def test_english_is_latin(self) -> None:
        assert detect("The quick brown fox") is Script.LATIN

    def test_urdu_is_arabic_script(self) -> None:
        assert detect("صبح بخیر، آپ کیسے ہیں؟") is Script.ARABIC

    def test_hindi_is_devanagari(self) -> None:
        assert detect("सुप्रभात, आप कैसे हैं?") is Script.DEVANAGARI

    def test_chinese_is_cjk(self) -> None:
        assert detect("早上好，你好吗？") is Script.CJK

    def test_russian_is_cyrillic(self) -> None:
        assert detect("Доброе утро") is Script.CYRILLIC

    def test_empty_string(self) -> None:
        assert detect("") is Script.EMPTY

    def test_punctuation_only_is_empty(self) -> None:
        assert detect("!!! ??? ...") is Script.EMPTY

    def test_digits_only_is_empty(self) -> None:
        assert detect("12345 67890") is Script.EMPTY


class TestProfile:
    def test_purity_of_pure_text(self) -> None:
        p = profile("hello world")
        assert p.purity == 1.0
        assert p.letters == 10

    def test_mixed_script_purity(self) -> None:
        # 5 Latin letters, 5 Arabic letters.
        p = profile("hello صبح بخ")
        assert p.letters == 10
        assert 0.4 <= p.purity <= 0.6

    def test_urdu_markers_detected(self) -> None:
        # ٹ and ے are Urdu-only letters, absent from standard Arabic.
        p = profile("ٹھیک ہے")
        assert p.urdu_markers >= 2
        assert p.looks_urdu is True

    def test_arabic_without_urdu_markers(self) -> None:
        p = profile("مرحبا بك")
        assert p.script is Script.ARABIC
        assert p.looks_urdu is False

    def test_loanword_does_not_break_urdu(self) -> None:
        # "WhatsApp" in Latin inside an Urdu sentence.
        p = profile("میں WhatsApp استعمال کرتا ہوں")
        assert p.script is Script.ARABIC
        assert p.purity > 0.6


class TestRtl:
    @pytest.mark.parametrize("text", ["اردو", "مرحبا", "עברית"])
    def test_rtl_scripts(self, text: str) -> None:
        assert is_rtl(text) is True

    @pytest.mark.parametrize("text", ["english", "français", "русский"])
    def test_ltr_scripts(self, text: str) -> None:
        assert is_rtl(text) is False


class TestScriptMatches:
    def test_exact_match(self) -> None:
        assert script_matches("hello", Script.LATIN) is True

    def test_urdu_with_loanword_passes(self) -> None:
        # Mostly Urdu with one English word: still Urdu.
        assert script_matches("میں WhatsApp استعمال کرتا ہوں", Script.ARABIC) is True

    def test_english_text_fails_arabic_expectation(self) -> None:
        assert script_matches("this is english", Script.ARABIC) is False

    def test_empty_never_matches(self) -> None:
        assert script_matches("", Script.LATIN) is False
