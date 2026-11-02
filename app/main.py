"""Application factory."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.cache import TTLCache
from app.config import Settings
from app.db import AppointmentRepository, Database, SessionRepository, UserRepository
from app.deps import AppState
from app.errors import AppError
from app.ml.model import ModelService
from app.routers import appointments, auth, model, reports
from app.security import AuthService, LoginThrottle, bootstrap_users
from app.services.appointments import AppointmentService
from app.services.dashboard import DashboardService
from app.services.reports import ReportService

log = logging.getLogger("meditrack")
STATIC_DIR = Path(__file__).parent / "static"

# Scripts and styles are served from our own origin only; nothing inline, nothing third-party.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)


def build_state(settings: Settings) -> AppState:
    db = Database(settings.db_path)
    db.init_schema()
    users, sessions, repo = UserRepository(db), SessionRepository(db), AppointmentRepository(db)
    bootstrap_users(users, settings)

    cache = TTLCache(settings.cache_ttl_seconds, settings.cache_max_entries)
    model_service = ModelService(settings, repo)
    model_service.train()
    dashboard = DashboardService(repo, model_service)
    return AppState(
        settings=settings,
        db=db,
        appointments_repo=repo,
        auth=AuthService(
            users, sessions, settings, LoginThrottle(settings.login_max_failures, settings.login_window_seconds)
        ),
        model=model_service,
        cache=cache,
        appointments=AppointmentService(repo, model_service, cache),
        dashboard=dashboard,
        reports=ReportService(repo, dashboard),
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.ctx = build_state(settings)
        yield

    app = FastAPI(title="MediTrack", version="1.0.0", lifespan=lifespan)

    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError):
        return JSONResponse({"detail": exc.message}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError):
        # Drop the echoed `input` so a rejected password or other secret is never reflected back.
        errors = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
        return JSONResponse({"detail": errors}, status_code=422)

    @app.exception_handler(Exception)
    async def unhandled_handler(_: Request, exc: Exception):
        log.exception("unhandled error")
        return JSONResponse({"detail": "Internal server error."}, status_code=500)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"  # patient data must not sit in browser caches
        return response

    @app.get("/api/health", tags=["meta"])
    def health(request: Request):
        return {"status": "ok", "model_version": request.app.state.ctx.model.info.version}

    app.include_router(auth.router)
    app.include_router(appointments.router)
    app.include_router(reports.router)
    app.include_router(model.router)

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


def get_app() -> FastAPI:
    """Entry point for `uvicorn app.main:get_app --factory`."""
    return create_app()
