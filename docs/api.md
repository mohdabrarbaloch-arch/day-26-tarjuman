# API reference

Base URL: `http://127.0.0.1:8000`

All request and response bodies are JSON. Authenticated endpoints take a bearer
token: `Authorization: Bearer <token>`.

Interactive docs are at `/docs` in development. They are **disabled** when
`APP_ENV=production`.

---

## Errors

Every error has the same shape:

```json
{
  "detail": "Human-readable message.",
  "code": "machine_readable_code"
}
```

| Status | When |
|---|---|
| `400` | Malformed request, or source and target are the same language |
| `401` | Missing, expired, or invalid token |
| `404` | Not found — **or** it exists but belongs to someone else |
| `409` | Email already registered |
| `413` | Request body over `MAX_REQUEST_BYTES` |
| `422` | Validation failed (Pydantic) |
| `429` | Rate limit hit, or provider quota exhausted |
| `502` | Provider returned an error or unparseable response |
| `503` | Provider unreachable after retries |

**Ownership returns 404, not 403.** Asking for another user's record tells you
nothing about whether it exists. This is deliberate.

---

## Health

### `GET /api/health`

No auth. Used by the Docker healthcheck.

```json
{
  "status": "ok",
  "version": "1.0.0",
  "languages": 25,
  "provider": "mymemory"
}
```

---

## Languages

### `GET /api/languages`

No auth. The full supported set, with script and direction so the UI can render
RTL correctly.

```json
{
  "languages": [
    {
      "code": "ur",
      "name": "Urdu",
      "native_name": "اردو",
      "script": "arabic",
      "rtl": true
    }
  ],
  "count": 25
}
```

---

## Auth

### `POST /api/auth/register`

```json
{ "email": "you@example.com", "password": "at-least-8-chars" }
```

`201` on success:

```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "user": { "id": 1, "email": "you@example.com", "created_at": "..." }
}
```

`409` if the email is taken. Passwords are bcrypt-hashed; the plaintext is never
stored or logged.

### `POST /api/auth/login`

Same body, same response shape. `401` on bad credentials — the message does not
distinguish "no such user" from "wrong password", so the endpoint cannot be used
to enumerate accounts.

### `GET /api/auth/me`

Auth required. Returns the current user.

---

## Translate

### `POST /api/translate`

Auth optional. Signed-in users get the result saved to history automatically.

```json
{
  "text": "Please send the invoice by Friday.",
  "source_lang": "en",
  "target_lang": "ur",
  "save": true
}
```

| Field | Type | Notes |
|---|---|---|
| `text` | string | 1 to `MAX_TEXT_LENGTH` (default 5,000) |
| `source_lang` | string | A language code, or `"auto"` |
| `target_lang` | string | A language code. Must differ from the resolved source |
| `save` | bool | Default `true`. Ignored when signed out |

Response:

```json
{
  "id": 12,
  "source_text": "Please send the invoice by Friday.",
  "translated_text": "براہ کرم جمعہ تک رسید بھیج دیں۔",
  "source_lang": "en",
  "target_lang": "ur",
  "detected_lang": "en",
  "roman_urdu": false,
  "verdict": "verified",
  "confidence": 1.0,
  "summary": "Every check passed.",
  "findings": [
    {
      "axis": "script",
      "severity": "ok",
      "score": 1.0,
      "detail": "100% of the output is arabic script, as Urdu requires."
    }
  ],
  "chunks": [
    { "index": 0, "verdict": "verified", "confidence": 1.0 }
  ],
  "provider": "mymemory",
  "cached": false,
  "elapsed_ms": 412
}
```

**`verdict`** is one of `verified`, `likely`, `uncertain`, `failed`.

**`findings`** always contains all five axes, including skipped ones — a skipped
axis appears with `severity: "skipped"` and is excluded from `confidence`. It is
never reported as a pass.

**`chunks`** is present only when the text was split. If any chunk failed, the
document verdict is `failed` regardless of the others.

### Rate limiting

`RATE_LIMIT_REQUESTS` per `RATE_LIMIT_WINDOW_SECONDS` per client IP (default 30
per 60s). Over the limit returns `429` with a `Retry-After` header.

The limiter is per-process. Behind N workers the effective limit is N× the
configured value. See [ARCHITECTURE.md](../ARCHITECTURE.md#scaling-notes).

---

## History

All endpoints require auth and are scoped to the caller.

### `GET /api/history`

| Query | Type | Default | Notes |
|---|---|---|---|
| `limit` | int | 20 | 1–100 |
| `offset` | int | 0 | |
| `verdict` | string | — | Filter by verdict |
| `favourite` | bool | — | Only favourites |

```json
{
  "items": [ { "id": 12, "source_text": "...", "verdict": "verified", "...": "..." } ],
  "total": 34,
  "limit": 20,
  "offset": 0
}
```

### `PATCH /api/history/{id}/favourite`

```json
{ "favourite": true }
```

Returns the updated record. `404` if it is not yours.

### `DELETE /api/history/{id}`

`204` on success. `404` if it is not yours.

---

## Conversation mode

All endpoints require auth.

### `POST /api/conversations`

```json
{ "lang_a": "en", "lang_b": "ur", "title": "Clinic visit" }
```

`201` with the session, including an empty `turns` array.

### `POST /api/conversations/{id}/turns`

```json
{ "text": "Where does it hurt?", "speaker": "a" }
```

The turn is translated from the speaker's language into the other one, verified,
and appended. The response includes the turn with its own verdict:

```json
{
  "id": 7,
  "speaker": "a",
  "original": "Where does it hurt?",
  "translated": "کہاں درد ہے؟",
  "verdict": "verified",
  "confidence": 1.0,
  "next_speaker": "b"
}
```

`next_speaker` is what the UI should switch to. A failed turn is stored with
`verdict: "failed"` and shown flagged — it is not silently dropped.

### `GET /api/conversations`

List your sessions, newest first.

### `GET /api/conversations/{id}`

Full transcript with every turn and its verdict.

### `DELETE /api/conversations/{id}`

`204`. `404` if it is not yours.

---

## Stats

### `GET /api/stats`

No auth. Operational visibility.

```json
{
  "provider": "mymemory",
  "cache": { "entries": 42, "max_entries": 2000, "ttl_seconds": 3600 },
  "languages": 25,
  "version": "1.0.0"
}
```

---

## Security headers

Every response carries:

```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: strict-origin-when-cross-origin
Content-Security-Policy: default-src 'self'; ...
Permissions-Policy: geolocation=(), microphone=(), camera=()
```

CSP allows `'self'` only. There is no inline script and no CDN — the whole
front-end is three local files, which is why a strict policy is possible.

---

## Examples

### Translate and read the verdict

```bash
curl -s -X POST http://127.0.0.1:8000/api/translate \
  -H 'Content-Type: application/json' \
  -d '{"text":"Please send the invoice by Friday.","source_lang":"en","target_lang":"ur"}' \
  | python -m json.tool
```

### The transliteration trap

```bash
curl -s -X POST http://127.0.0.1:8000/api/translate \
  -H 'Content-Type: application/json' \
  -d '{"text":"Aaj mausam bohat acha hai","source_lang":"ur","target_lang":"en"}' \
  | python -m json.tool
```

Expect `"verdict": "failed"` with the transliteration axis at `0.0`. If you get
`verified`, the provider has started translating Roman Urdu properly — check the
output text before trusting the badge.

### Register, translate, read history

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"me@example.com","password":"hunter2hunter2"}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -s -X POST http://127.0.0.1:8000/api/translate \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"text":"Good morning","source_lang":"en","target_lang":"ur"}'

curl -s http://127.0.0.1:8000/api/history -H "Authorization: Bearer $TOKEN"
```
