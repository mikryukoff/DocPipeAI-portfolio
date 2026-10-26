from __future__ import annotations

import hmac
import json
from datetime import UTC, datetime, time, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, Path, Query, Response
from fastapi.encoders import jsonable_encoder

from backend.app.api.dependencies import (
    get_audit_repository,
    get_app_logs_service,
    get_job_service,
    get_parsing_logs_service,
    get_audit_service,
    get_config,
    get_instrument_embedment_service,
    get_pipeline_repository,
    get_spec_item_repository,
    get_user_repository,
    require_roles,
)
from backend.app.application.embedment.instrument_embedment_service import (
    InstrumentEmbedmentService,
)
from backend.app.api.schemas.auth import (
    AppErrorLogResponse,
    AuditLogResponse,
    CreateUserRequest,
    CreateUserResponse,
    ErrorLogResponse,
    JobErrorLogResponse,
    ParsingLogEventResponse,
    UpdateUserActiveRequest,
    UpdateUserRoleRequest,
    UserResponse,
)
from backend.app.application.app_logs_service import AppLogsQuery, AppLogsService
from backend.app.application.jobs.job_service import JobService
from backend.app.application.parsing_logs_service import ParsingLogsQuery, ParsingLogsService
from backend.app.application.exceptions import NotFoundError, ValidationError
from backend.app.application.security.audit_service import AuditService
from backend.app.config import Config
from backend.app.infrastructure.db.models.user import UserORM, UserRole
from backend.app.infrastructure.repositories.audit_repository import AuditRepository
from backend.app.infrastructure.repositories.pipeline_repository import PipelineRepository
from backend.app.infrastructure.repositories.spec_item_repository import SpecItemRepository
from backend.app.infrastructure.repositories.user_repository import UserRepository
from backend.app.security.passwords import generate_temporary_password, hash_password
from backend.app.shared.user_log_key import format_user_log_key


router = APIRouter(prefix="/admin", tags=["Admin"])


def _parse_date_boundary(value: str | None, *, end: bool) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        day = datetime.fromisoformat(text).date()
    except ValueError:
        return None
    bound = time.max if end else time.min
    return datetime.combine(day, bound, tzinfo=UTC).replace(tzinfo=None)


def _normalize_ts(value: str | None) -> datetime:
    text = str(value or "").strip()
    if not text:
        return datetime.min.replace(tzinfo=UTC)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _parse_client_timezone(offset_minutes: int | None) -> timezone:
    if offset_minutes is None:
        return datetime.now().astimezone().tzinfo or UTC
    safe = max(-14 * 60, min(14 * 60, int(offset_minutes)))
    return timezone(timedelta(minutes=safe))


def _to_client_tz_iso(value: Any, tz: timezone) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return text
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(tz).isoformat()


def _normalize_event_ts_for_client(event: dict[str, Any], tz: timezone) -> dict[str, Any]:
    out = dict(event)
    out["ts"] = _to_client_tz_iso(event.get("ts"), tz)
    raw = event.get("raw")
    if isinstance(raw, dict):
        raw_copy = dict(raw)
        if "ts" in raw_copy:
            raw_copy["ts"] = _to_client_tz_iso(raw_copy.get("ts"), tz)
        out["raw"] = raw_copy
    return out


def _require_logs_clear_password(*, config: Config, provided_password: str | None) -> None:
    expected = (config.security.admin_logs_clear_password or "").strip()
    if not expected:
        raise ValidationError(
            "Logs clear password is not configured",
            details={"reason": "logs_clear_password_not_configured"},
        )
    candidate = (provided_password or "").strip()
    if not candidate:
        raise ValidationError(
            "Access password is required",
            details={"reason": "logs_clear_password_required"},
        )
    if not hmac.compare_digest(candidate, expected):
        raise ValidationError(
            "Access password is invalid",
            details={"reason": "logs_clear_password_invalid"},
        )


async def _resolve_user_scope(
    *,
    users: UserRepository,
    user_id: int | None,
    login: str | None,
) -> tuple[int | None, str | None]:
    if user_id is not None:
        user = await users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User not found")
        return user.id, format_user_log_key(user_id=user.id, username=user.username)

    username = (login or "").strip()
    if not username:
        return None, None
    user = await users.get_by_username(username)
    if user is not None:
        return user.id, format_user_log_key(user_id=user.id, username=user.username)
    return None, username


def _invalid_pipeline_events_as_error_rows(
    events: list[dict[str, Any]],
    *,
    resolved_user_id: int | None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ev in events:
        msg = str(ev.get("value") or "").strip() or str(ev.get("field") or "").strip()
        out.append(
            {
                "source_kind": "invalid_pipeline",
                "ts": ev.get("ts"),
                "user_id": resolved_user_id,
                "filename": ev.get("source_file"),
                "path": str(ev.get("pipeline") or "") or None,
                "level": "ERROR",
                "message": msg or "invalid_pipeline",
                "request_id": None,
                "source_stream": "invalid_pipelines",
                "raw": dict(ev) if isinstance(ev, dict) else {},
            }
        )
    return out


def _merge_error_rows(
    *,
    job_rows: list[JobErrorLogResponse],
    app_rows: list[AppErrorLogResponse],
    invalid_pipeline_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for row in job_rows:
        merged.append(
            {
                "source_kind": "job_error",
                "ts": row.created_at.isoformat() if row.created_at else None,
                "user_id": row.user_id,
                "filename": row.filename,
                "path": None,
                "level": "ERROR",
                "message": row.error,
                "request_id": None,
                "source_stream": "job_errors",
                "raw": row.model_dump(),
            }
        )
    for row in app_rows:
        merged.append(
            {
                "source_kind": "app_error",
                "ts": row.ts,
                "user_id": None,
                "filename": None,
                "path": row.path,
                "level": row.level,
                "message": row.error_message or row.message,
                "request_id": row.request_id,
                "source_stream": row.source_stream,
                "raw": row.model_dump(),
            }
        )
    for row in invalid_pipeline_rows or []:
        merged.append(row)
    merged.sort(key=lambda item: _normalize_ts(item.get("ts")), reverse=True)
    return merged


def _list_invalid_pipeline_events_for_admin_errors(
    parsing_logs: ParsingLogsService,
    *,
    log_login: str,
    date_from: str | None,
    date_to: str | None,
    file_type: str | None,
    text: str | None,
    cap: int,
) -> list[dict[str, Any]]:
    log_login = (log_login or "").strip()
    if not log_login:
        return []
    q = ParsingLogsQuery(
        login=log_login,
        pipeline=None,
        date_from=date_from,
        date_to=date_to,
        file_type=file_type,
        limit=min(max(cap, 1), 1000),
        offset=0,
    )
    rows = [e for e in parsing_logs.list_events(q) if e.get("source_stream") == "invalid_pipelines"]
    needle = (text or "").strip().lower()
    if not needle:
        return rows
    filtered: list[dict[str, Any]] = []
    for e in rows:
        hay = " ".join(
            str(x).lower()
            for x in (
                e.get("pipeline"),
                e.get("source_file"),
                e.get("value"),
                e.get("field"),
            )
        )
        if needle in hay:
            filtered.append(e)
    return filtered


def _to_user_response(user: UserORM) -> UserResponse:
    return UserResponse(
        id=user.id,
        username=user.username,
        role=user.role,
        is_active=user.is_active,
        force_password_change=user.force_password_change,
    )


@router.post("/users", response_model=CreateUserResponse)
async def create_user(
    payload: CreateUserRequest,
    _: UserORM = Depends(require_roles([UserRole.ADMIN])),
    users: UserRepository = Depends(get_user_repository),
    config: Config = Depends(get_config),
    audit: AuditService = Depends(get_audit_service),
):
    existing = await users.get_by_username(payload.username)
    if existing is not None:
        raise ValidationError("Username already exists")

    temporary_password = generate_temporary_password(config.security.temp_password_len)
    user = UserORM(
        username=payload.username,
        role=payload.role,
        password_hash=hash_password(temporary_password),
        temporary_password=temporary_password,
        force_password_change=True,
        is_active=payload.is_active,
    )
    users.session.add(user)
    await users.session.flush()
    await audit.log(
        user_id=_.id,
        action="admin_user_create",
        details={"created_user_id": user.id, "role": user.role.value},
    )
    await users.session.commit()
    return CreateUserResponse(
        id=user.id,
        username=user.username,
        role=user.role,
        temporary_password=temporary_password,
    )


@router.get("/users", response_model=list[UserResponse])
async def list_users(
    _: UserORM = Depends(require_roles([UserRole.ADMIN])),
    users: UserRepository = Depends(get_user_repository),
):
    rows = await users.list_users()
    return [_to_user_response(row) for row in rows]


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int = Path(..., gt=0),
    current_user: UserORM = Depends(require_roles([UserRole.ADMIN])),
    users: UserRepository = Depends(get_user_repository),
    audit: AuditService = Depends(get_audit_service),
):
    if current_user.id == user_id:
        raise ValidationError("Admin cannot delete own account")

    user = await users.get_by_id(user_id)
    if user is None:
        raise NotFoundError("User not found")
    await users.session.delete(user)
    await users.session.flush()
    await audit.log(
        user_id=current_user.id,
        action="admin_user_delete",
        details={"deleted_user_id": user_id},
    )
    await users.session.commit()
    return {"ok": True}


@router.put("/users/{user_id}/role", response_model=UserResponse)
async def update_user_role(
    payload: UpdateUserRoleRequest,
    user_id: int = Path(..., gt=0),
    current_user: UserORM = Depends(require_roles([UserRole.ADMIN])),
    users: UserRepository = Depends(get_user_repository),
    audit: AuditService = Depends(get_audit_service),
):
    user = await users.get_by_id(user_id)
    if user is None:
        raise NotFoundError("User not found")
    user.role = payload.role
    await users.session.flush()
    await audit.log(
        user_id=current_user.id,
        action="admin_user_role_updated",
        details={"target_user_id": user_id, "role": payload.role.value},
    )
    await users.session.commit()
    return _to_user_response(user)


@router.patch("/users/{user_id}/active", response_model=UserResponse)
async def update_user_active(
    payload: UpdateUserActiveRequest,
    user_id: int = Path(..., gt=0),
    current_user: UserORM = Depends(require_roles([UserRole.ADMIN])),
    users: UserRepository = Depends(get_user_repository),
    audit: AuditService = Depends(get_audit_service),
):
    if current_user.id == user_id:
        raise ValidationError("Нельзя изменить статус своей учётной записи")
    user = await users.get_by_id(user_id)
    if user is None:
        raise NotFoundError("User not found")
    user.is_active = payload.is_active
    await users.session.flush()
    await audit.log(
        user_id=current_user.id,
        action="admin_user_active_updated",
        details={"target_user_id": user_id, "is_active": payload.is_active},
    )
    await users.session.commit()
    return _to_user_response(user)


@router.get("/audit-logs", response_model=list[AuditLogResponse])
async def list_audit_logs(
    user_id: int | None = Query(default=None, ge=1),
    action: str | None = Query(default=None, max_length=120),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: UserORM = Depends(require_roles([UserRole.ADMIN])),
    repo: AuditRepository = Depends(get_audit_repository),
):
    rows = await repo.list_filtered(
        user_id=user_id,
        action=action,
        date_from=_parse_date_boundary(date_from, end=False),
        date_to=_parse_date_boundary(date_to, end=True),
        limit=limit,
        offset=offset,
    )
    return [
        AuditLogResponse(
            id=row.id,
            user_id=row.user_id,
            action=row.action,
            details=row.details,
            timestamp=row.timestamp,
        )
        for row in rows
    ]


@router.get("/audit-logs/download")
async def download_audit_logs(
    user_id: int | None = Query(default=None, ge=1),
    action: str | None = Query(default=None, max_length=120),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    current_user: UserORM = Depends(require_roles([UserRole.ADMIN])),
    repo: AuditRepository = Depends(get_audit_repository),
    audit: AuditService = Depends(get_audit_service),
):
    rows = await repo.list_filtered(
        user_id=user_id,
        action=action,
        date_from=_parse_date_boundary(date_from, end=False),
        date_to=_parse_date_boundary(date_to, end=True),
        limit=100000,
        offset=0,
    )
    await audit.log(
        user_id=current_user.id,
        action="admin_audit_logs_download",
        details={
            "user_id": user_id,
            "action_filter": action,
            "date_from": date_from,
            "date_to": date_to,
            "rows_total": len(rows),
        },
    )
    payload = [
        {
            "id": row.id,
            "user_id": row.user_id,
            "action": row.action,
            "details": row.details,
            "timestamp": row.timestamp.isoformat() if row.timestamp else None,
        }
        for row in rows
    ]
    content = b"".join(
        (json.dumps(jsonable_encoder(item), ensure_ascii=False) + "\n").encode("utf-8")
        for item in payload
    )
    filename = "audit_logs.jsonl" if user_id is None else f"audit_logs_user_{user_id}.jsonl"
    return Response(
        content=content,
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/audit-logs")
async def clear_audit_logs(
    user_id: int = Query(..., ge=1),
    confirm: bool = Query(default=False),
    access_password: str | None = Header(default=None, alias="X-Admin-Clear-Password"),
    current_user: UserORM = Depends(require_roles([UserRole.ADMIN])),
    repo: AuditRepository = Depends(get_audit_repository),
    audit: AuditService = Depends(get_audit_service),
    config: Config = Depends(get_config),
):
    if not confirm:
        raise ValidationError("Confirm flag is required")
    _require_logs_clear_password(config=config, provided_password=access_password)
    removed = await repo.clear_filtered(user_id=user_id)
    await audit.log(
        user_id=current_user.id,
        action="admin_audit_logs_clear",
        details={"user_id": user_id, "removed_rows": removed},
    )
    return {"ok": True, "removed_rows": removed}


@router.get("/job-errors", response_model=list[JobErrorLogResponse])
async def list_job_errors(
    user_id: int | None = Query(default=None, ge=1),
    source: str | None = Query(default=None, max_length=32),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: UserORM = Depends(require_roles([UserRole.ADMIN])),
    jobs: JobService = Depends(get_job_service),
):
    rows = await jobs.list_failed_jobs(
        user_id=user_id,
        source=source,
        date_from=_parse_date_boundary(date_from, end=False),
        date_to=_parse_date_boundary(date_to, end=True),
        limit=limit,
        offset=offset,
    )
    return [
        JobErrorLogResponse(
            id=row.id,
            user_id=row.user_id,
            filename=row.filename,
            status=row.status,
            error=row.error,
            extra=row.extra,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.get("/app-errors", response_model=list[AppErrorLogResponse])
async def list_app_errors(
    user_id: int | None = Query(default=None, ge=1),
    login: str | None = Query(default=None, min_length=1, max_length=100),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    level: str = Query(default="error", pattern="^(error|warn|all)$"),
    text: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    _: UserORM = Depends(require_roles([UserRole.ADMIN])),
    users: UserRepository = Depends(get_user_repository),
    logs: AppLogsService = Depends(get_app_logs_service),
):
    user_log_key = (login or "").strip()
    if user_id is not None:
        user = await users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User not found")
        user_log_key = format_user_log_key(user_id=user.id, username=user.username)
    if not user_log_key:
        raise ValidationError("User identifier is required", details={"reason": "user_required"})

    rows = logs.list_events(
        AppLogsQuery(
            user_log_key=user_log_key,
            date_from=date_from,
            date_to=date_to,
            level=level,
            text=text,
            limit=limit,
            offset=offset,
        )
    )
    return [AppErrorLogResponse(**row) for row in rows]


@router.get("/errors", response_model=list[ErrorLogResponse])
async def list_errors(
    user_id: int | None = Query(default=None, ge=1),
    login: str | None = Query(default=None, min_length=1, max_length=100),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    text: str | None = Query(default=None, max_length=200),
    file_type: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    _: UserORM = Depends(require_roles([UserRole.ADMIN])),
    users: UserRepository = Depends(get_user_repository),
    jobs: JobService = Depends(get_job_service),
    app_logs: AppLogsService = Depends(get_app_logs_service),
    parsing_logs: ParsingLogsService = Depends(get_parsing_logs_service),
):
    resolved_user_id, user_log_key = await _resolve_user_scope(
        users=users,
        user_id=user_id,
        login=login,
    )
    if resolved_user_id is None and not user_log_key:
        raise ValidationError("User identifier is required", details={"reason": "user_required"})

    query_limit = max(limit + offset + 200, 500)
    job_rows_orm = await jobs.list_failed_jobs(
        user_id=resolved_user_id,
        source=file_type,
        date_from=_parse_date_boundary(date_from, end=False),
        date_to=_parse_date_boundary(date_to, end=True),
        limit=query_limit,
        offset=0,
    )
    job_rows = [
        JobErrorLogResponse(
            id=row.id,
            user_id=row.user_id,
            filename=row.filename,
            status=row.status,
            error=row.error,
            extra=row.extra,
            created_at=row.created_at,
        )
        for row in job_rows_orm
    ]
    app_rows = [
        AppErrorLogResponse(**row)
        for row in app_logs.list_events(
            AppLogsQuery(
                user_log_key=user_log_key or "",
                date_from=date_from,
                date_to=date_to,
                level="error",
                text=text,
                limit=query_limit,
                offset=0,
            )
        )
    ]
    log_login = (user_log_key or (login or "").strip())
    inv_events = _list_invalid_pipeline_events_for_admin_errors(
        parsing_logs,
        log_login=log_login,
        date_from=date_from,
        date_to=date_to,
        file_type=file_type,
        text=text,
        cap=query_limit,
    )
    inv_rows = _invalid_pipeline_events_as_error_rows(inv_events, resolved_user_id=resolved_user_id)
    merged = _merge_error_rows(job_rows=job_rows, app_rows=app_rows, invalid_pipeline_rows=inv_rows)
    if offset > 0:
        merged = merged[offset:]
    return [ErrorLogResponse(**row) for row in merged[: max(1, min(limit, 1000))]]


@router.get("/errors/download")
async def download_errors(
    user_id: int | None = Query(default=None, ge=1),
    login: str | None = Query(default=None, min_length=1, max_length=100),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    text: str | None = Query(default=None, max_length=200),
    file_type: str | None = Query(default=None, max_length=32),
    export_format: str = Query("jsonl", alias="format", pattern="^(jsonl|json)$"),
    current_user: UserORM = Depends(require_roles([UserRole.ADMIN])),
    users: UserRepository = Depends(get_user_repository),
    jobs: JobService = Depends(get_job_service),
    app_logs: AppLogsService = Depends(get_app_logs_service),
    parsing_logs: ParsingLogsService = Depends(get_parsing_logs_service),
    audit: AuditService = Depends(get_audit_service),
):
    resolved_user_id, user_log_key = await _resolve_user_scope(
        users=users,
        user_id=user_id,
        login=login,
    )
    if resolved_user_id is None and not user_log_key:
        raise ValidationError("User identifier is required", details={"reason": "user_required"})

    job_rows_orm = await jobs.list_failed_jobs(
        user_id=resolved_user_id,
        source=file_type,
        date_from=_parse_date_boundary(date_from, end=False),
        date_to=_parse_date_boundary(date_to, end=True),
        limit=100000,
        offset=0,
    )
    job_rows = [
        JobErrorLogResponse(
            id=row.id,
            user_id=row.user_id,
            filename=row.filename,
            status=row.status,
            error=row.error,
            extra=row.extra,
            created_at=row.created_at,
        )
        for row in job_rows_orm
    ]
    app_rows = [
        AppErrorLogResponse(**row)
        for row in app_logs.list_events(
            AppLogsQuery(
                user_log_key=user_log_key or "",
                date_from=date_from,
                date_to=date_to,
                level="error",
                text=text,
                limit=100000,
                offset=0,
            )
        )
    ]
    log_login = (user_log_key or (login or "").strip())
    inv_events = _list_invalid_pipeline_events_for_admin_errors(
        parsing_logs,
        log_login=log_login,
        date_from=date_from,
        date_to=date_to,
        file_type=file_type,
        text=text,
        cap=100000,
    )
    inv_rows = _invalid_pipeline_events_as_error_rows(inv_events, resolved_user_id=resolved_user_id)
    merged = _merge_error_rows(job_rows=job_rows, app_rows=app_rows, invalid_pipeline_rows=inv_rows)
    await audit.log(
        user_id=current_user.id,
        action="admin_errors_logs_download",
        details={
            "user_id": resolved_user_id,
            "user_log_key": user_log_key,
            "file_type": file_type,
            "date_from": date_from,
            "date_to": date_to,
            "rows_total": len(merged),
            "format": export_format,
        },
    )
    enc_rows = [jsonable_encoder(item) for item in merged]
    filename_user = resolved_user_id if resolved_user_id is not None else (user_log_key or "unknown")
    if export_format == "json":
        content = json.dumps(enc_rows, ensure_ascii=False).encode("utf-8")
        return Response(
            content=content,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="errors_logs_{filename_user}.json"'},
        )
    content = b"".join(
        (json.dumps(item, ensure_ascii=False) + "\n").encode("utf-8") for item in enc_rows
    )
    return Response(
        content=content,
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="errors_logs_{filename_user}.jsonl"'},
    )


@router.delete("/errors")
async def clear_errors(
    user_id: int | None = Query(default=None, ge=1),
    login: str | None = Query(default=None, min_length=1, max_length=100),
    confirm: bool = Query(default=False),
    file_type: str | None = Query(default=None, max_length=32),
    access_password: str | None = Header(default=None, alias="X-Admin-Clear-Password"),
    current_user: UserORM = Depends(require_roles([UserRole.ADMIN])),
    users: UserRepository = Depends(get_user_repository),
    jobs: JobService = Depends(get_job_service),
    app_logs: AppLogsService = Depends(get_app_logs_service),
    audit: AuditService = Depends(get_audit_service),
    config: Config = Depends(get_config),
):
    if not confirm:
        raise ValidationError("Confirm flag is required")
    _require_logs_clear_password(config=config, provided_password=access_password)
    resolved_user_id, user_log_key = await _resolve_user_scope(
        users=users,
        user_id=user_id,
        login=login,
    )
    if resolved_user_id is None and not user_log_key:
        raise ValidationError("User identifier is required", details={"reason": "user_required"})
    removed_jobs = await jobs.clear_failed_jobs(user_id=resolved_user_id, source=file_type)
    removed_app_files = app_logs.clear_logs(user_log_key=user_log_key or "")
    await audit.log(
        user_id=current_user.id,
        action="admin_errors_logs_clear",
        details={
            "user_id": resolved_user_id,
            "user_log_key": user_log_key,
            "removed_job_rows": removed_jobs,
            "removed_app_files": removed_app_files,
            "source": file_type,
        },
    )
    return {
        "ok": True,
        "removed_job_rows": removed_jobs,
        "removed_app_files": removed_app_files,
    }


@router.get("/parsing-logs", response_model=list[ParsingLogEventResponse])
async def list_parsing_logs(
    login: str = Query(..., min_length=1, max_length=100),
    pipeline: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    file_type: str | None = Query(default=None),
    tz_offset_min: int | None = Query(default=None, ge=-840, le=840),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    _: UserORM = Depends(require_roles([UserRole.ADMIN])),
    logs: ParsingLogsService = Depends(get_parsing_logs_service),
):
    query = ParsingLogsQuery(
        login=login,
        pipeline=pipeline,
        date_from=date_from,
        date_to=date_to,
        file_type=file_type,
        limit=limit,
        offset=offset,
    )
    tz = _parse_client_timezone(tz_offset_min)
    return [_normalize_event_ts_for_client(item, tz) for item in logs.list_events(query)]


@router.get("/parsing-logs/download")
async def download_parsing_logs(
    login: str = Query(..., min_length=1, max_length=100),
    pipeline: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    file_type: str | None = Query(default=None),
    tz_offset_min: int | None = Query(default=None, ge=-840, le=840),
    export_format: str = Query("jsonl", alias="format", pattern="^(jsonl|json)$"),
    current_user: UserORM = Depends(require_roles([UserRole.ADMIN])),
    logs: ParsingLogsService = Depends(get_parsing_logs_service),
    audit: AuditService = Depends(get_audit_service),
):
    query = ParsingLogsQuery(
        login=login,
        pipeline=pipeline,
        date_from=date_from,
        date_to=date_to,
        file_type=file_type,
        limit=100000,
        offset=0,
    )
    filename = f"parsing_logs_{login}.jsonl"
    await audit.log(
        user_id=current_user.id,
        action="admin_parsing_logs_download",
        details={
            "login": login,
            "pipeline": pipeline,
            "date_from": date_from,
            "date_to": date_to,
            "file_type": file_type,
            "format": export_format,
        },
    )
    tz = _parse_client_timezone(tz_offset_min)
    rows = [_normalize_event_ts_for_client(item, tz) for item in logs.list_events(query)]
    enc_rows = [jsonable_encoder(item) for item in rows]
    if export_format == "json":
        filename = f"parsing_logs_{login}.json"
        content = json.dumps(enc_rows, ensure_ascii=False).encode("utf-8")
        return Response(
            content=content,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    content = b"".join(
        (json.dumps(item, ensure_ascii=False) + "\n").encode("utf-8") for item in enc_rows
    )
    return Response(
        content=content,
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/parsing-logs")
async def clear_parsing_logs(
    login: str = Query(..., min_length=1, max_length=100),
    confirm: bool = Query(default=False),
    access_password: str | None = Header(default=None, alias="X-Admin-Clear-Password"),
    current_user: UserORM = Depends(require_roles([UserRole.ADMIN])),
    logs: ParsingLogsService = Depends(get_parsing_logs_service),
    audit: AuditService = Depends(get_audit_service),
    config: Config = Depends(get_config),
):
    if not confirm:
        raise ValidationError("Confirm flag is required")
    _require_logs_clear_password(config=config, provided_password=access_password)
    removed = logs.clear_logs(login=login)
    await audit.log(
        user_id=current_user.id,
        action="admin_parsing_logs_clear",
        details={"login": login, "removed_files": removed},
    )
    return {"ok": True, "removed_files": removed}


@router.get("/instrument-embedments")
async def admin_list_all_instrument_embedments(
    _: UserORM = Depends(require_roles([UserRole.ADMIN, UserRole.ENGINEER, UserRole.DEMO])),
    repo: PipelineRepository = Depends(get_pipeline_repository),
    spec_repo: SpecItemRepository = Depends(get_spec_item_repository),
    embedment_service: InstrumentEmbedmentService = Depends(get_instrument_embedment_service),
):
    """Все закладные из БД: по одной записи на строку спецификации (позиция), с полем pipeline для сохранения."""
    return await embedment_service.list_all_embedments_flat_for_admin(
        repo=repo,
        spec_repo=spec_repo,
    )


@router.post("/instrument-embedments/sync-drawing-paths")
async def admin_sync_instrument_embedment_drawing_paths(
    admin: UserORM = Depends(require_roles([UserRole.ADMIN, UserRole.ENGINEER])),
    spec_repo: SpecItemRepository = Depends(get_spec_item_repository),
    audit: AuditService = Depends(get_audit_service),
    only_missing: bool = Query(
        default=True,
        description="Если true — только строки без drawing_image_path; если false — перезаписать путь из JSON",
    ),
):
    """
    Подтянуть `drawing_image_path` из каталога parsed_texts (Drawing4Store) для всех закладных в БД.
    Перед синхронизацией сбрасывается кэш JSON в памяти (без перезапуска сервера).
    """
    n = await spec_repo.sync_instrument_embedment_drawing_paths_from_store(
        only_missing=only_missing,
    )
    await audit.log(
        user_id=admin.id,
        action="admin_sync_embedment_drawing_paths",
        details={"updated_rows": n, "only_missing": only_missing},
    )
    return {"updated": n, "only_missing": only_missing}
