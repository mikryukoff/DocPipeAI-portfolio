from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.dependencies import get_config, get_current_user
from backend.app.api.exception_handlers import register_exception_handlers
from backend.app.api.routers.auth import router as auth_router
from backend.app.infrastructure.db.models.user import UserRole


def _build_app(*, role: UserRole, allow_endpoint: bool, temp_password_len: int = 12) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(auth_router)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=7,
        username="tester",
        role=role,
        is_active=True,
    )
    app.dependency_overrides[get_config] = lambda: SimpleNamespace(
        security=SimpleNamespace(
            allow_password_generator_endpoint=allow_endpoint,
            temp_password_len=temp_password_len,
        )
    )
    return app


def test_generate_password_admin_only():
    app = _build_app(role=UserRole.ENGINEER, allow_endpoint=True)
    with TestClient(app) as client:
        response = client.get("/auth/generate-password")
    assert response.status_code == 403


def test_generate_password_can_be_disabled():
    app = _build_app(role=UserRole.ADMIN, allow_endpoint=False)
    with TestClient(app) as client:
        response = client.get("/auth/generate-password")
    assert response.status_code == 403


def test_generate_password_returns_value_for_admin_when_enabled():
    app = _build_app(role=UserRole.ADMIN, allow_endpoint=True, temp_password_len=18)
    with TestClient(app) as client:
        response = client.get("/auth/generate-password")
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload.get("password"), str)
    assert len(payload["password"]) >= 18
