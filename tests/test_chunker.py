"""Tests for the chunker.

The property that matters is losslessness: chunking then reassembling must give
back the original string exactly. A chunker that drops a space produces
translations that are individually fine and collectively wrong, and the bug only
shows up in production.
"""

from __future__ import annotations

import pytest

from app.core.chunker import (
    DEFAULT_LIMIT,
    Chunk,
    chunk,
    needs_chunking,
    reassemble,
)

CASES = [
    "",
    "   ",
    "Short.",
    "A" * 900,
    "The quick brown fox jumps over the lazy dog. " * 20,
    "Para one.\n\nPara two is longer, with commas; and clauses. And more.\n\nThird.",
    "اردو متن یہاں ہے۔ یہ دوسرا جملہ ہے۔ اور تیسرا بھی۔" * 8,
    "word " * 200,
    "https://example.com/" + "x" * 600,
    "Mixed 中文 text with English and اردو together. " * 15,
    "Line one\nLine two\nLine three\n" * 30,
    "No spaces at all " + "z" * 500,
]


class TestLosslessness:
    @pytest.mark.parametrize("text", CASES)
    def test_round_trip_is_exact(self, text: str) -> None:
        assert reassemble(chunk(text)) == text

    @pytest.mark.parametrize("text", CASES)
    def test_every_chunk_within_limit(self, text: str) -> None:
        for c in chunk(text):
            assert len(c.text) <= DEFAULT_LIMIT, f"chunk too long: {len(c.text)}"

    @pytest.mark.parametrize("text", CASES)
    def test_no_empty_chunks(self, text: str) -> None:
        for c in chunk(text):
            assert c.text != ""


class TestBoundaries:
    def test_short_text_is_one_chunk(self) -> None:
        assert len(chunk("Hello world")) == 1

    def test_empty_text_is_no_chunks(self) -> None:
        assert chunk("") == []

    def test_splits_on_sentence_boundary(self) -> None:
        text = "First sentence here. Second sentence here. Third sentence here."
        chunks = chunk(text, limit=40)
        # Each chunk should end at a sentence boundary, not mid-word.
        for c in chunks[:-1]:
            assert c.text.rstrip().endswith("."), f"bad boundary: {c.text!r}"

    def test_splits_on_paragraph_first(self) -> None:
        text = "A" * 200 + "\n\n" + "B" * 200
        chunks = chunk(text, limit=250)
        assert len(chunks) == 2
        assert chunks[0].text.startswith("A")
        assert chunks[1].text.startswith("B")

    def test_long_url_is_hard_split(self) -> None:
        url = "https://example.com/" + "y" * 800
        chunks = chunk(url, limit=100)
        assert len(chunks) > 1
        assert reassemble(chunks) == url

    def test_urdu_sentence_boundary(self) -> None:
        # ۔ is the Urdu full stop.
        text = "پہلا جملہ یہاں ہے۔ دوسرا جملہ یہاں ہے۔ تیسرا جملہ یہاں ہے۔"
        chunks = chunk(text, limit=40)
        assert len(chunks) > 1
        assert reassemble(chunks) == text


class TestValidation:
    def test_limit_too_small_raises(self) -> None:
        with pytest.raises(ValueError):
            chunk("hello", limit=5)

    def test_needs_chunking_true(self) -> None:
        assert needs_chunking("x" * 500) is True

    def test_needs_chunking_false(self) -> None:
        assert needs_chunking("short") is False


class TestChunkDataclass:
    def test_separator_preserved(self) -> None:
        c = Chunk("hello", " ")
        assert c.text == "hello"
        assert c.separator == " "

    def test_default_separator_empty(self) -> None:
        assert Chunk("hello").separator == ""
