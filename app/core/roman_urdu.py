"""Roman Urdu detection.

Most Pakistani users do not type Urdu script. They type "Aaj mausam bohat acha
hai" -- Urdu words in Latin letters. No translation provider has a language code
for this, so the obvious move is to declare the source as Urdu and let the
provider sort it out.

That move fails silently, and it fails in the worst possible way. Ask MyMemory
to translate "Aaj mausam bohat acha hai" from Urdu to English and it returns
"aaj mosam acha hy": the same sentence, respelled. HTTP 200. ``match`` 0.85.
Every naive check passes, because the output is Latin script (as English is),
differs from the input (44% token overlap), is a plausible length, and round-
trips perfectly -- it round-trips perfectly *because nothing happened*.

So we detect Roman Urdu ourselves, from a lexicon of function words. Function
words rather than content words on purpose: "acha" and "bohat" also appear in
transliterated Hindi and in names, but "hai", "nahi", "kya", "aap" and "mujhe"
are the load-bearing grammar of the language and are far more diagnostic.

The detector is deliberately conservative. A false positive means we refuse to
translate ordinary English, which is worse than a false negative.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# High-frequency Roman Urdu function words. Chosen because they are common in
# real messages and rare in English. Deliberately excludes words that collide
# with English or with common names ("do", "hi", "main", "kal", "na").
_FUNCTION_WORDS: frozenset[str] = frozenset(
    {
        # copulas and negation
        # NOTE: "the" is deliberately absent. It is the Roman Urdu plural past
        # of "tha" (they were), but it is also the single most common word in
        # English, and including it made "The quick brown fox..." register as
        # Roman Urdu. The plural past is rare in typed messages; "the" is not.
        "hai",
        "hain",
        "hoon",
        "hun",
        "tha",
        "thi",
        "nahi",
        "nahin",
        "nai",
        # pronouns
        "aap",
        "tum",
        "hum",
        "mujhe",
        "mujhay",
        "tumhe",
        "unhe",
        "inhe",
        "apna",
        "apni",
        "apne",
        "mera",
        "meri",
        "mere",
        "tera",
        "teri",
        "uska",
        "uski",
        "hamara",
        "hamari",
        "aapka",
        "aapki",
        "aapke",
        # question words
        "kya",
        "kaise",
        "kaisay",
        "kyun",
        "kyu",
        "kab",
        "kahan",
        "kaun",
        "kitna",
        "kitni",
        "kitne",
        # postpositions and conjunctions
        "mein",
        "se",
        "ko",
        "ka",
        "ki",
        "ke",
        "aur",
        "ya",
        "lekin",
        "magar",
        "phir",
        "bhi",
        "sirf",
        "liye",
        "wala",
        "wali",
        "walay",
        "tak",
        "saath",
        # common verbs
        "karna",
        "karo",
        "karein",
        "karen",
        "kar",
        "kiya",
        "raha",
        "rahi",
        "rahe",
        "jana",
        "jata",
        "jati",
        "gaya",
        "gayi",
        "aana",
        "aata",
        "aati",
        "aya",
        "dena",
        "deta",
        "deti",
        "diya",
        "lena",
        "leta",
        "leti",
        "liya",
        "bolna",
        "bolta",
        "bolti",
        "sakta",
        "sakti",
        "sakte",
        "chahiye",
        "chahta",
        "chahti",
        # everyday adverbs and quantifiers
        "bohat",
        "bohot",
        "bahut",
        "thoda",
        "zyada",
        "ziyada",
        "kam",
        "acha",
        "achi",
        "achay",
        "theek",
        "thik",
        "abhi",
        "ab",
        "aaj",
        "kal",
        "parson",
        "hamesha",
        "kabhi",
        "dobara",
        "jaldi",
        "der",
        "yahan",
        "wahan",
        "kuch",
        "sab",
        "koi",
        "log",
        "baat",
        "cheez",
        "pani",
        "khana",
        "ghar",
        "kaam",
        "waqt",
        "din",
        "raat",
        "subah",
        "shaam",
        "mausam",
        "kitab",
        "dost",
        "bhai",
        "behen",
        "walid",
        "ammi",
        "abbu",
        "hoga",
        "hogi",
        "honge",
        "hona",
        "milna",
        "milta",
        "milti",
        "samajh",
        "pata",
        "maloom",
        "zaroor",
        "zarurat",
        "zaroorat",
        "madad",
        "shukriya",
        "salam",
        "khuda",
        "allah",
        "inshallah",
        "mashallah",
        "yaar",
        "bas",
        "bilkul",
        "shayad",
        "agar",
        "toh",
        "to",
        "hi",
        "warna",
        "isliye",
        "kyunke",
        "kyunki",
        "jab",
        "tab",
    }
)

# Words that look Roman Urdu but are overwhelmingly English in practice. If the
# text is mostly these, it is English.
_ENGLISH_GUARD: frozenset[str] = frozenset(
    {
        "the",
        "and",
        "is",
        "are",
        "was",
        "were",
        "have",
        "has",
        "had",
        "will",
        "would",
        "should",
        "could",
        "can",
        "this",
        "that",
        "these",
        "those",
        "with",
        "from",
        "for",
        "about",
        "into",
        "your",
        "our",
        "their",
        "my",
        "please",
        "thank",
        "thanks",
        "hello",
        "hi",
        "yes",
        "no",
        "not",
        "what",
        "when",
        "where",
        "who",
        "how",
        "why",
        "which",
        "there",
        "here",
        "just",
        "very",
        "much",
        "more",
        "most",
        "some",
        "any",
        "all",
        "one",
        "two",
    }
)

_WORD = re.compile(r"[A-Za-z']+")

# Minimum share of tokens that must be Roman Urdu function words before we call
# the text Roman Urdu. Tuned against real messages: a single "hai" in an English
# sentence should not flip the verdict.
MIN_RATIO = 0.22
MIN_HITS = 2


@dataclass(frozen=True, slots=True)
class RomanUrduProfile:
    """How Roman-Urdu a piece of Latin-script text looks."""

    is_roman_urdu: bool
    ratio: float
    hits: int
    tokens: int
    matched: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "is_roman_urdu": self.is_roman_urdu,
            "ratio": round(self.ratio, 3),
            "hits": self.hits,
            "tokens": self.tokens,
            "matched": list(self.matched[:12]),
        }


def analyse(text: str) -> RomanUrduProfile:
    """Decide whether ``text`` is Urdu written in Latin letters."""
    tokens = [t.lower() for t in _WORD.findall(text)]
    if not tokens:
        return RomanUrduProfile(False, 0.0, 0, 0, ())

    hits = [t for t in tokens if t in _FUNCTION_WORDS]
    english = sum(1 for t in tokens if t in _ENGLISH_GUARD)
    ratio = len(hits) / len(tokens)

    # If English function words outnumber Roman Urdu ones, it is English.
    if english > len(hits):
        return RomanUrduProfile(False, ratio, len(hits), len(tokens), tuple(hits))

    is_ru = ratio >= MIN_RATIO and len(hits) >= MIN_HITS
    return RomanUrduProfile(is_ru, ratio, len(hits), len(tokens), tuple(hits))


def is_roman_urdu(text: str) -> bool:
    return analyse(text).is_roman_urdu


def looks_like_transliteration(source: str, target: str) -> bool:
    """Is ``target`` the same Roman Urdu sentence, respelled?

    This is the specific failure the provider produces: it "translates" Roman
    Urdu to English by normalising the spelling. The tell is that the output is
    still Roman Urdu -- it still carries the same function words -- while the
    input was Roman Urdu too.

    We require the output to be Roman Urdu *and* to share a meaningful share of
    its tokens with the input. A genuine English translation of a Roman Urdu
    sentence contains almost none of the original function words.
    """
    src = analyse(source)
    if not src.is_roman_urdu:
        return False

    tgt = analyse(target)
    if not tgt.is_roman_urdu:
        return False

    # Both sides read as Roman Urdu, which is already damning: a genuine English
    # translation of a Roman Urdu sentence is not itself Roman Urdu.
    #
    # The overlap check below is only a sanity guard, and its threshold is low
    # on purpose. Respelling rewrites most words -- "mausam" becomes "mosam",
    # "hai" becomes "hy" -- so a real transliteration shares surprisingly little
    # vocabulary with its input. An earlier version of this function required
    # 30% overlap and missed the exact case it was written for at 28.6%.
    src_tokens = {t.lower() for t in _WORD.findall(source)}
    tgt_tokens = {t.lower() for t in _WORD.findall(target)}
    if not src_tokens or not tgt_tokens:
        return False
    overlap = len(src_tokens & tgt_tokens) / len(src_tokens | tgt_tokens)
    return overlap >= 0.15


__all__ = [
    "MIN_HITS",
    "MIN_RATIO",
    "RomanUrduProfile",
    "analyse",
    "is_roman_urdu",
    "looks_like_transliteration",
]
