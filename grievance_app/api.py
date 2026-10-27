"""Mountable form of the grievance API.

The grievance service started life as its own FastAPI application (`main.create_app`).
This module exposes the same routes as a router, so the chatbot's API process can host
them at `/api/grievance` without running a second server:

    from grievance_app.api import build_api_router, bootstrap, service_error_handler
    app.include_router(build_api_router())
    app.add_exception_handler(ServiceError, service_error_handler)

`main.py` still builds a standalone app from the same pieces, so the service can also be
run on its own (`uvicorn grievance_app.main:app`).
"""

import logging
import threading

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .auth.routes import me_router, router as auth_router
from .config import get_settings
from .routers import (
    admin_config,
    admin_ops,
    attachments,
    classify,
    issues,
    meta,
    notifications,
    staff,
)
from .security.csrf import csrf_protect
from .services.errors import ServiceError

_logger = logging.getLogger("grievance.api")


def build_api_router() -> APIRouter:
    """Every grievance route, under the configured prefix, with CSRF protection."""
    settings = get_settings()
    api = APIRouter(prefix=settings.api_prefix, dependencies=[Depends(csrf_protect)])
    api.include_router(auth_router)
    api.include_router(me_router)
    api.include_router(issues.router)
    api.include_router(attachments.router)
    api.include_router(staff.router)
    api.include_router(classify.router)
    api.include_router(meta.router)
    api.include_router(notifications.router)
    api.include_router(admin_config.router)
    api.include_router(admin_ops.router)

    @api.get("/health")
    def grievance_health():
        return {"status": "ok"}

    @api.head("/health", include_in_schema=False)       # load balancers often probe with HEAD
    def grievance_health_head():
        return {"status": "ok"}

    return api


async def service_error_handler(request: Request, exc: ServiceError) -> JSONResponse:
    """A business-rule error becomes a JSON response with its own status (409, 422, ...)."""
    return JSONResponse(status_code=exc.status, content={"detail": exc.detail, **exc.extra})


def bootstrap(create_tables: bool | None = None) -> None:
    """Validate the production settings and, when asked, create the tables.

    Safe to call from a startup hook: a database that is down is logged and skipped
    when `GRIEVANCE_AUTO_CREATE_TABLES` permits it, so the chatbot still boots.
    """
    settings = get_settings()
    settings.validate_for_runtime()
    if create_tables is None:
        create_tables = settings.auto_create_tables
    if not create_tables:
        return
    from . import models  # noqa: F401  (registers the tables on the metadata)
    from .db import Base, engine

    Base.metadata.create_all(bind=engine)
    _logger.info("grievance tables ready", extra={"database": engine.url.render_as_string(hide_password=True)})


def watchdog_loop(stop: threading.Event) -> None:
    """Check every 5 minutes that the grievance worker is alive; email the admin once if not."""
    from .db import SessionLocal
    from .services.scheduler import check_heartbeat

    while not stop.wait(300):
        try:
            with SessionLocal() as db:
                check_heartbeat(db)
        except Exception:
            _logger.exception("watchdog check failed")


def start_watchdog(stop: threading.Event) -> threading.Thread | None:
    """Start the worker watchdog when it is configured and not already running."""
    if not get_settings().watchdog_enabled:
        return None
    thread = threading.Thread(target=watchdog_loop, args=(stop,), daemon=True, name="grievance-watchdog")
    thread.start()
    return thread
