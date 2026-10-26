"""API редактирования JSON в data/config (админ)."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.dependencies import get_audit_service, get_config, get_current_user
from backend.app.api.exception_handlers import register_exception_handlers
from backend.app.api.routers.admin_config_json import router as admin_config_json_router
from backend.app.domain.parsing import armature_gost_store as ags_mod
from backend.app.infrastructure.db.models.user import UserRole


def _cfg(tmp: Path):
    return SimpleNamespace(
        user_data=SimpleNamespace(
            config_path=str(tmp / "config"),
        ),
        ocr=SimpleNamespace(
            parsed_output_dir=str(tmp / "parsed"),
        ),
    )


@pytest.fixture
def admin_app(tmp_path: Path):
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_config_json_router)
    app.dependency_overrides[get_config] = lambda: _cfg(tmp_path)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=1,
        username="admin",
        role=UserRole.ADMIN,
        is_active=True,
    )
    app.dependency_overrides[get_audit_service] = lambda: SimpleNamespace(
        log=AsyncMock(),
    )
    return app


def test_list_config_json_empty(admin_app: FastAPI):
    with TestClient(admin_app) as client:
        r = client.get("/admin/config-json")
    assert r.status_code == 200
    assert r.json() == {"files": []}


def test_list_and_roundtrip(admin_app: FastAPI, tmp_path: Path):
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "alpha.json").write_text('{"x": 1}', encoding="utf-8")
    (cfg_dir / "beta.json").write_text("[]", encoding="utf-8")

    with TestClient(admin_app) as client:
        r = client.get("/admin/config-json")
        assert r.status_code == 200
        assert r.json()["files"] == ["alpha.json", "beta.json"]

        g = client.get("/admin/config-json/alpha.json")
        assert g.status_code == 200
        assert g.json()["filename"] == "alpha.json"
        assert g.json()["value"] == {"x": 1}

        p = client.put(
            "/admin/config-json/alpha.json",
            json={"value": {"x": 2, "y": "z"}},
        )
        assert p.status_code == 200
        assert p.json()["ok"] is True
        raw = (cfg_dir / "alpha.json").read_text(encoding="utf-8")
        assert '"x": 2' in raw
        assert '"y": "z"' in raw


def test_get_missing_returns_404(admin_app: FastAPI):
    with TestClient(admin_app) as client:
        r = client.get("/admin/config-json/nope.json")
    assert r.status_code == 404


def test_invalid_filename_rejected(admin_app: FastAPI):
    with TestClient(admin_app) as client:
        r = client.get("/admin/config-json/_bad.json")
    assert r.status_code == 422


def test_engineer_forbidden(admin_app: FastAPI):
    admin_app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=2,
        username="eng",
        role=UserRole.ENGINEER,
        is_active=True,
    )
    with TestClient(admin_app) as client:
        r = client.get("/admin/config-json")
    assert r.status_code == 403


def test_put_armature_gost_resets_store(admin_app: FastAPI, tmp_path: Path):
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "armature_gost.json").write_text("{}", encoding="utf-8")
    ags_mod._default_store = object()

    with TestClient(admin_app) as client:
        r = client.put(
            "/admin/config-json/armature_gost.json",
            json={"value": {"Клапан": "ГОСТ 1"}},
        )
    assert r.status_code == 200
    assert ags_mod._default_store is None


def test_list_settings_files_config_only(admin_app: FastAPI, tmp_path: Path):
    (tmp_path / "config").mkdir(parents=True)
    (tmp_path / "parsed").mkdir(parents=True)
    (tmp_path / "config" / "a.json").write_text("{}", encoding="utf-8")
    (tmp_path / "parsed" / "ignored.json").write_text("{}", encoding="utf-8")

    with TestClient(admin_app) as client:
        r = client.get("/admin/settings-files")
    assert r.status_code == 200
    data = r.json()
    assert len(data["entries"]) == 1
    assert data["entries"][0]["filename"] == "a.json"
    assert data["entries"][0]["source"] == "config"


def test_settings_files_content_roundtrip_config(admin_app: FastAPI, tmp_path: Path):
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "map.json").write_text('{"K": "v"}', encoding="utf-8")

    with TestClient(admin_app) as client:
        g = client.get(
            "/admin/settings-files/content",
            params={"filename": "map.json"},
        )
        assert g.status_code == 200
        assert g.json()["value"] == {"K": "v"}

        p = client.put(
            "/admin/settings-files/content",
            params={"filename": "map.json"},
            json={"value": {"K": "w"}},
        )
        assert p.status_code == 200
        raw = (cfg_dir / "map.json").read_text(encoding="utf-8")
        assert '"w"' in raw
