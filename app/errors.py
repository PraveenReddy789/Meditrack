"""Domain errors that map cleanly onto HTTP responses."""
from __future__ import annotations


class AppError(Exception):
    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NotFoundError(AppError):
    status_code = 404


class ConflictError(AppError):
    status_code = 409


class AuthenticationError(AppError):
    status_code = 401


class PermissionDeniedError(AppError):
    status_code = 403


class TooManyAttemptsError(AppError):
    status_code = 429


class ValidationFailedError(AppError):
    status_code = 422
