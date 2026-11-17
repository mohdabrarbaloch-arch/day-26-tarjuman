"""Text chunking for a provider with a hard 500-character limit.

MyMemory rejects anything over 500 characters with HTTP 403. Naive slicing
breaks words and sentences, which produces translations that are individually
correct and collectively nonsense -- the model sees half a clause and guesses.

So we split on the largest natural boundary that fits: paragraph, then sentence,
then clause, then word. Reassembly is lossless: joining the chunks with the
separators we recorded gives back the original string byte for byte. That
property is tested, because a chunker that silently drops a space is the kind of
bug that only shows up in production.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Provider limit is 500. We stay well under it: URL-encoding expands non-ASCII
# text, and a chunk that is 499 characters of Urdu can exceed the limit once
# encoded. 380 leaves comfortable headroom.
DEFAULT_LIMIT = 380

# Sentence terminators across the scripts we support. Devanagari and CJK use
# their own marks; including them means Hindi and Chinese split properly.
_SENTENCE_END = re.compile(r"(?<=[.!?۔।。！？])\s+")
_CLAUSE_END = re.compile(r"(?<=[,;:،؛])\s+")


@dataclass(frozen=True, slots=True)
class Chunk:
    """One piece of text, plus the separator that followed it in the original."""

    text: str
    separator: str = ""


def _split_keep(text: str, pattern: re.Pattern[str]) -> list[str]:
    """Split on ``pattern`` but keep the separators attached to the left piece."""
    parts: list[str] = []
    last = 0
    for match in pattern.finditer(text):
        parts.append(text[last : match.start()])
        last = match.start()
    parts.append(text[last:])
    return [p for p in parts if p]


def _hard_split(word: str, limit: int) -> list[str]:
    """Last resort: a single token longer than the limit (a URL, a hash)."""
    return [word[i : i + limit] for i in range(0, len(word), limit)]


def _pack(pieces: list[str], limit: int) -> list[str]:
    """Greedily merge adjacent pieces while they fit under ``limit``."""
    out: list[str] = []
    current = ""
    for piece in pieces:
        if not current:
            current = piece
        elif len(current) + len(piece) <= limit:
            current += piece
        else:
            out.append(current)
            current = piece
    if current:
        out.append(current)
    return out


def chunk(text: str, limit: int = DEFAULT_LIMIT) -> list[Chunk]:
    """Split ``text`` into chunks no longer than ``limit`` characters.

    The returned chunks, concatenated with their separators, reproduce the
    input exactly.
    """
    if limit < 20:
        raise ValueError("limit must be at least 20 characters")
    if not text:
        return []
    if len(text) <= limit:
        return [Chunk(text, "")]

    # Level 1: paragraphs. Blank lines are the strongest boundary we have.
    paragraphs = re.split(r"(\n\s*\n)", text)
    blocks: list[str] = []
    for part in paragraphs:
        if part and not part.strip():
            blocks.append(part)  # keep the whitespace block as its own piece
        elif part:
            blocks.append(part)

    chunks: list[str] = []
    for block in blocks:
        if not block.strip():
            # Pure whitespace: attach to the previous chunk if it fits.
            if chunks and len(chunks[-1]) + len(block) <= limit:
                chunks[-1] += block
            else:
                chunks.append(block)
            continue
        if len(block) <= limit:
            chunks.append(block)
            continue

        # Level 2: sentences, then clauses, then words.
        for level in (_SENTENCE_END, _CLAUSE_END):
            if len(block) <= limit:
                break
            pieces = _split_keep(block, level)
            packed = _pack(pieces, limit)
            block_parts = packed if len(packed) > 1 or len(packed[0]) <= limit else [block]
            if all(len(p) <= limit for p in block_parts):
                chunks.extend(block_parts)
                block = ""
                break
        if not block:
            continue

        # Level 3: words.
        words = re.split(r"(\s+)", block)
        packed = _pack(words, limit)
        if all(len(p) <= limit for p in packed):
            chunks.extend(packed)
            continue

        # Level 4: a single token longer than the limit.
        for piece in packed:
            if len(piece) <= limit:
                chunks.append(piece)
            else:
                chunks.extend(_hard_split(piece, limit))

    # Attach separators: everything after a chunk up to the next chunk's start.
    result: list[Chunk] = []
    cursor = 0
    for i, piece in enumerate(chunks):
        start = text.find(piece, cursor)
        if start < 0:  # defensive: should not happen
            start = cursor
        end = start + len(piece)
        nxt = chunks[i + 1] if i + 1 < len(chunks) else None
        if nxt is None:
            sep = text[end:]
        else:
            nxt_start = text.find(nxt, end)
            sep = text[end:nxt_start] if nxt_start >= 0 else ""
        result.append(Chunk(piece, sep))
        cursor = end + len(sep)
    return result


def reassemble(chunks: list[Chunk]) -> str:
    """Rebuild the original text from chunks. Inverse of :func:`chunk`."""
    return "".join(c.text + c.separator for c in chunks)


def needs_chunking(text: str, limit: int = DEFAULT_LIMIT) -> bool:
    return len(text) > limit
