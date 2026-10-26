from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from backend.app.infrastructure.db.models.user import UserRole


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=255)


class ChangePasswordRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=255)
    current_password: str | None = None
    change_password_token: str | None = None

    @field_validator("new_password")
    @classmethod
    def validate_new_password_strength(cls, value: str) -> str:
        if len(value) < 8:
            raise ValueError("Пароль должен содержать минимум 8 символов")
        if not any(ch.islower() for ch in value):
            raise ValueError("Пароль должен содержать хотя бы одну строчную букву")
        if not any(ch.isupper() for ch in value):
            raise ValueError("Пароль должен содержать хотя бы одну заглавную букву")
        if not any(ch.isdigit() for ch in value):
            raise ValueError("Пароль должен содержать хотя бы одну цифру")
        if not any(ch in "!@#$%^&*()-_=+[]{};:,.<>?/\\|" for ch in value):
            raise ValueError("Пароль должен содержать хотя бы один спецсимвол")
        return value


class RefreshResponse(BaseModel):
    ok: bool = True


class LoginSuccessResponse(BaseModel):
    ok: bool = True
    user_id: int
    role: UserRole


class ForcePasswordResponse(BaseModel):
    error: str = "force_password_change"
    change_password_token: str


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    role: UserRole = UserRole.ENGINEER
    is_active: bool = True


class UserResponse(BaseModel):
    id: int
    username: str
    role: UserRole
    is_active: bool
    force_password_change: bool


class CreateUserResponse(BaseModel):
    id: int
    username: str
    role: UserRole
    temporary_password: str


class UpdateUserRoleRequest(BaseModel):
    role: UserRole


class UpdateUserActiveRequest(BaseModel):
    is_active: bool


class AuditLogResponse(BaseModel):
    id: int
    user_id: int | None
    action: str
    details: dict
    timestamp: datetime


class ParsingLogEventResponse(BaseModel):
    ts: str | None
    user_log_key: str | None
    pipeline: str | None
    source_type: str | None
    source_file: str | None
    field: str | None
    value: object | None
    source_stream: str
    raw: dict


class JobErrorLogResponse(BaseModel):
    id: int
    user_id: int | None
    filename: str
    status: str
    error: str | None
    extra: dict | None
    created_at: datetime


class AppErrorLogResponse(BaseModel):
    ts: str | None
    level: str | None
    message: str | None
    request_id: str | None
    user_log_key: str | None
    path: str | None
    status_code: int | str | None
    error_type: str | None
    error_message: str | None
    source_stream: str
    raw: dict


class ErrorLogResponse(BaseModel):
    source_kind: str
    ts: str | None
    user_id: int | None = None
    filename: str | None = None
    path: str | None = None
    level: str | None = None
    message: str | None = None
    request_id: str | None = None
    source_stream: str
    raw: dict
