from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.dependencies import get_config, get_current_user
from backend.app.api.exception_handlers import register_exception_handlers
from backend.app.api.routers.pipelines import router as pipelines_router
from backend.app.infrastructure.db.models.user import UserRole


def _build_app(tmp_path) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(pipelines_router)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=101,
        username="demo_user",
        role=UserRole.DEMO,
        is_active=True,
    )
    app.dependency_overrides[get_config] = lambda: SimpleNamespace(
        upload_validation=SimpleNamespace(
            max_upload_size_mb=10,
            allowed_mime_pdf=["application/pdf", "application/octet-stream"],
        ),
        user_data=SimpleNamespace(base_path=str(tmp_path)),
    )
    return app


def test_pdf_drawing_check_rejects_multiple_files(tmp_path):
    app = _build_app(tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/pipelines/pdf-drawing-check",
            files=[
                ("files", ("one.pdf", b"%PDF-1.4 one", "application/pdf")),
                ("files", ("two.pdf", b"%PDF-1.4 two", "application/pdf")),
            ],
            data={"page": "1"},
        )
    assert response.status_code == 422
    payload = response.json()
    assert payload["details"]["reason"] == "single_file_required"


def test_pdf_drawing_check_returns_png_base64(monkeypatch, tmp_path):
    app = _build_app(tmp_path)

    def _fake_snapshots(pdf_path, *, page_num=1, resolution=150):
        assert page_num == 1
        assert str(pdf_path).endswith(".pdf")
        assert resolution == 150
        return (b"fake-params-png", b"fake-spec-png")

    monkeypatch.setattr(
        "backend.app.api.routers.pipelines.render_drawing_check_table_snapshots",
        _fake_snapshots,
    )

    with TestClient(app) as client:
        response = client.post(
            "/pipelines/pdf-drawing-check",
            files={"file": ("one.pdf", b"%PDF-1.4 one", "application/pdf")},
            data={"page": "1"},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["filename"] == "one.pdf"
    assert payload["page"] == 1
    assert payload["params_png_base64"] == "ZmFrZS1wYXJhbXMtcG5n"  # base64(b"fake-params-png")
    assert payload["spec_png_base64"] == "ZmFrZS1zcGVjLXBuZw=="  # base64(b"fake-spec-png")
