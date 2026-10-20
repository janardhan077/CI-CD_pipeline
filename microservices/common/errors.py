"""
Uniform error handling, shared by every microservice.

Kept identical to the monolith's mapping so client behavior (status
codes, error body shape) doesn't change just because the code moved
into separate processes.
"""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from common.core.exceptions import (
    InOnError, ValidationError, NotFoundError, InsufficientStockError,
    AmbiguousCommandError, ConfirmationRequiredError, UpstreamServiceError,
)

_ERROR_STATUS = {
    ValidationError: 400,
    NotFoundError: 404,
    InsufficientStockError: 409,
    AmbiguousCommandError: 422,
    ConfirmationRequiredError: 428,
    UpstreamServiceError: 502,
}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(InOnError)
    def handle_inon_error(request: Request, exc: InOnError):
        status_code = _ERROR_STATUS.get(type(exc), 400)
        return JSONResponse(
            status_code=status_code,
            content={"error": type(exc).__name__, "detail": str(exc)},
        )
