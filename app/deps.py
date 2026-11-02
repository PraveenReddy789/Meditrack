"""Shared state container and FastAPI dependencies (authentication + RBAC)."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable

from fastapi import Depends, Request

from app.cache import TTLCache
from app.config import Settings
from app.db import AppointmentRepository, Database
from app.errors import AuthenticationError, PermissionDeniedError
from app.ml.model import ModelService
from app.security import AuthService, AuthUser
from app.services.appointments import AppointmentService
from app.services.dashboard import DashboardService
from app.services.reports import ReportService

SESSION_COOKIE = "meditrack_session"


@dataclass
class AppState:
    settings: Settings
    db: Database
    appointments_repo: AppointmentRepository
    auth: AuthService
    model: ModelService
    cache: TTLCache
    appointments: AppointmentService
    dashboard: DashboardService
    reports: ReportService
    retrain_lock: threading.Lock = field(default_factory=threading.Lock)


def get_state(request: Request) -> AppState:
    return request.app.state.ctx


def current_user(request: Request, state: AppState = Depends(get_state)) -> AuthUser:
    user = state.auth.user_for_token(request.cookies.get(SESSION_COOKIE))
    if user is None:
        raise AuthenticationError("Sign in required.")
    return user


def require(permission: str) -> Callable[..., AuthUser]:
    """Dependency factory: the route runs only if the signed-in user holds `permission`."""

    def dependency(user: AuthUser = Depends(current_user)) -> AuthUser:
        if not user.can(permission):
            raise PermissionDeniedError("Your role does not allow this action.")
        return user

    return dependency
