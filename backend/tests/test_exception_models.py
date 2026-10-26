import pytest

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
from backend.app.domain.exceptions import (
    DomainError,
    InvalidPipelineDataError,
    PipelineParseError,
    TableExtractionError,
)


def test_application_error_base_fields():
    exc = ApplicationError("boom", details={"a": 1})
    assert exc.status_code == 400
    assert exc.error_code == "application_error"
    assert exc.message == "boom"
    assert exc.details == {"a": 1}


@pytest.mark.parametrize(
    ("exc", "status_code", "error_code", "message_substring"),
    [
        (NotFoundError("not found"), 404, "not_found", "not found"),
        (ConflictError("conflict"), 409, "conflict", "conflict"),
        (ValidationError("invalid"), 422, "validation_error", "invalid"),
        (JobNotFoundError(42), 404, "job_not_found", "id=42"),
        (
            PipelineNotFoundError("P-100"),
            404,
            "pipeline_not_found",
            "P-100",
        ),
        (EmptyUploadError(), 422, "empty_upload", "empty"),
        (
            ImportAlreadyRunningError(7),
            409,
            "import_already_running",
            "already running",
        ),
    ],
)
def test_application_exception_variants(exc, status_code, error_code, message_substring):
    assert isinstance(exc, ApplicationError)
    assert exc.status_code == status_code
    assert exc.error_code == error_code
    assert message_substring.lower() in exc.message.lower()


def test_job_not_found_error_details():
    exc = JobNotFoundError(123)
    assert exc.details == {"job_id": 123}


def test_pipeline_not_found_error_details():
    exc = PipelineNotFoundError("PIPE-1")
    assert exc.details == {"pipeline_name": "PIPE-1"}


def test_import_already_running_error_details():
    exc = ImportAlreadyRunningError(9)
    assert exc.details == {"active_job_id": 9}


@pytest.mark.parametrize(
    "exc_cls",
    [DomainError, PipelineParseError, TableExtractionError, InvalidPipelineDataError],
)
def test_domain_exceptions_inheritance(exc_cls):
    exc = exc_cls("domain problem")
    assert isinstance(exc, DomainError)
    assert str(exc) == "domain problem"
