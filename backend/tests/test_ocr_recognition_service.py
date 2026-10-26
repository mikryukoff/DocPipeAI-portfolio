import pytest

from backend.app.application.ocr.ocr_recognition_service import OcrRecognitionService


class _FakePdf:
    def __init__(self, pages_count: int):
        self.pages = [object() for _ in range(pages_count)]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_recognize_passport_rngs_uses_first_case_brand_as_material(monkeypatch):
    service = OcrRecognitionService(session_factory=lambda: None)

    monkeypatch.setattr(
        "backend.app.application.ocr.ocr_recognition_service.pdfplumber.open",
        lambda *_args, **_kwargs: _FakePdf(2),
    )

    async def fake_diameter(*_args, **_kwargs):
        return "Арматура XX01-V41000"

    async def fake_gost(*_args, **_kwargs):
        return "ТУ 22.19.30-002-46387464-2023"

    async def fake_table(*_args, **_kwargs):
        return ["12Х18Н10Т", "unused"]

    monkeypatch.setattr(
        "backend.app.application.ocr.ocr_recognition_service.ProcessPassport.process_passport_diameter",
        fake_diameter,
    )
    monkeypatch.setattr(
        "backend.app.application.ocr.ocr_recognition_service.ProcessPassport.process_passport_text_page",
        fake_gost,
    )
    monkeypatch.setattr(
        "backend.app.application.ocr.ocr_recognition_service.ProcessPassport.process_passport_table",
        fake_table,
    )

    captured = {}

    async def fake_update(**kwargs):
        captured.update(kwargs)
        return {
            "name_prefix": kwargs["name_prefix"],
            "found": 1,
            "updated": 1,
            "status": "updated",
        }

    monkeypatch.setattr(service, "_update_armature_rows", fake_update)

    progress_points = []

    async def capture_progress(progress: int, extra: dict | None = None):
        progress_points.append(progress)

    result = await service.recognize_passport_rngs(
        file_name="rngs.pdf",
        pdf_bytes=b"%PDF-1.4",
        pages_limit=0,
        on_progress=capture_progress,
    )

    assert captured["name_prefix"] == "Арматура XX01-V41000"
    assert captured["gost"] == "ТУ 22.19.30-002-46387464-2023"
    assert captured["material_grade"] == "12Х18Н10Т"
    assert result["db_update"]["updated_total"] == 1
    assert progress_points[0] == 5
    assert progress_points[-1] == 100


@pytest.mark.asyncio
async def test_recognize_passport_compensators_updates_by_dn_prefix(monkeypatch):
    service = OcrRecognitionService(session_factory=lambda: None)
    open_calls = {"count": 0}

    def fake_open(*_args, **_kwargs):
        open_calls["count"] += 1
        return _FakePdf(1)

    monkeypatch.setattr(
        "backend.app.application.ocr.ocr_recognition_service.pdfplumber.open",
        fake_open,
    )

    async def fake_diameter(*_args, **_kwargs):
        return "DN200"

    async def fake_page(*_args, **_kwargs):
        return {"gost": "ТУ 22.19.30-002-46387464-2023", "materials": "-"}

    monkeypatch.setattr(
        "backend.app.application.ocr.ocr_recognition_service.ProcessCompensators.process_compensators_diameter_page",
        fake_diameter,
    )
    monkeypatch.setattr(
        "backend.app.application.ocr.ocr_recognition_service.ProcessCompensators.process_compensators_page",
        fake_page,
    )

    captured = {}

    async def fake_update(**kwargs):
        captured.update(kwargs)
        return {
            "name_prefix": kwargs["name_prefix"],
            "found": 2,
            "updated": 2,
            "status": "updated",
        }

    monkeypatch.setattr(service, "_update_armature_rows", fake_update)

    progress_points = []

    async def capture_progress(progress: int, extra: dict | None = None):
        progress_points.append(progress)

    result = await service.recognize_passport_compensators(
        diameter_file_name="diameter.pdf",
        diameter_pdf_bytes=b"%PDF-1.4",
        gost_materials_file_name="gm.pdf",
        gost_materials_pdf_bytes=b"%PDF-1.4",
        on_progress=capture_progress,
    )

    assert open_calls["count"] == 2
    assert captured["name_prefix"] == "Компенсатор DN200"
    assert captured["gost"] == "ТУ 22.19.30-002-46387464-2023"
    assert captured["material_grade"] == "-"
    assert result["db_update"]["found_total"] == 2
    assert result["filename"] == "diameter__gm"
    assert progress_points[-1] == 100
