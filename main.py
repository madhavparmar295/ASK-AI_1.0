from dotenv import load_dotenv

load_dotenv()

import logging
import os
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from database import Base, engine
from grievance_app.api import (
    bootstrap as grievance_bootstrap,
    build_api_router as build_grievance_router,
    service_error_handler as grievance_service_error_handler,
    start_watchdog as start_grievance_watchdog,
)
from grievance_app.services.errors import ServiceError as GrievanceServiceError
from models import AnswerFeedback  # noqa: F401  registered so create_all builds its table
from routers import (
    auth,
    chat_history,
    feedback,
    gmail_webhook,
    grievance_bridge,
    query,
    upload,
    user_auth,
    website,
)
from services.health import readiness_report
from services.logging_config import (
    RequestContextMiddleware,
    configure_logging,
    log_event,
)
from services.postgres import init_db

APP_VERSION = os.getenv("APP_VERSION", "2.0")
REQUIRE_DATABASE = os.getenv("REQUIRE_DATABASE", "false").lower() in ("1", "true", "yes")

configure_logging()
_logger = logging.getLogger("askai.startup")


def _warm_retrieval() -> None:
    """Pay the first-call cost of the hosted embedding before a student asks anything.

    The first query after a restart measured ~4.9 s against ~0.9 s warm, which was
    enough on its own to push the grievance hint (and the chat's first answer) past its
    deadline. One tiny embedding call per process removes that spike.
    """
    try:
        from services.embeddings import embed_query

        embed_query("warm up")
        log_event(_logger, "retrieval_warm")
    except Exception as exc:      # no key, no network, no index: not fatal
        log_event(_logger, "retrieval_warm_failed", level=logging.INFO, error=str(exc)[:160])


def _cors_origins() -> list[str]:
    raw = os.getenv("CORS_ALLOW_ORIGINS", "*")
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    return origins or ["*"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    started = time.time()
    try:
        # Two separate schemas: init_db() is the pgvector-side migration and needs
        # PostgreSQL, while the SQLAlchemy models (users, chat history, feedback) work on
        # any SQLAlchemy URL. Keeping them apart means a SQLite deployment still gets its
        # tables instead of inheriting a failure from the pgvector step.
        try:
            init_db()
        except Exception as exc:
            log_event(
                _logger,
                "pgvector_init_skipped",
                level=logging.INFO,
                error=str(exc)[:200],
                hint="document vectors live in Pinecone; these tables are legacy",
            )

        Base.metadata.create_all(bind=engine)
        log_event(
            _logger,
            "startup_complete",
            database="ready",
            seconds=round(time.time() - started, 2),
        )
    except Exception as exc:
        # Mail ingestion and retrieval now run entirely on Pinecone, so a database
        # outage must not stop the service booting. Set REQUIRE_DATABASE=true to make
        # it fatal instead.
        if REQUIRE_DATABASE:
            raise
        log_event(
            _logger,
            "startup_degraded",
            level=logging.WARNING,
            error=str(exc)[:200],
            hint="users, chat history and feedback will fail until the database is reachable",
        )

    # The grievance side owns its own database and its own sign-in, so it is prepared
    # separately: a failure here leaves the chat working and only the grievance pages
    # degraded, which is the right way round.
    try:
        grievance_bootstrap()
        log_event(_logger, "grievance_tables_ready")
    except Exception as exc:
        log_event(
            _logger,
            "grievance_startup_degraded",
            level=logging.WARNING,
            error=str(exc)[:200],
            hint="the /api/grievance routes stay down until GRIEVANCE_DATABASE_URL is reachable",
        )

    watchdog_stop = threading.Event()
    start_grievance_watchdog(watchdog_stop)

    if (
        os.getenv("WARMUP_ON_STARTUP", "true").lower() not in ("0", "false", "no")
        and os.getenv("ENVIRONMENT", "").lower() != "test"
    ):
        threading.Thread(target=_warm_retrieval, daemon=True, name="retrieval-warmup").start()

    yield

    watchdog_stop.set()
    log_event(_logger, "shutdown_complete")


app = FastAPI(
    title="ASK-AI 2.0",
    description="AI-powered email & document Q&A system",
    version=APP_VERSION,
    lifespan=lifespan,
)

_origins = _cors_origins()
_wildcard = "*" in _origins

if _wildcard:
    log_event(
        _logger,
        "cors_wildcard",
        level=logging.WARNING,
        hint="set CORS_ALLOW_ORIGINS to your frontend origin before going live",
    )

# The request logger is added first so it wraps everything; CORS is added after it,
# so preflight requests are answered before they reach the application.
app.add_middleware(RequestContextMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    # Browsers reject a wildcard origin together with credentials, so credentials are
    # only enabled when the allowed origins are explicit.
    allow_credentials=not _wildcard,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)


@app.get("/health", tags=["Health"])
def health():
    """Liveness: never touches an external dependency."""
    return {
        "status": "ok",
        "version": APP_VERSION,
        "environment": os.getenv("ENVIRONMENT", "development"),
    }


@app.get("/health/ready", tags=["Health"])
def readiness(response: Response):
    """Readiness: reports Pinecone, database and Redis status."""
    report = readiness_report()
    if not report["ready"]:
        response.status_code = 503
    return report


# Grievance system: the student portal's case workflow, notifications and admin API.
app.include_router(build_grievance_router())
app.add_exception_handler(GrievanceServiceError, grievance_service_error_handler)

app.include_router(auth.router)
app.include_router(user_auth.router)
app.include_router(grievance_bridge.router)
app.include_router(chat_history.router)
app.include_router(feedback.router)
app.include_router(gmail_webhook.router)
app.include_router(query.router)
app.include_router(upload.router)
app.include_router(website.router)
