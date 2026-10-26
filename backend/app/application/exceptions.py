from fastapi import status


class ApplicationError(Exception):
    """Base application-level exception with stable error code."""

    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "application_error"

    def __init__(self, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(ApplicationError):
    status_code = status.HTTP_404_NOT_FOUND
    error_code = "not_found"


class ConflictError(ApplicationError):
    status_code = status.HTTP_409_CONFLICT
    error_code = "conflict"


class ValidationError(ApplicationError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    error_code = "validation_error"


class UnauthorizedError(ApplicationError):
    status_code = status.HTTP_401_UNAUTHORIZED
    error_code = "unauthorized"


class ForbiddenError(ApplicationError):
    status_code = status.HTTP_403_FORBIDDEN
    error_code = "forbidden"


class TooManyRequestsError(ApplicationError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    error_code = "too_many_requests"


class JobNotFoundError(NotFoundError):
    error_code = "job_not_found"

    def __init__(self, job_id: int):
        super().__init__(f"Job with id={job_id} not found", details={"job_id": job_id})


class PipelineNotFoundError(NotFoundError):
    error_code = "pipeline_not_found"

    def __init__(self, pipeline_name: str):
        super().__init__(
            f"Pipeline '{pipeline_name}' not found",
            details={"pipeline_name": pipeline_name},
        )


class EmptyUploadError(ValidationError):
    error_code = "empty_upload"

    def __init__(self):
        super().__init__("Uploaded file is empty")


class ImportAlreadyRunningError(ConflictError):
    error_code = "import_already_running"

    def __init__(self, job_id: int):
        super().__init__(
            "Import is already running",
            details={"active_job_id": job_id},
        )


class DemoLimitExceededError(ForbiddenError):
    error_code = "demo_limit_exceeded"

    def __init__(self, *, limit: int, period_days: int):
        super().__init__(
            "Demo download limit exceeded",
            details={"limit": limit, "period_days": period_days},
        )
