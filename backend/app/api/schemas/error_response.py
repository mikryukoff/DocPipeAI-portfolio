from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    error: str = Field(description="Stable machine-readable error code")
    status_code: int = Field(description="HTTP status code")
    message: str = Field(description="Human-readable error message")
    details: dict = Field(default_factory=dict)
    request_id: str = Field(default="N/A")
