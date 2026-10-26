from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.app.api.schemas.error_response import ErrorResponse
from backend.app.application.exceptions import ApplicationError
from backend.app.shared.logging_config import StructuredLogger, get_structured_logger


def _request_id(request: Request) -> str:
    # request_id ставится в middleware; здесь берём его для ответа и логов.
    return getattr(request.state, "request_id", "N/A")


async def _bind_error_context(
    slog: StructuredLogger,
    request: Request,
    *,
    status_code: int,
    exc: Exception,
):
    # Единый контекст ошибки для структурированного JSON-лога.
    return slog.logger.bind(
        request_id=_request_id(request),
        method=request.method,
        path=request.url.path,
        client_host=request.client.host if request.client else "unknown",
        client_port=request.client.port if request.client else "unknown",
        query_params=dict(request.query_params),
        path_params=dict(request.path_params),
        headers=slog.mask_headers(dict(request.headers)),
        cookies=slog.mask_cookies(dict(request.cookies)),
        body=await slog.safe_extract_body(request),
        content_type=request.headers.get("content-type", "N/A"),
        status_code=status_code,
        error_type=type(exc).__name__,
        error_message=str(exc),
    )


def register_exception_handlers(app: FastAPI) -> None:
    # Регистрируем обработчики по приоритету: доменные -> валидация -> fallback.
    @app.exception_handler(ApplicationError)
    async def application_error_handler(request: Request, exc: ApplicationError) -> JSONResponse:
        slog = get_structured_logger()
        bound_logger = await _bind_error_context(
            slog,
            request,
            status_code=exc.status_code,
            exc=exc,
        )
        bound_logger.warning(
            "Application error. path={} error_code={} message={}",
            request.url.path,
            exc.error_code,
            exc.message,
        )
        payload = ErrorResponse(
            error=exc.error_code,
            status_code=exc.status_code,
            message=exc.message,
            details=exc.details,
            request_id=_request_id(request),
        )
        return JSONResponse(status_code=exc.status_code, content=payload.model_dump())

    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        slog = get_structured_logger()
        safe_errors = jsonable_encoder(
            exc.errors(),
            custom_encoder={
                ValueError: lambda v: str(v),
                Exception: lambda e: str(e),
            },
        )
        bound_logger = await _bind_error_context(
            slog,
            request,
            status_code=422,
            exc=exc,
        )
        bound_logger.warning("Request validation failed. path={} errors={}", request.url.path, safe_errors)
        payload = ErrorResponse(
            error="request_validation_error",
            message="Request validation failed",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            details={"errors": safe_errors},
            request_id=_request_id(request),
        )
        return JSONResponse(status_code=422, content=payload.model_dump())

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        status_code = getattr(exc, 'status_code', status.HTTP_500_INTERNAL_SERVER_ERROR)
        slog = get_structured_logger()
        bound_logger = await _bind_error_context(
            slog,
            request,
            status_code=status_code,
            exc=exc,
        )
        bound_logger.exception("Unhandled exception. path={}", request.url.path)
        payload = ErrorResponse(
            error="internal_server_error",
            message="Internal server error",
            status_code=status_code,
            request_id=_request_id(request),
        )
        return JSONResponse(status_code=500, content=payload.model_dump())
