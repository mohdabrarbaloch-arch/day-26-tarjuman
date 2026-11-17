# Setup

## Requirements

- Python 3.11 or newer
- pip
- Optional: Docker, if you'd rather not install anything locally

No API key is required. The default provider (MyMemory) has a free endpoint that
needs no authentication, which is deliberate — the project should run for anyone
who clones it.

## Local install

```bash
git clone https://github.com/mohdabrarbaloch-arch/day-26-tarjuman.git
cd day-26-tarjuman

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -e ".[dev]"
```

`[dev]` pulls in pytest, ruff and httpx. If you only want to run the app:

```bash
pip install -e .
```

## Configure

```bash
cp .env.example .env
```

Every value in `.env.example` has a working default, so an empty `.env` boots
fine. The one you should set before deploying:

```bash
python -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(48))" >> .env
```

If you leave `SECRET_KEY` at its default and set `APP_ENV=production`, the app
**refuses to start**. That is intentional — a default signing key in production
means anyone can mint a valid token.

## Run

```bash
uvicorn app.main:app --reload
```

Open **http://127.0.0.1:8000**.

The database is created automatically on first boot. With no `DATABASE_URL` set,
it's SQLite at `./tarjuman.db`.

## Docker

```bash
docker compose up --build
```

Brings up the app on port 8000 with PostgreSQL 16 behind it. The app waits for
the database healthcheck before starting.

To set a real secret:

```bash
SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(48))") \
  docker compose up --build
```

## PostgreSQL without Docker

```bash
pip install -e ".[postgres]"

export DATABASE_URL="postgresql+psycopg://user:pass@localhost:5432/tarjuman"
uvicorn app.main:app --reload
```

Tables are created on startup. There are no migrations yet — see
[ARCHITECTURE.md](../ARCHITECTURE.md#scaling-notes) for why, and when to add
Alembic.

## Verifying the install

```bash
pytest                    # 167 tests, no network needed
ruff check .              # lint
ruff format --check .     # formatting
```

Then check the app is alive:

```bash
curl http://127.0.0.1:8000/api/health
```

You should get `{"status":"ok",...}` with a language count.

## Troubleshooting

**`429 quota_exceeded` from the translate endpoint**
MyMemory's free tier is limited per IP per day. Wait, or set `MYMEMORY_EMAIL` in
`.env` to a registered address for a larger allowance. The error is surfaced
honestly rather than swallowed — that's the point of the project.

**`SECRET_KEY is still the development default`**
You set `APP_ENV=production` without changing the key. Generate one as shown
above.

**Port 8000 already in use**
`uvicorn app.main:app --port 8001`

**`ModuleNotFoundError: app`**
You're not in the project root, or the venv isn't active. `pip install -e .`
registers the package; run it from the directory containing `pyproject.toml`.

**Tests fail with a database error**
Tests use an in-memory SQLite database and never touch your real one. If they
fail, check that `pytest` is running from the project root so `conftest.py` is
picked up.
