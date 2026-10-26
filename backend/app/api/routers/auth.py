from __future__ import annotations

from time import time

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from loguru import logger

from backend.app.api.dependencies import (
    get_audit_service,
    get_config,
    get_current_user,
    get_current_user_optional,
    require_roles,
    get_user_repository,
)
from backend.app.api.schemas.auth import (
    ChangePasswordRequest,
    ForcePasswordResponse,
    LoginRequest,
    LoginSuccessResponse,
    RefreshResponse,
)
from backend.app.application.exceptions import ForbiddenError, UnauthorizedError
from backend.app.application.security.audit_service import AuditService
from backend.app.config import Config
from backend.app.infrastructure.db.models.user import UserORM, UserRole
from backend.app.infrastructure.repositories.user_repository import UserRepository
from backend.app.security.passwords import generate_temporary_password, hash_password, verify_password
from backend.app.security.rate_limit import login_rate_limiter
from backend.app.security.tokens import (
    REFRESH_COOKIE_NAME,
    clear_auth_cookies,
    create_access_token,
    create_change_password_token,
    create_refresh_token,
    decode_change_password_token,
    decode_refresh_token,
    set_auth_cookies,
)


router = APIRouter(prefix="/auth", tags=["Auth"])

_used_change_password_jti: dict[str, int] = {}


def _register_change_password_jti_once(*, jti: str, exp: int) -> None:
    now = int(time())
    expired = [token_id for token_id, token_exp in _used_change_password_jti.items() if token_exp <= now]
    for token_id in expired:
        _used_change_password_jti.pop(token_id, None)

    if (_used_change_password_jti.get(jti) or 0) > now:
        raise UnauthorizedError("Password change token is already used")
    _used_change_password_jti[jti] = max(exp, now + 1)


async def _safe_audit(audit: AuditService, *, user_id: int | None, action: str, details: dict | None = None) -> None:
    try:
        await audit.log(user_id=user_id, action=action, details=details or {})
    except Exception:
        logger.exception("Audit log write failed. action={} user_id={}", action, user_id)


@router.post("/login", response_model=LoginSuccessResponse, responses={403: {"model": ForcePasswordResponse}})
async def login(
    payload: LoginRequest,
    response: Response,
    request: Request,
    config: Config = Depends(get_config),
    users: UserRepository = Depends(get_user_repository),
    audit: AuditService = Depends(get_audit_service),
):
    ip = request.client.host if request.client else "unknown"
    logger.info("Login attempt. username={} ip={}", payload.username, ip)
    login_rate_limiter.check(ip=ip, cfg=config)

    user = await users.get_by_username(payload.username)
    if user is None:
        logger.warning("Login failed: user not found. username={} ip={}", payload.username, ip)
        login_rate_limiter.mark_failure(ip=ip, cfg=config)
        await _safe_audit(
            audit,
            user_id=None,
            action="login_failed_user_not_found",
            details={"username": payload.username, "ip": ip},
        )
        raise UnauthorizedError("Invalid credentials")
    if not verify_password(payload.password, user.password_hash):
        logger.warning("Login failed: wrong password. username={} user_id={} ip={}", payload.username, user.id, ip)
        login_rate_limiter.mark_failure(ip=ip, cfg=config)
        await _safe_audit(
            audit,
            user_id=user.id,
            action="login_failed_wrong_password",
            details={"username": payload.username, "ip": ip},
        )
        raise UnauthorizedError("Invalid credentials")
    if not user.is_active:
        logger.warning("Login failed: user inactive. username={} user_id={} ip={}", payload.username, user.id, ip)
        login_rate_limiter.mark_failure(ip=ip, cfg=config)
        await _safe_audit(audit, user_id=user.id, action="login_failed_inactive", details={"ip": ip})
        raise UnauthorizedError("User is inactive")

    if user.force_password_change:
        logger.info("Login requires password change. username={} user_id={} ip={}", payload.username, user.id, ip)
        token = create_change_password_token(user.id, config)
        await _safe_audit(audit, user_id=user.id, action="login_force_password_change", details={"ip": ip})
        force_response = JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content=ForcePasswordResponse(change_password_token=token).model_dump(),
        )
        # Prevent keeping an old account session when switching user.
        clear_auth_cookies(force_response, cfg=config)
        return force_response

    login_rate_limiter.mark_success(ip=ip)
    access_token = create_access_token(
        user.id, user.role.value, config, username=user.username
    )
    refresh_token = create_refresh_token(
        user.id, user.role.value, config, username=user.username
    )
    set_auth_cookies(response, access_token=access_token, refresh_token=refresh_token, cfg=config)
    logger.info("Login success. username={} user_id={} role={} ip={}", payload.username, user.id, user.role.value, ip)
    await _safe_audit(audit, user_id=user.id, action="login_success", details={"ip": ip})
    return LoginSuccessResponse(user_id=user.id, role=user.role)


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(
    request: Request,
    response: Response,
    config: Config = Depends(get_config),
    users: UserRepository = Depends(get_user_repository),
):
    refresh_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if not refresh_token:
        raise UnauthorizedError("Refresh token is required")
    payload = decode_refresh_token(refresh_token, config)
    user_id = int(payload["sub"])
    role = str(payload["role"])
    user = await users.get_by_id(user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("Invalid user")

    access_token = create_access_token(
        user_id, role, config, username=user.username
    )
    new_refresh_token = create_refresh_token(
        user_id, role, config, username=user.username
    )
    set_auth_cookies(response, access_token=access_token, refresh_token=new_refresh_token, cfg=config)
    return RefreshResponse()


@router.post("/logout")
async def logout(response: Response, config: Config = Depends(get_config)):
    clear_auth_cookies(response, cfg=config)
    return {"ok": True}


@router.get("/me")
async def me(current_user: UserORM = Depends(get_current_user)):
    return {
        "user_id": current_user.id,
        "username": current_user.username,
        "role": current_user.role.value,
        "is_active": current_user.is_active,
    }


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordRequest,
    response: Response,
    config: Config = Depends(get_config),
    users: UserRepository = Depends(get_user_repository),
    current_user: UserORM | None = Depends(get_current_user_optional),
    audit: AuditService = Depends(get_audit_service),
):
    user: UserORM | None = None
    if payload.change_password_token:
        token_payload = decode_change_password_token(payload.change_password_token, config)
        jti = str(token_payload["jti"])
        exp = int(token_payload.get("exp") or 0)
        _register_change_password_jti_once(jti=jti, exp=exp)
        user = await users.get_by_id(int(token_payload["sub"]))
    else:
        user = current_user
        if user is None:
            raise UnauthorizedError("Authentication required")
        if not payload.current_password or not verify_password(payload.current_password, user.password_hash):
            raise UnauthorizedError("Current password is invalid")

    if user is None:
        raise UnauthorizedError("User not found")

    user.password_hash = hash_password(payload.new_password)
    user.force_password_change = False
    user.temporary_password = None
    await users.session.flush()
    await _safe_audit(audit, user_id=user.id, action="password_changed")
    if payload.change_password_token:
        # Token-based password change should end any previous session and require fresh login.
        clear_auth_cookies(response, cfg=config)
    return {"ok": True, "require_relogin": bool(payload.change_password_token)}


@router.get("/generate-password")
async def generate_password(
    config: Config = Depends(get_config),
    _: UserORM = Depends(require_roles([UserRole.ADMIN])),
):
    if not config.security.allow_password_generator_endpoint:
        raise ForbiddenError("Password generator endpoint is disabled")
    return {"password": generate_temporary_password(config.security.temp_password_len)}
