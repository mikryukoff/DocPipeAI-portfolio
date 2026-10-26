import asyncio
import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from loguru import logger
from starlette.requests import Request

import backend.app.shared.logging_config as logging_config
from backend.app.api.exception_handlers import register_exception_handlers
from backend.app.application.exceptions import (
    ApplicationError,
    ConflictError,
    EmptyUploadError,
    ImportAlreadyRunningError,
    JobNotFoundError,
    NotFoundError,
    PipelineNotFoundError,
    ValidationError,
)

TEST_EXCEPTIONS_LOGS_DIR = Path("data/logs/tests/exceptions")


@pytest.fixture(scope="module", autouse=True)
def configure_exception_tests_logging():
    old_logs_path = os.environ.get("LOGS_OUTPUT_PATH")
    old_data_base = os.environ.get("DATA_BASE_PATH")
    old_log_body = os.environ.get("LOG_BODY_ENABLED")
    old_verbose_http = os.environ.get("LOG_VERBOSE_HTTP")

    os.environ["LOGS_OUTPUT_PATH"] = str(TEST_EXCEPTIONS_LOGS_DIR)
    os.environ["DATA_BASE_PATH"] = str(TEST_EXCEPTIONS_LOGS_DIR)
    os.environ["LOG_BODY_ENABLED"] = "false"
    os.environ["LOG_VERBOSE_HTTP"] = "true"
    TEST_EXCEPTIONS_LOGS_DIR.mkdir(parents=True, exist_ok=True)

    logging_config._structured_logger = None
    logging_config.setup_logger()

    yield

    logger.complete()
    logging_config._structured_logger = None

    if old_logs_path is None:
        os.environ.pop("LOGS_OUTPUT_PATH", None)
    else:
        os.environ["LOGS_OUTPUT_PATH"] = old_logs_path

    if old_data_base is None:
        os.environ.pop("DATA_BASE_PATH", None)
    else:
        os.environ["DATA_BASE_PATH"] = old_data_base

    if old_log_body is None:
        os.environ.pop("LOG_BODY_ENABLED", None)
    else:
        os.environ["LOG_BODY_ENABLED"] = old_log_body

    if old_verbose_http is None:
        os.environ.pop("LOG_VERBOSE_HTTP", None)
    else:
        os.environ["LOG_VERBOSE_HTTP"] = old_verbose_http


def _make_request(app: FastAPI, request_id: str = "RID-TEST", headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/test",
        "raw_path": b"/test",
        "query_string": b"",
        "headers": headers or [],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
        "app": app,
    }
    request = Request(scope, receive)
    request.state.request_id = request_id
    return request


def test_application_error_handler_for_each_exception_type():
    app = FastAPI()
    register_exception_handlers(app)

    handler = app.exception_handlers[ApplicationError]
    request = _make_request(app, request_id="RID-123")

    cases = [
        (ApplicationError("base error", details={"x": 1}), 400, "application_error", "base error"),
        (NotFoundError("not found"), 404, "not_found", "not found"),
        (ConflictError("conflict"), 409, "conflict", "conflict"),
        (ValidationError("validation"), 422, "validation_error", "validation"),
        (JobNotFoundError(5), 404, "job_not_found", "id=5"),
        (PipelineNotFoundError("PIPE-1"), 404, "pipeline_not_found", "PIPE-1"),
        (EmptyUploadError(), 422, "empty_upload", "empty"),
        (ImportAlreadyRunningError(77), 409, "import_already_running", "already running"),
    ]

    for exc, status_code, error_code, msg_contains in cases:
        response = asyncio.run(handler(request, exc))
        payload = response.body.decode("utf-8")

        assert response.status_code == status_code
        assert f'"error":"{error_code}"' in payload
        assert msg_contains.lower() in payload.lower()
        assert '"request_id":"RID-123"' in payload


def test_request_validation_handler_returns_structured_payload():
    app = FastAPI()
    register_exception_handlers(app)

    handler = app.exception_handlers[RequestValidationError]
    request = _make_request(app, request_id="RID-VAL")
    exc = RequestValidationError(errors=[{"loc": ["query", "value"], "msg": "invalid", "type": "value_error"}])

    response = asyncio.run(handler(request, exc))
    payload = response.body.decode("utf-8")

    assert response.status_code == 422
    assert '"error":"request_validation_error"' in payload
    assert '"message":"Request validation failed"' in payload
    assert '"errors"' in payload
    assert '"request_id":"RID-VAL"' in payload


def test_unhandled_exception_handler_returns_500_with_request_id():
    app = FastAPI()
    register_exception_handlers(app)

    handler = app.exception_handlers[Exception]
    request = _make_request(app, request_id="RID-500")

    response = asyncio.run(handler(request, RuntimeError("boom")))
    payload = response.body.decode("utf-8")

    assert response.status_code == 500
    assert '"error":"internal_server_error"' in payload
    assert '"message":"Internal server error"' in payload
    assert '"details":{}' in payload
    assert '"request_id":"RID-500"' in payload


def test_exception_logs_written_to_separate_test_folder():
    logger.complete()

    log_files = sorted(TEST_EXCEPTIONS_LOGS_DIR.rglob("app*.jsonl"))
    assert log_files, f"No log files found in {TEST_EXCEPTIONS_LOGS_DIR}"

    content = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in log_files
        if path.exists() and path.stat().st_size > 0
    )

    assert content, f"Log files exist but are empty in {TEST_EXCEPTIONS_LOGS_DIR}"
    assert "Application error." in content
    assert "Unhandled exception." in content
    assert "Request validation failed" in content


def test_exception_logs_mask_cookie_values():
    app = FastAPI()
    register_exception_handlers(app)
    handler = app.exception_handlers[Exception]
    headers = [(b"cookie", b"access_token=secret-token; refresh_token=secret-refresh")]
    request = _make_request(app, request_id="RID-COOKIE", headers=headers)

    asyncio.run(handler(request, RuntimeError("boom-cookie")))
    logger.complete()

    log_files = sorted(TEST_EXCEPTIONS_LOGS_DIR.rglob("app*.jsonl"))
    content = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in log_files
        if path.exists() and path.stat().st_size > 0
    )
    assert "***MASKED***" in content
    assert "secret-token" not in content
    assert "secret-refresh" not in content
