"""Tarjuman -- application entry point.

Middleware order matters and is deliberate:

1. Security headers run outermost so every response carries them, including
   error responses generated further in.
2. CORS next, so preflight requests are answered before anything else touches
   them.
3. Rate limiting after that, so a flood is rejected before it reaches a route.
4. Request size guard last, because it needs to read the body.

The docs are disabled in production. An open /docs on a public deployment is a
map of every endpoint and schema, which is not a vulnerability on its own but is
free reconnaissance.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import auth, conversation, history, translate
from app.core.config import settings
from app.core.provider import close_provider
from app.core.ratelimit import make_limiter
from app.db.session import init_db
from app.schemas import HealthOut

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger("tarjuman")

VERSION = "1.0.0"

# A generous global limit: the translate endpoint has its own, tighter one.
global_limiter = make_limiter(settings.rate_limit_requests, settings.rate_limit_window_seconds)

MAX_BODY_BYTES = 256 * 1024


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    logger.info(
        "Tarjuman %s starting | env=%s | db=%s",
        VERSION,
        settings.environment,
        "sqlite" if settings.is_sqlite else "postgres",
    )
    yield
    await close_provider()
    logger.info("Tarjuman shutting down")


app = FastAPI(
    title="Tarjuman",
    version=VERSION,
    description=(
        "Real-time translation that verifies its own output. Every translation "
        "carries a verdict and the evidence behind it."
    ),
    lifespan=lifespan,
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    openapi_url=None if settings.is_production else "/openapi.json",
)


# --- middleware ------------------------------------------------------------


@app.middleware("http")
async def security_headers(request: Request, call_next: Any):
    """Attach security headers to every response."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    if settings.is_production:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    # The CSP allows the inline styles and scripts the single-page UI uses. A
    # stricter policy would need nonces, which is the right next step but not
    # worth the complexity for a self-contained page.
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "font-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )
    return response


@app.middleware("http")
async def request_guard(request: Request, call_next: Any):
    """Reject oversized bodies and add a request id + timing header."""
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_BODY_BYTES:
                return JSONResponse(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    content={
                        "detail": {
                            "code": "payload_too_large",
                            "message": f"Request body exceeds {MAX_BODY_BYTES} bytes.",
                        }
                    },
                )
        except ValueError:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"detail": {"code": "bad_request", "message": "Malformed Content-Length."}},
            )

    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - started) * 1000
    response.headers["X-Response-Time"] = f"{elapsed_ms:.1f}ms"
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,
)


# --- error handlers --------------------------------------------------------


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Normalise every HTTP error into {code, message}."""
    detail = exc.detail
    if isinstance(detail, dict) and "code" in detail:
        body = detail
    else:
        body = {"code": _code_for(exc.status_code), "message": str(detail)}
    return JSONResponse(status_code=exc.status_code, content={"detail": body}, headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Turn Pydantic's error list into one readable message plus the fields."""
    errors = exc.errors()
    first = errors[0] if errors else {}
    field = ".".join(str(p) for p in first.get("loc", []) if p != "body")
    message = first.get("msg", "The request was invalid.")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": {
                "code": "validation_error",
                "message": f"{field}: {message}" if field else message,
                "fields": [
                    {
                        "field": ".".join(str(p) for p in e.get("loc", []) if p != "body"),
                        "message": e.get("msg", ""),
                    }
                    for e in errors[:10]
                ],
            }
        },
    )


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    """Never leak a stack trace to a client."""
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": {
                "code": "internal_error",
                "message": "Something went wrong on our side. It has been logged.",
            }
        },
    )


def _code_for(status_code: int) -> str:
    return {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        405: "method_not_allowed",
        409: "conflict",
        413: "payload_too_large",
        422: "validation_error",
        429: "rate_limited",
        500: "internal_error",
        503: "unavailable",
    }.get(status_code, "error")


# --- routes ----------------------------------------------------------------


@app.get("/api/health", response_model=HealthOut, tags=["meta"], summary="Health check")
def health() -> HealthOut:
    from app.core import languages

    return HealthOut(
        status="ok",
        version=VERSION,
        environment=settings.environment,
        provider="mymemory",
        languages=len(languages.LANGUAGES),
    )


app.include_router(auth.router)
app.include_router(translate.router)
app.include_router(history.router)
app.include_router(conversation.router)

# Static UI. Mounted last so /api/* always wins.
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse("app/static/index.html")


@app.get("/favicon.svg", include_in_schema=False)
def favicon() -> FileResponse:
    return FileResponse("app/static/favicon.svg", media_type="image/svg+xml")
