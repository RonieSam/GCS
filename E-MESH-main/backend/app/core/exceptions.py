"""
Custom exception classes and FastAPI exception handlers.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import Request, status
from fastapi.responses import JSONResponse


# ── Domain exceptions ─────────────────────────────────────────────────────────

class EMeshException(Exception):
    """Base class for all E-Mesh application exceptions."""

    def __init__(
        self,
        message: str,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail: Optional[Any] = None,
    ) -> None:
        self.message = message
        self.status_code = status_code
        self.detail = detail
        super().__init__(message)


class NotFoundError(EMeshException):
    def __init__(self, resource: str, resource_id: Any = None) -> None:
        msg = f"{resource} not found"
        if resource_id is not None:
            msg = f"{resource} '{resource_id}' not found"
        super().__init__(msg, status.HTTP_404_NOT_FOUND)


class AlreadyExistsError(EMeshException):
    def __init__(self, resource: str, identifier: Any = None) -> None:
        msg = f"{resource} already exists"
        if identifier is not None:
            msg = f"{resource} '{identifier}' already exists"
        super().__init__(msg, status.HTTP_409_CONFLICT)


class AuthenticationError(EMeshException):
    def __init__(self, message: str = "Authentication failed") -> None:
        super().__init__(message, status.HTTP_401_UNAUTHORIZED)


class AuthorizationError(EMeshException):
    def __init__(self, message: str = "Insufficient permissions") -> None:
        super().__init__(message, status.HTTP_403_FORBIDDEN)


class ValidationError(EMeshException):
    def __init__(self, message: str, detail: Optional[Any] = None) -> None:
        super().__init__(message, status.HTTP_422_UNPROCESSABLE_ENTITY, detail)


class RateLimitError(EMeshException):
    def __init__(self, message: str = "Rate limit exceeded") -> None:
        super().__init__(message, status.HTTP_429_TOO_MANY_REQUESTS)


class SOSCooldownError(EMeshException):
    def __init__(self, seconds_remaining: int) -> None:
        super().__init__(
            f"SOS cooldown active. Please wait {seconds_remaining} seconds before sending another SOS.",
            status.HTTP_429_TOO_MANY_REQUESTS,
            {"seconds_remaining": seconds_remaining},
        )


# ── Exception handlers ────────────────────────────────────────────────────────

def _error_response(status_code: int, message: str, detail: Any = None) -> JSONResponse:
    body: Dict[str, Any] = {"success": False, "message": message}
    if detail is not None:
        body["detail"] = detail
    return JSONResponse(status_code=status_code, content=body)


async def emesh_exception_handler(request: Request, exc: EMeshException) -> JSONResponse:
    return _error_response(exc.status_code, exc.message, exc.detail)


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Never expose internal details in production
    return _error_response(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "An unexpected error occurred. Please try again.",
    )
