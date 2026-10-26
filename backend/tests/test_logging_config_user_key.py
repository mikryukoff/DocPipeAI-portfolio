from types import SimpleNamespace

from starlette.requests import Request

from backend.app.security.tokens import create_access_token, create_refresh_token
from backend.app.shared.logging_config import _user_log_key_from_request


def _cfg(access_ttl_min: int = 15) -> SimpleNamespace:
    return SimpleNamespace(
        security=SimpleNamespace(
            jwt_access_secret="access-secret",
            jwt_refresh_secret="refresh-secret",
            jwt_change_password_secret="change-secret",
            jwt_mfa_secret="mfa-secret",
            jwt_access_ttl_min=access_ttl_min,
            jwt_refresh_ttl_days=7,
            jwt_change_password_ttl_min=10,
            jwt_mfa_ttl_min=5,
        )
    )


def _request_with_cookie(cookie_value: str) -> Request:
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/auth/me",
        "raw_path": b"/auth/me",
        "query_string": b"",
        "headers": [(b"cookie", cookie_value.encode("utf-8"))],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }
    return Request(scope, receive)


def test_user_log_key_falls_back_to_refresh_token_when_access_expired():
    refresh_cfg = _cfg(access_ttl_min=15)
    expired_access_cfg = _cfg(access_ttl_min=0)
    access = create_access_token(7, "admin", expired_access_cfg, username="alice")
    refresh = create_refresh_token(7, "admin", refresh_cfg, username="alice")
    request = _request_with_cookie(f"access_token={access}; refresh_token={refresh}")

    assert _user_log_key_from_request(request, refresh_cfg) == "alice"


def test_user_log_key_is_unauthenticated_without_valid_tokens():
    request = _request_with_cookie("access_token=bad; refresh_token=bad")
    assert _user_log_key_from_request(request, _cfg()) == "unauthenticated"
