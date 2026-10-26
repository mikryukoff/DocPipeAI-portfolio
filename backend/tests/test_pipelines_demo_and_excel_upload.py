from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.dependencies import (
    get_config,
    get_current_user,
    get_excel_batch_import_service,
    get_job_service,
)
from backend.app.api.exception_handlers import register_exception_handlers
from backend.app.api.routers.pipelines import router as pipelines_router
from backend.app.infrastructure.db.models.user import UserRole


class _FakeJobService:
    async def create(self, filename, extra=None, user_id=None):
        return SimpleNamespace(id=321, status="queued", extra=extra)

    async def update_progress(self, job_id, progress=None, extra=None):
        return None

    async def fail(self, job_id, reason):
        return None


class _FakeExcelBatchService:
    def __init__(self):
        self.last_excel_paths = []

    async def start_batch_import(self, job_id, excel_paths, user_log_key, job_workspace=None):
        self.last_excel_paths = list(excel_paths)
        return SimpleNamespace(id=job_id, status="processing")


class _FakeSpecSectionMappingStore:
    last_update_payload = None

    @staticmethod
    def allowed_sections_for_ui():
        return ["Трубы", "Арматура"]

    @staticmethod
    def allowed_tables_for_ui():
        return []

    @staticmethod
    def table_to_sections_map_for_ui():
        return {}

    def list_undefined(self):
        return ["Неразмеченный элемент"]

    def update_many(self, mapping):
        _FakeSpecSectionMappingStore.last_update_payload = dict(mapping or {})
        return len(mapping or {})


def _build_app(*, tmp_path: Path, batch_service: _FakeExcelBatchService) -> FastAPI:
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
            allowed_mime_excel=[
                "application/vnd.ms-excel",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ],
        ),
        user_data=SimpleNamespace(base_path=str(tmp_path)),
    )
    app.dependency_overrides[get_job_service] = lambda: _FakeJobService()
    app.dependency_overrides[get_excel_batch_import_service] = lambda: batch_service
    return app


def test_demo_can_access_undefined_spec_sections(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "backend.app.api.routers.pipelines.SpecSectionMappingStore",
        _FakeSpecSectionMappingStore,
    )
    batch_service = _FakeExcelBatchService()
    app = _build_app(tmp_path=tmp_path, batch_service=batch_service)

    with TestClient(app) as client:
        get_response = client.get("/pipelines/spec-sections/undefined")
        post_response = client.post("/pipelines/spec-sections", json={"тестовый ключ": "Трубы"})

    assert get_response.status_code == 200
    get_json = get_response.json()
    assert get_json["undefined_names"] == ["Неразмеченный элемент"]
    assert "allowed_tables" in get_json
    assert isinstance(get_json["allowed_tables"], list)
    assert len(get_json["allowed_tables"]) == 4
    assert get_json["table_to_sections"]["Таблица 4.2"] == ["Арматура"]
    assert post_response.status_code == 200
    assert post_response.json() == {"updated": 1}
    assert _FakeSpecSectionMappingStore.last_update_payload == {"тестовый ключ": "Трубы"}


def test_post_spec_sections_items_resolves_to_section(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "backend.app.api.routers.pipelines.SpecSectionMappingStore",
        _FakeSpecSectionMappingStore,
    )
    batch_service = _FakeExcelBatchService()
    app = _build_app(tmp_path=tmp_path, batch_service=batch_service)

    with TestClient(app) as client:
        post_response = client.post(
            "/pipelines/spec-sections",
            json={
                "items": [
                    {"name": "  Кран  ", "table": "Таблица 4.2"},
                    {
                        "name": "Отвод",
                        "table": "Таблица 4.1",
                        "section": "Соединительные детали",
                    },
                ],
            },
        )

    assert post_response.status_code == 200
    assert post_response.json() == {"updated": 2}
    assert _FakeSpecSectionMappingStore.last_update_payload == {
        "Кран": "Арматура",
        "Отвод": "Соединительные детали",
    }


def test_post_spec_sections_4_1_full_name_drives_infer(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "backend.app.api.routers.pipelines.SpecSectionMappingStore",
        _FakeSpecSectionMappingStore,
    )
    batch_service = _FakeExcelBatchService()
    app = _build_app(tmp_path=tmp_path, batch_service=batch_service)

    with TestClient(app) as client:
        post_response = client.post(
            "/pipelines/spec-sections",
            json={
                "items": [
                    {
                        "name": "Колено",
                        "table": "Таблица 4.1",
                        "full_name": "Труба стальная бесшовная DN50 Колено",
                    },
                ],
            },
        )

    assert post_response.status_code == 200
    assert _FakeSpecSectionMappingStore.last_update_payload == {"Колено": "Трубы"}


def test_post_spec_sections_items_4_1_resolves_section_from_name(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "backend.app.api.routers.pipelines.SpecSectionMappingStore",
        _FakeSpecSectionMappingStore,
    )
    batch_service = _FakeExcelBatchService()
    app = _build_app(tmp_path=tmp_path, batch_service=batch_service)

    with TestClient(app) as client:
        post_response = client.post(
            "/pipelines/spec-sections",
            json={"items": [{"name": "X", "table": "Таблица 4.1"}]},
        )

    assert post_response.status_code == 200
    assert post_response.json() == {"updated": 1}
    assert _FakeSpecSectionMappingStore.last_update_payload == {
        "X": "Соединительные детали",
    }


def test_excel_single_file_accepts_octet_stream(tmp_path: Path):
    batch_service = _FakeExcelBatchService()
    app = _build_app(tmp_path=tmp_path, batch_service=batch_service)

    with TestClient(app) as client:
        response = client.post(
            "/pipelines/from-excel",
            files={"file": ("single.xlsx", b"fake-excel-payload", "application/octet-stream")},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["job_id"] == 321
    assert payload["status"] == "processing"
    assert [p.name for p in batch_service.last_excel_paths] == ["single.xlsx"]
