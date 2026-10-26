from pathlib import Path

import pytest

from backend.app.application.passports.passport_service import PassportService
from backend.app.security.file_encryption import FileEncryptionService


class _FakeRepo:
    async def get_by_name(self, name: str):
        return {"name": name}

    async def list_names(self) -> list[str]:
        return ["P-1"]


class _FakeExporter:
    def export(self, pipeline, path: Path) -> None:
        path.write_bytes(b"passport-content")


@pytest.mark.asyncio
async def test_generate_passport_cleans_plaintext_and_encrypted_when_enabled(tmp_path: Path):
    template = tmp_path / "template.docx"
    template.write_bytes(b"template")
    service = PassportService(
        pipeline_repo=_FakeRepo(),
        template_path=template,
        output_dir=tmp_path,
        encryption_service=FileEncryptionService("test-key"),
        remove_source_after_processing=True,
    )
    service.exporter = _FakeExporter()

    payload, filename = await service.generate_passport("P-1")
    assert filename == "P-1.docx"
    assert payload == b"passport-content"
    assert not (tmp_path / "P-1.docx").exists()
    assert not (tmp_path / "P-1.docx.enc").exists()


@pytest.mark.asyncio
async def test_generate_passport_keeps_only_encrypted_when_cleanup_disabled(tmp_path: Path):
    template = tmp_path / "template.docx"
    template.write_bytes(b"template")
    service = PassportService(
        pipeline_repo=_FakeRepo(),
        template_path=template,
        output_dir=tmp_path,
        encryption_service=FileEncryptionService("test-key"),
        remove_source_after_processing=False,
    )
    service.exporter = _FakeExporter()

    await service.generate_passport("P-2")
    assert not (tmp_path / "P-2.docx").exists()
    assert (tmp_path / "P-2.docx.enc").exists()
