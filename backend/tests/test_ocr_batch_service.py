from pathlib import Path

import pytest

from backend.app.application.exceptions import ValidationError
from backend.app.application.ocr.ocr_batch_service import OcrBatchService


class _FakeRecognitionService:
    def __init__(self):
        self.calls = []

    async def recognize_passport_compensators(self, **kwargs):
        self.calls.append(("compensators", kwargs))
        return {"message": "ok", "filename": "pair", "data": {}}

    async def recognize_passport_rngs(self, **kwargs):
        self.calls.append(("rngs", kwargs))
        return {"message": "ok", "filename": "rngs", "data": {}}

    async def recognize_drawing(self, **kwargs):
        self.calls.append(("drawing", kwargs))
        return {"message": "ok", "filename": "drawing"}


@pytest.mark.asyncio
async def test_compensators_requires_even_file_count(tmp_path: Path):
    svc = OcrBatchService(recognition_service=_FakeRecognitionService())
    paths = []
    for idx in range(3):
        path = tmp_path / f"f{idx}.pdf"
        path.write_bytes(b"%PDF")
        paths.append(path)

    with pytest.raises(ValidationError):
        await svc.process_pdf_paths(
            kind="passport_compensators",
            pdf_paths=paths,
            pages_limit=0,
        )


@pytest.mark.asyncio
async def test_compensators_pairs_files_in_order(tmp_path: Path):
    fake = _FakeRecognitionService()
    svc = OcrBatchService(recognition_service=fake)
    paths = []
    for name in ("a.pdf", "b.pdf", "c.pdf", "d.pdf"):
        path = tmp_path / name
        path.write_bytes(b"%PDF")
        paths.append(path)

    progress_points = []

    async def capture_progress(progress: int, extra: dict | None = None):
        progress_points.append(progress)

    result = await svc.process_pdf_paths(
        kind="passport_compensators",
        pdf_paths=paths,
        pages_limit=0,
        on_progress=capture_progress,
    )

    assert [call[1]["diameter_file_name"] for call in fake.calls] == ["a.pdf", "c.pdf"]
    assert [call[1]["gost_materials_file_name"] for call in fake.calls] == ["b.pdf", "d.pdf"]
    assert result[0]["source_file"] == ["a.pdf", "b.pdf"]
    assert result[1]["source_file"] == ["c.pdf", "d.pdf"]
    assert progress_points[-1] == 100
