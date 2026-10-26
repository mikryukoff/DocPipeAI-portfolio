from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Any
import uuid

from fastapi import Response

from backend.app.application.exceptions import UnauthorizedError
from backend.app.config import Config


ACCESS_COOKIE_NAME = "access_token"
REFRESH_COOKIE_NAME = "refresh_token"
_RUNTIME_SESSION_ID = str(uuid.uuid4())


def _build_payload(*, user_id: int, role: str, ttl: timedelta, token_type: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    now = datetime.now(tz=UTC)
    payload = {
        "sub": str(user_id),
        "role": role,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
        "jti": str(uuid.uuid4()),
    }
    if extra:
        payload.update(extra)
    return payload


def _force_relogin_on_restart(cfg: Config) -> bool:
    return bool(getattr(cfg.security, "force_relogin_on_restart", True))


def _b64_encode(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def _b64_decode(payload: str) -> bytes:
    padding = "=" * (-len(payload) % 4)
    return base64.urlsafe_b64decode((payload + padding).encode("ascii"))


def _sign(header_b64: str, payload_b64: str, secret: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"),
        f"{header_b64}.{payload_b64}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return _b64_encode(digest)


def _encode(payload: dict[str, Any], secret: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    header_b64 = _b64_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature_b64 = _sign(header_b64, payload_b64, secret)
    return f"{header_b64}.{payload_b64}.{signature_b64}"


def create_access_token(
    user_id: int,
    role: str,
    cfg: Config,
    *,
    username: str | None = None,
) -> str:
    extra: dict[str, Any] = {}
    if username:
        extra["username"] = username
    if _force_relogin_on_restart(cfg):
        extra["sid"] = _RUNTIME_SESSION_ID
    payload = _build_payload(
        user_id=user_id,
        role=role,
        ttl=timedelta(minutes=cfg.security.jwt_access_ttl_min),
        token_type="access",
        extra=extra or None,
    )
    return _encode(payload, cfg.security.jwt_access_secret)


def create_refresh_token(
    user_id: int,
    role: str,
    cfg: Config,
    *,
    username: str | None = None,
) -> str:
    extra: dict[str, Any] = {}
    if username:
        extra["username"] = username
    if _force_relogin_on_restart(cfg):
        extra["sid"] = _RUNTIME_SESSION_ID
    payload = _build_payload(
        user_id=user_id,
        role=role,
        ttl=timedelta(days=cfg.security.jwt_refresh_ttl_days),
        token_type="refresh",
        extra=extra or None,
    )
    return _encode(payload, cfg.security.jwt_refresh_secret)


def create_change_password_token(user_id: int, cfg: Config) -> str:
    payload = _build_payload(
        user_id=user_id,
        role="change_password",
        ttl=timedelta(minutes=cfg.security.jwt_change_password_ttl_min),
        token_type="change_password",
    )
    return _encode(payload, cfg.security.jwt_change_password_secret)


def create_mfa_challenge_token(user_id: int, cfg: Config) -> str:
    payload = _build_payload(
        user_id=user_id,
        role="mfa",
        ttl=timedelta(minutes=cfg.security.jwt_mfa_ttl_min),
        token_type="mfa_challenge",
    )
    return _encode(payload, cfg.security.jwt_mfa_secret)


def decode_access_token(token: str, cfg: Config) -> dict[str, Any]:
    payload = _decode(token, cfg.security.jwt_access_secret, "access")
    if _force_relogin_on_restart(cfg) and payload.get("sid") != _RUNTIME_SESSION_ID:
        raise UnauthorizedError("Token expired")
    return payload


def decode_refresh_token(token: str, cfg: Config) -> dict[str, Any]:
    payload = _decode(token, cfg.security.jwt_refresh_secret, "refresh")
    if _force_relogin_on_restart(cfg) and payload.get("sid") != _RUNTIME_SESSION_ID:
        raise UnauthorizedError("Token expired")
    return payload


def decode_change_password_token(token: str, cfg: Config) -> dict[str, Any]:
    return _decode(token, cfg.security.jwt_change_password_secret, "change_password")


def decode_mfa_challenge_token(token: str, cfg: Config) -> dict[str, Any]:
    return _decode(token, cfg.security.jwt_mfa_secret, "mfa_challenge")


def _decode(token: str, secret: str, expected_type: str) -> dict[str, Any]:
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
        expected_sig = _sign(header_b64, payload_b64, secret)
        if not hmac.compare_digest(signature_b64, expected_sig):
            raise UnauthorizedError("Invalid token signature")
        payload = json.loads(_b64_decode(payload_b64).decode("utf-8"))
    except Exception as exc:
        raise UnauthorizedError("Invalid token") from exc
    if payload.get("type") != expected_type:
        raise UnauthorizedError("Invalid token type")
    exp = int(payload.get("exp", 0))
    now = int(datetime.now(tz=UTC).timestamp())
    if exp <= now:
        raise UnauthorizedError("Token expired")
    return payload


def set_auth_cookies(response: Response, *, access_token: str, refresh_token: str, cfg: Config) -> None:
    secure = bool(cfg.security.auth_cookie_secure)
    samesite = str(cfg.security.auth_cookie_samesite).lower()
    if samesite not in {"lax", "strict", "none"}:
        samesite = "strict"

    response.set_cookie(
        key=ACCESS_COOKIE_NAME,
        value=access_token,
        httponly=True,
        secure=secure,
        samesite=samesite,
        path="/",
        max_age=cfg.security.jwt_access_ttl_min * 60,
    )
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=secure,
        samesite=samesite,
        path="/",
        max_age=cfg.security.jwt_refresh_ttl_days * 24 * 60 * 60,
    )


def clear_auth_cookies(response: Response, cfg: Config | None = None) -> None:
    secure = bool(cfg.security.auth_cookie_secure) if cfg is not None else True
    samesite = (
        str(cfg.security.auth_cookie_samesite).lower()
        if cfg is not None
        else "strict"
    )
    if samesite not in {"lax", "strict", "none"}:
        samesite = "strict"
    response.delete_cookie(
        ACCESS_COOKIE_NAME,
        path="/",
        secure=secure,
        samesite=samesite,
    )
    response.delete_cookie(
        REFRESH_COOKIE_NAME,
        path="/",
        secure=secure,
        samesite=samesite,
    )
