from io import BytesIO
import zipfile
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks

from backend.app.api.routers.pipelines import PassportsZipRequest, download_passports_zip
from backend.app.application.exceptions import PipelineNotFoundError, ValidationError
from backend.app.infrastructure.db.models.user import UserRole


class _FakePassportService:
    def __init__(self, fail_on: str | None = None):
        self.fail_on = fail_on
        self.received_names = []

    async def generate_passports_zip(self, names: list[str]) -> tuple[bytes, str]:
        self.received_names = list(names)
        if self.fail_on and self.fail_on in names:
            raise KeyError(self.fail_on)

        stream = BytesIO()
        with zipfile.ZipFile(stream, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in names:
                archive.writestr(f"{name}.docx", b"ok")
        return stream.getvalue(), "passports.zip"


class _FakeDemoLimitService:
    def __init__(self):
        self.calls = 0

    async def check_and_increment(self, _: int) -> None:
        self.calls += 1


class _FakeAuditService:
    def __init__(self):
        self.calls = []

    async def log(self, **kwargs):
        self.calls.append(kwargs)


class _Cfg:
    class _UD:
        delete_generated_passports_after_download = False

    user_data = _UD()


@pytest.mark.asyncio
async def test_download_passports_zip_success():
    passport_service = _FakePassportService()
    demo_limit = _FakeDemoLimitService()
    audit = _FakeAuditService()
    current_user = SimpleNamespace(id=11, role=UserRole.ENGINEER)

    response = await download_passports_zip(
        current_user=current_user,
        background_tasks=BackgroundTasks(),
        config=_Cfg(),
        demo_limit_service=demo_limit,
        audit_service=audit,
        passport_service=passport_service,
        payload=PassportsZipRequest(pipeline_names=["A", "B", "A"]),
    )

    assert response.media_type == "application/zip"
    assert "filename=\"passports.zip\"" in response.headers["Content-Disposition"]
    assert passport_service.received_names == ["A", "B"]
    assert demo_limit.calls == 0
    assert len(audit.calls) == 1
    assert audit.calls[0]["details"]["pipelines_count"] == 2

    with zipfile.ZipFile(BytesIO(response.body), mode="r") as archive:
        assert sorted(archive.namelist()) == ["A.docx", "B.docx"]


@pytest.mark.asyncio
async def test_download_passports_zip_requires_names():
    passport_service = _FakePassportService()
    demo_limit = _FakeDemoLimitService()
    audit = _FakeAuditService()
    current_user = SimpleNamespace(id=22, role=UserRole.ADMIN)

    with pytest.raises(ValidationError):
        await download_passports_zip(
            current_user=current_user,
            background_tasks=BackgroundTasks(),
            config=_Cfg(),
            demo_limit_service=demo_limit,
            audit_service=audit,
            passport_service=passport_service,
            payload=PassportsZipRequest(pipeline_names=[]),
        )


@pytest.mark.asyncio
async def test_download_passports_zip_maps_not_found_and_checks_demo_limit():
    passport_service = _FakePassportService(fail_on="MISSING")
    demo_limit = _FakeDemoLimitService()
    audit = _FakeAuditService()
    current_user = SimpleNamespace(id=33, role=UserRole.DEMO)

    with pytest.raises(PipelineNotFoundError):
        await download_passports_zip(
            current_user=current_user,
            background_tasks=BackgroundTasks(),
            config=_Cfg(),
            demo_limit_service=demo_limit,
            audit_service=audit,
            passport_service=passport_service,
            payload=PassportsZipRequest(pipeline_names=["OK", "MISSING"]),
        )

    assert demo_limit.calls == 2
