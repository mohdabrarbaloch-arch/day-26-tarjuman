# Tarjuman · ترجمان

**Translation that shows its work.**

[![Python](https://img.shields.io/badge/python-3.11+-3776ab?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Tests](https://img.shields.io/badge/tests-167%20passing-4ec9a8)](tests/)
[![Ruff](https://img.shields.io/badge/lint-ruff%20clean-4ec9a8)](https://github.com/astral-sh/ruff)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

---

## Why this exists

Every translation API I tested returns **HTTP 200 for text it cannot translate**.

Ask MyMemory to translate `"Zyx qwerty plonking"` into Urdu and it hands back
Urdu-script gibberish. Ask it to translate the same string *from* Urdu and it
hands back the input unchanged. Both times `responseStatus` is `200` and `match`
is `0.85` — the same `0.85` it returns for a perfect translation. The API's own
confidence field is a constant, so it tells you nothing.

So a normal client reports success on garbage. And a normal round-trip check
reports **verified** on a no-op, because if the provider echoed the input both
ways, the round trip is perfect.

Tarjuman checks every translation on five independent axes and shows you the
evidence. When it says a translation is bad, you can see exactly which check
failed and read the sentence explaining why.

---

## What it actually does

Paste text, pick two languages, hit translate. You get the translation **and** a
verdict panel:

```
┌─────────────────────────────────────────────────────────────┐
│  ● VERIFIED          Every check passed.        confidence  │
│                                                  ███████ 100%│
├─────────────────────────────────────────────────────────────┤
│  ✓ Script conformance                              1.00     │
│    100% of the output is arabic script, as Urdu requires.   │
│  ✓ Echo detection                                  1.00     │
│    The output differs from the input (0% overlap), so       │
│    translation did occur.                                   │
│  ✓ Length plausibility                             1.00     │
│    33 characters out for 34 in — within the normal range.   │
│  ✓ Transliteration check                           1.00     │
│    Not applicable: the target language is not written in    │
│    Latin script.                                            │
│  ✓ Round-trip fidelity                             1.00     │
│    Translating back gives 100% of the original wording, so  │
│    the meaning held.                                        │
└─────────────────────────────────────────────────────────────┘
```

And when it fails, it says so:

```
┌─────────────────────────────────────────────────────────────┐
│  ● FAILED       The provider did not translate this.        │
├─────────────────────────────────────────────────────────────┤
│  ✓ Script conformance                              1.00     │
│  ✓ Echo detection                                  0.56     │
│  ✓ Length plausibility                             1.00     │
│  ✕ Transliteration check                           0.00     │
│    The output is still Roman Urdu — the same words,         │
│    respelled. The provider normalised the spelling instead  │
│    of translating.                                          │
│  ✓ Round-trip fidelity                             0.91     │
│    Translating back gives 91% of the original wording…      │
└─────────────────────────────────────────────────────────────┘
```

That last one is the interesting case. Four of five checks pass. The round trip
is *perfect* — because nothing happened. Only the transliteration check catches
it.

---

## Features

**Verification**
- Five independent axes: script, echo, length, transliteration, round-trip
- Every axis reports a score, a severity, and a plain-English reason
- Per-chunk verdicts — one bad paragraph in ten is not hidden by an average
- Round-trip skipped above 1200 chars and reported as *skipped*, never as *passed*

**Roman Urdu**
- Detects Urdu written in Latin letters from a function-word lexicon
- Flags the transliteration failure that no other check catches
- Conservative by design: a false positive would refuse to translate real English

**Translation**
- 25 languages with script expectations and RTL support
- Lossless chunking for the provider's 500-character limit
- Automatic source detection
- In-process TTL cache

**Conversation mode**
- Two speakers, two languages, one transcript
- Each turn carries its own verdict — a failed turn is marked, not passed through
- Speaker flips automatically after each message

**Everything else**
- JWT auth with bcrypt, no account enumeration
- Per-user history with favourites and verdict filtering
- Rate limiting on the expensive endpoint
- Security headers, CSP, request size guard
- 167 tests, ruff clean, Docker + PostgreSQL ready

---

## Screenshots

| Translate | Verdict panel |
|---|---|
| ![Translate view](docs/screenshots/01-translate.png) | ![Verdict](docs/screenshots/02-verdict.png) |

| Conversation mode | History |
|---|---|
| ![Conversation](docs/screenshots/03-conversation.png) | ![History](docs/screenshots/04-history.png) |

| Mobile |
|---|
| ![Mobile](docs/screenshots/05-mobile.png) |

---

## Live demo

**Not deployed.** There is no `VERCEL_TOKEN` in the build environment, and — more
importantly — Vercel is the wrong host for this app. It needs a persistent
filesystem for SQLite and a real database connection, neither of which a
serverless function provides.

The intended path is Docker, which takes about a minute:

```bash
docker compose up --build
# → http://localhost:8000
```

The production build is verified locally: the app boots, serves the UI, and every
endpoint returns the right status code. See [Verification](#verification) for
exactly what was checked.

---

## Quick start

```bash
git clone https://github.com/mohdabrarbaloch-arch/day-26-tarjuman.git
cd day-26-tarjuman

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -e ".[dev]"

cp .env.example .env
python -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(48))" >> .env

uvicorn app.main:app --reload
```

Open **http://127.0.0.1:8000**.

No API key needed — MyMemory's free endpoint requires none. That is deliberate:
the project should run for anyone who clones it.

### With Docker

```bash
docker compose up --build
```

That brings up the app on port 8000 with PostgreSQL behind it.

### With PostgreSQL instead of SQLite

```bash
export DATABASE_URL="postgresql+psycopg://tarjuman:tarjuman@localhost:5432/tarjuman"
pip install -e ".[postgres]"
uvicorn app.main:app --reload
```

---

## Usage

### Translate

1. Pick a source language (or leave it on **Detect language**)
2. Pick a target
3. Type or paste — up to 5,000 characters
4. Hit **Translate** (or `Ctrl`/`Cmd` + `Enter`)

The verdict panel appears below. Read the axes, not just the badge.

**Try a sample** cycles through four examples, including two Roman Urdu ones that
demonstrate the transliteration check.

### Conversation mode

Sign in, pick two languages, start. Type as speaker A, send, and the app flips to
speaker B automatically. Each turn shows the original above the translation, and
any turn that failed verification is flagged in the transcript.

### History

Every saved translation keeps the verdict it earned **at the time** — not what
the app would say about it today. The verification rules will change; your
history should not silently rewrite itself.

---

## API

Full reference in [`docs/api.md`](docs/api.md). The short version:

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/health` | — | Health check |
| `GET` | `/api/languages` | — | Supported languages |
| `POST` | `/api/auth/register` | — | Create account |
| `POST` | `/api/auth/login` | — | Sign in |
| `GET` | `/api/auth/me` | ✓ | Current user |
| `POST` | `/api/translate` | optional | Translate + verify |
| `GET` | `/api/history` | ✓ | Your translations |
| `PATCH` | `/api/history/{id}/favourite` | ✓ | Star / unstar |
| `DELETE` | `/api/history/{id}` | ✓ | Delete |
| `POST` | `/api/conversations` | ✓ | Start conversation |
| `POST` | `/api/conversations/{id}/turns` | ✓ | Add a turn |
| `GET` | `/api/stats` | — | Provider and cache status |

```bash
curl -X POST http://127.0.0.1:8000/api/translate \
  -H 'Content-Type: application/json' \
  -d '{"text":"Please send the invoice by Friday.","source_lang":"en","target_lang":"ur"}'
```

---

## Verification

What was actually run, and what it showed.

| Check | Result |
|---|---|
| Test suite | **167 passed** in ~7s, no network |
| `ruff check` | clean |
| `ruff format --check` | clean, 30 files |
| Production wheel | builds |
| App boots | `Application startup complete` |
| `GET /` | 200, 10,362 bytes |
| `GET /static/app.css` | 200 |
| `GET /static/app.js` | 200 |
| `GET /api/health` | 200, 25 languages |
| Register → login → me | 201 / 200 / 200 |
| Translate en→ur | `verified`, confidence 1.00, 5 axes |
| Translate Roman Urdu trap | `failed` — transliteration caught |
| Save + history | saved, total 1 |
| Security headers | nosniff, DENY, CSP present |
| Ownership scoping | other user's record → 404, not 403 |

**Not verified:** a live deployment (no token, wrong host — see above), and the
UI in a real browser beyond the screenshots.

---

## What this does not do

Being specific about the limits, because a tool that overstates itself is worse
than no tool.

- **It cannot tell you whether a claim is true.** It verifies *how* a translation
  was produced, not whether the original sentence is factually correct.
- **No speech.** The brief mentions speech translation. This build is text-only.
  There is no microphone button, because there is no speech pipeline behind it.
- **Roman Urdu detection is a lexicon, not a model.** It will miss unusual
  spellings and it will occasionally miss short messages. It is tuned to avoid
  false positives, because refusing to translate real English is worse.
- **The provider's free tier is limited.** Heavy use will hit the daily cap. The
  error is surfaced honestly as `429 quota_exceeded`, not swallowed.
- **Rate limiting is per-process.** N workers behind a load balancer means N×
  the configured rate. Redis is the fix.
- **`create_all()`, not migrations.** Fine for one deploy; Alembic before the
  first schema change on real data.
- **The cache is in-process.** Same scaling caveat as the rate limiter.

---

## Project structure

```
day-26-tarjuman/
├── app/
│   ├── core/
│   │   ├── chunker.py       lossless splitting for the 500-char limit
│   │   ├── config.py        settings, every value defaulted
│   │   ├── languages.py     25 languages with script expectations
│   │   ├── provider.py      MyMemory client, retry, cache
│   │   ├── ratelimit.py     fixed-window limiter
│   │   ├── roman_urdu.py    Roman Urdu detection + transliteration check
│   │   ├── scripts.py       Unicode script classification
│   │   ├── security.py      bcrypt + JWT
│   │   ├── translator.py    orchestration
│   │   └── verify.py        the five axes
│   ├── api/                 auth, translate, history, conversation
│   ├── db/                  models, session
│   ├── static/              index.html, app.css, app.js
│   ├── deps.py              shared dependencies
│   ├── main.py              app, middleware, error handlers
│   └── schemas.py           request/response models
├── docs/                    setup, usage, api
├── tests/                   167 tests
├── ARCHITECTURE.md
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml
```

---

## Development

```bash
pytest                    # 167 tests
ruff check .              # lint
ruff format .             # format
ruff format --check .     # verify formatting
```

---

## License

MIT — see [LICENSE](LICENSE).

---

Built by **ABraz Baloch** as Day 26 of a 30-day AI engineering challenge.
Translation by [MyMemory](https://mymemory.translated.net).
