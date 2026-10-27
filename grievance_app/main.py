"""Standalone grievance API.

Run it on its own with:

    uvicorn grievance_app.main:app --reload --port 8000

In the combined product this process is not needed: the chatbot's API imports
`grievance_app.api.build_api_router()` and serves the same routes under /api/grievance.
Keeping this module means the grievance system can still be deployed alone.
"""

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import bootstrap, build_api_router, service_error_handler, start_watchdog
from .config import get_settings
from .services.errors import ServiceError


def create_app() -> FastAPI:
    settings = get_settings()
    settings.validate_for_runtime()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        stop = threading.Event()
        try:
            bootstrap()
        except Exception:                      # an unreachable database must not stop the API booting
            logging.getLogger("grievance.api").exception("could not prepare the grievance tables")
        start_watchdog(stop)
        yield
        stop.set()

    app = FastAPI(
        lifespan=lifespan,
        title="College Grievance API",
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )
    if settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["Content-Type", "X-CSRF-Token"],
        )

    app.include_router(build_api_router())
    app.add_exception_handler(ServiceError, service_error_handler)
    return app


app = create_app()
