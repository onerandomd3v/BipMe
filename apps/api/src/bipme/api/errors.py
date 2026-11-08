"""Stable structured HTTP errors without leaking internal exception details."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(Exception):
    """Expected API failure with a stable public code and safe message."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message


def _error_response(
    status_code: int,
    code: str,
    message: str,
    fields: list[dict[str, str]] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "fields": fields}},
    )


def install_error_handlers(app: FastAPI) -> None:
    """Expose validation, HTTP and application failures through one response envelope."""

    @app.exception_handler(ApiError)
    async def api_error_handler(_request: Request, exc: ApiError) -> JSONResponse:
        return _error_response(exc.status_code, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        fields: list[dict[str, str]] = []
        for error in exc.errors():
            location = ".".join(str(part) for part in error.get("loc", ()))
            fields.append({"field": location, "code": str(error.get("type", "invalid"))})
        return _error_response(422, "invalid_request", "Request validation failed.", fields)

    @app.exception_handler(HTTPException)
    async def http_error_handler(_request: Request, exc: HTTPException) -> JSONResponse:
        code, message = _http_error(exc.status_code)
        return _error_response(exc.status_code, code, message)


def _http_error(status_code: int) -> tuple[str, str]:
    messages: dict[int, tuple[str, str]] = {
        401: ("authentication_required", "Authentication is required."),
        403: ("creator_not_authorized", "This creator is not authorized."),
        404: ("not_found", "The requested resource was not found."),
    }
    return messages.get(status_code, ("request_failed", "The request could not be completed."))
