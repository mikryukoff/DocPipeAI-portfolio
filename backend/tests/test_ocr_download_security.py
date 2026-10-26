from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.dependencies import get_config, get_current_user
from backend.app.api.exception_handlers import register_exception_handlers
from backend.app.api.routers.ocr import router as ocr_router
from backend.app.infrastructure.db.models.user import UserRole


def _build_app(*, parsed_output_dir: Path, with_user: bool) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(ocr_router)
    app.dependency_overrides[get_config] = lambda: SimpleNamespace(
        ocr=SimpleNamespace(parsed_output_dir=str(parsed_output_dir))
    )
    if with_user:
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=101,
            username="engineer",
            role=UserRole.ENGINEER,
            is_active=True,
        )
    return app


def test_download_json_requires_auth(tmp_path: Path):
    parsed_dir = tmp_path / "parsed_texts"
    parsed_dir.mkdir(parents=True, exist_ok=True)
    (parsed_dir / "sample.json").write_text('{"ok": true}', encoding="utf-8")

    app = _build_app(parsed_output_dir=parsed_dir, with_user=False)
    with TestClient(app) as client:
        response = client.get("/api/download/sample")
    assert response.status_code == 401


def test_download_json_rejects_traversal_filename(tmp_path: Path):
    parsed_dir = tmp_path / "parsed_texts"
    parsed_dir.mkdir(parents=True, exist_ok=True)
    app = _build_app(parsed_output_dir=parsed_dir, with_user=True)

    with TestClient(app) as client:
        response = client.get("/api/download/..%5C..%5Csecret")
    assert response.status_code == 422


def test_download_json_deletes_file_after_successful_response(tmp_path: Path):
    parsed_dir = tmp_path / "parsed_texts"
    parsed_dir.mkdir(parents=True, exist_ok=True)
    target = parsed_dir / "drawing_1.json"
    target.write_text('{"pipeline":"A"}', encoding="utf-8")

    app = _build_app(parsed_output_dir=parsed_dir, with_user=True)
    with TestClient(app) as client:
        response = client.get("/api/download/drawing_1")
    assert response.status_code == 200
    assert response.json() == {"pipeline": "A"}
    assert not target.exists()
