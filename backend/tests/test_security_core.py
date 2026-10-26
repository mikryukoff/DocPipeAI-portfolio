from types import SimpleNamespace

import pytest
from fastapi import Response

from backend.app.application.exceptions import UnauthorizedError
from backend.app.security.file_encryption import FileEncryptionService
from backend.app.security.passwords import generate_temporary_password, hash_password, verify_password
from backend.app.security.tokens import (
    clear_auth_cookies,
    create_access_token,
    create_change_password_token,
    create_refresh_token,
    decode_access_token,
    decode_change_password_token,
    set_auth_cookies,
)
from backend.app.security.totp import generate_totp_secret, verify_totp, _totp_now


def _config():
    return SimpleNamespace(
        security=SimpleNamespace(
            jwt_access_secret="access-secret",
            jwt_refresh_secret="refresh-secret",
            jwt_change_password_secret="change-secret",
            jwt_mfa_secret="mfa-secret",
            jwt_access_ttl_min=15,
            jwt_refresh_ttl_days=7,
            jwt_change_password_ttl_min=10,
            jwt_mfa_ttl_min=5,
            auth_cookie_secure=True,
            auth_cookie_samesite="strict",
            force_relogin_on_restart=True,
        )
    )


def test_password_hashing_and_generation():
    password = generate_temporary_password(12)
    assert len(password) >= 12
    hashed = hash_password(password)
    assert verify_password(password, hashed)
    assert not verify_password("wrong", hashed)


def test_tokens_roundtrip():
    cfg = _config()
    access = create_access_token(7, "admin", cfg)
    payload = decode_access_token(access, cfg)
    assert int(payload["sub"]) == 7
    assert payload["role"] == "admin"

    change = create_change_password_token(11, cfg)
    change_payload = decode_change_password_token(change, cfg)
    assert int(change_payload["sub"]) == 11


def test_access_token_invalidated_after_restart(monkeypatch):
    cfg = _config()
    access = create_access_token(7, "admin", cfg)
    monkeypatch.setattr(
        "backend.app.security.tokens._RUNTIME_SESSION_ID",
        "new-runtime-session-id",
    )
    with pytest.raises(UnauthorizedError):
        decode_access_token(access, cfg)


def test_totp_and_file_encryption_roundtrip():
    secret = generate_totp_secret()
    code = _totp_now(secret=secret, step_offset=0)
    assert verify_totp(secret=secret, code=code)

    crypto = FileEncryptionService("test-key")
    payload = b"secret-bytes"
    encrypted = crypto.encrypt(payload)
    assert encrypted != payload
    assert crypto.decrypt(encrypted) == payload


def test_auth_cookies_are_secure_and_strict():
    cfg = _config()
    response = Response()
    set_auth_cookies(
        response,
        access_token=create_access_token(1, "admin", cfg),
        refresh_token=create_refresh_token(1, "admin", cfg),
        cfg=cfg,
    )
    cookies = response.headers.getlist("set-cookie")
    assert len(cookies) == 2
    assert all("HttpOnly" in item for item in cookies)
    assert all("Secure" in item for item in cookies)
    assert all("SameSite=strict" in item for item in cookies)

    clear_auth_cookies(response, cfg=cfg)
    cleared = response.headers.getlist("set-cookie")
    assert any("Max-Age=0" in item for item in cleared)
