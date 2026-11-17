# Architecture

## The problem, stated precisely

Every translation API I tested returns **HTTP 200 for text it cannot translate**.

Ask MyMemory to translate `"Zyx qwerty plonking"` into Urdu and it returns
Urdu-script gibberish. Ask it to translate the same string *from* Urdu and it
returns the input unchanged. In both cases `responseStatus` is `200` and `match`
is `0.85` — the same `0.85` it returns for a perfect translation. The API's own
confidence field is a constant, so it carries no information at all.

A naive client therefore reports success on garbage. Worse, a naive round-trip
check reports **verified** on a no-op: translate X, translate back, compare, and
if the provider echoed the input both ways you get a perfect score for having
done nothing.

Tarjuman exists to make that failure visible.

## System diagram

```
┌──────────────────────────────────────────────────────────────────┐
│  Browser — single page, three views, no build step               │
│  ┌────────────┬──────────────┬──────────────┐                    │
│  │ Translate  │ Conversation │   History    │                    │
│  └────────────┴──────────────┴──────────────┘                    │
│         │              │             │                           │
│         └──────────────┴─────────────┘                           │
│                        │ fetch + Bearer JWT                      │
└────────────────────────┼─────────────────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────────────────┐
│  FastAPI                                                         │
│                                                                  │
│  middleware:  security headers → CORS → rate limit → size guard  │
│                                                                  │
│  routes:  /api/auth   /api/translate   /api/history              │
│           /api/conversations   /api/languages   /api/health      │
└────────────────────────┬─────────────────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────────────────┐
│  app.core.translator  — orchestration                            │
│                                                                  │
│   1. resolve_source()      script detection + Roman Urdu check   │
│   2. chunk()               split to fit the 500-char limit       │
│   3. provider.translate()  one call per chunk                    │
│   4. provider.translate()  again, backwards, for round-trip      │
│   5. verify()              five independent axes                 │
└───────┬──────────────────────────────────┬───────────────────────┘
        ▼                                  ▼
┌───────────────────────┐        ┌─────────────────────────────────┐
│ app.core.verify       │        │ app.core.provider               │
│                       │        │                                 │
│  script conformance   │        │  MyMemory GET endpoint          │
│  echo detection       │        │  retry with backoff             │
│  length plausibility  │        │  in-process TTL cache           │
│  transliteration      │        │  honest error mapping           │
│  round-trip fidelity  │        │                                 │
│         ↓             │        └─────────────────────────────────┘
│   verdict + evidence  │
└───────────────────────┘
        ▼
┌──────────────────────────────────────────────────────────────────┐
│  SQLAlchemy  →  SQLite (default)  |  PostgreSQL (DATABASE_URL)   │
│  users · translations · conversation_sessions · conversation_turns│
└──────────────────────────────────────────────────────────────────┘
```

## The five verification axes

Each axis is independent and each produces a score, a severity, and a sentence
explaining itself. The verdict is the worst finding.

| Axis | Weight | What it catches |
|---|---|---|
| **Script conformance** | 0.25 | Asked for Urdu, got Latin back. The cheapest reliable proof that nothing happened. |
| **Echo detection** | 0.15 | Output identical or near-identical to input. Catches no-ops that share a script. |
| **Length plausibility** | 0.10 | Truncation and padding. Exempt below 10 characters, where the ratio is noise. |
| **Transliteration** | 0.20 | The text was respelled, not translated. Only meaningful for Latin-script targets. |
| **Round-trip fidelity** | 0.30 | Meaning survived. The only axis that tests meaning — and the one that lies on a no-op. |

### Why round-trip is never trusted alone

If the provider echoes the input in both directions, the round trip is perfect.
That is exactly the failure mode a naive implementation ships. So a failed
round trip on its own yields `uncertain`, not `failed` — idioms and formal
register routinely fail to round-trip while the forward translation is fine. But
a failed round trip **combined** with a failed script, echo, or transliteration
check means the provider was not translating, and the verdict is `failed`.

### Why the transliteration axis exists

This is the failure no other axis catches, and it is the one that matters most
for the audience this was built for.

Ask a provider to translate Roman Urdu — Urdu written in Latin letters, which is
what most Pakistani users actually type — into English, and it may return the
same sentence with the spelling normalised:

```
in:   Aaj mausam bohat acha hai
out:  aaj mosam acha hy
```

The output is Latin script (as English is), differs from the input (44% token
overlap), is a plausible length, and round-trips perfectly — **because nothing
happened**. Every other axis passes. Only a check that asks "is this still Roman
Urdu?" catches it.

## Data flow: one translation

```
POST /api/translate {text, source_lang, target_lang}
  │
  ├─ validate: length ≤ 5000, language codes known, not same-language
  │
  ├─ resolve_source()
  │    declared "ur" + Latin script + reads as Roman Urdu  →  ("ur", roman=True)
  │    declared "ur" + Latin script + reads as English     →  ("en", roman=False)
  │
  ├─ chunk(text)  →  [Chunk(text, separator), …]   lossless, ≤ 380 chars each
  │
  ├─ for each chunk: provider.translate(chunk, src, tgt)
  │
  ├─ if len(text) ≤ 1200: provider.translate(whole, tgt, src)   ← round trip
  │
  ├─ verify() per chunk  →  each chunk carries its own verdict
  ├─ verify() whole      →  the document verdict
  │
  └─ if any chunk failed, the document failed
       (an aggregate score hides one bad paragraph in ten)
```

## Scaling notes

**What is already right.** Stateless HTTP, no session affinity, provider calls
are per-request and cacheable, the verification layer is pure functions with no
I/O, and the database is behind an ORM with a connection pool.

**What breaks first, in order:**

1. **The in-process cache.** `app/core/provider.py` keeps a bounded dict. With N
   workers you get N caches and N× the provider calls. Redis is the fix, and the
   interface (`_cache_get` / `_cache_put`) is shaped so it is a one-file change.

2. **The rate limiter.** Same problem, same fix. `app/core/ratelimit.py` is a
   fixed-window counter in process memory. It stops one client hammering the
   endpoint, which is the actual threat, but it does not enforce a global limit.

3. **The provider's free tier.** MyMemory allows a limited number of words per
   day per IP. A real deployment needs a paid provider or a self-hosted model.
   The `MyMemoryProvider` class is the seam: implement `translate()` and
   `max_chars`, and nothing else changes.

4. **`create_all()` instead of migrations.** Fine for one deploy. Alembic before
   the first schema change on real data.

5. **Round-trip doubles cost.** Already mitigated: skipped above 1200 characters,
   and the verifier reports the axis as *skipped* rather than *passed*, so the
   gap is visible instead of silent.

**What would need rethinking at real scale.** Verification is currently
synchronous with the request. At high volume the round-trip call should move to
a background job and the response should return `verdict: pending` with a
polling or WebSocket channel. The data model already stores the verdict per
translation, so this is a transport change, not a schema change.

## Deliberate non-goals

- **No language model.** Every check is deterministic and explainable. A model
  would score better on some inputs and be unable to say why, which defeats the
  entire premise.
- **No claim about truth.** Tarjuman verifies *how* a translation was produced,
  not whether the original sentence is factually correct. The UI says so.
- **No speech.** The project brief mentions speech translation; this build is
  text-only, and the README says so rather than shipping a fake microphone.
