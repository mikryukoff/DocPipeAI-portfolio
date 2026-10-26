from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.application.exceptions import ForbiddenError, UnauthorizedError
from backend.app.application.security.audit_service import AuditService
from backend.app.application.app_logs_service import AppLogsService
from backend.app.application.parsing_logs_service import ParsingLogsService
from backend.app.application.security.demo_limit_service import DemoLimitService
from backend.app.config import load_config
from backend.app.infrastructure.db.database import get_async_session
from backend.app.infrastructure.db.models.user import UserORM, UserRole
from backend.app.infrastructure.repositories.pipeline_repository import PipelineRepository
from backend.app.infrastructure.repositories.spec_item_repository import SpecItemRepository
from backend.app.infrastructure.repositories.job_repository import JobRepository
from backend.app.infrastructure.repositories.checklist_repository import ChecklistRepository
from backend.app.infrastructure.repositories.user_repository import UserRepository
from backend.app.infrastructure.repositories.demo_limit_repository import DemoLimitRepository
from backend.app.infrastructure.repositories.audit_repository import AuditRepository
from backend.app.domain.pdf_import.pdf_pipeline_importer import PDFPipelineImporter
from backend.app.application.imports.pipeline_import_service import PipelineImportService
from backend.app.application.imports.pdf_batch_import_service import PdfBatchImportService
from backend.app.application.imports.excel_import_service import ExcelImportService
from backend.app.application.imports.excel_batch_import_service import ExcelBatchImportService
from backend.app.application.imports.word_batch_import_service import WordBatchImportService
from backend.app.application.imports.word_import_service import WordDocumentImportService
from backend.app.application.embedment.instrument_embedment_service import InstrumentEmbedmentService
from backend.app.application.ocr.ocr_batch_service import OcrBatchService
from backend.app.application.ocr.ocr_recognition_service import OcrRecognitionService
from backend.app.application.passports.passport_service import PassportService
from backend.app.application.jobs.job_service import JobService
from backend.app.security.file_encryption import FileEncryptionService
from backend.app.security.tokens import ACCESS_COOKIE_NAME, decode_access_token
from backend.app.infrastructure.db.database import AsyncSessionLocal
from backend.app.infrastructure.db.dependencies import pipeline_repo_factory
from backend.app.shared.user_data_paths import user_passports_dir


@lru_cache()
def get_config():
    return load_config()


def get_pipeline_repository(
    session: AsyncSession = Depends(get_async_session),
) -> PipelineRepository:
    return PipelineRepository(session)


def get_spec_item_repository(
    session: AsyncSession = Depends(get_async_session),
) -> SpecItemRepository:
    return SpecItemRepository(session)


def get_job_repository(
    session: AsyncSession = Depends(get_async_session),
) -> JobRepository:
    return JobRepository(session)


def get_job_service():
    return JobService(session_factory=AsyncSessionLocal)


def get_user_repository(
    session: AsyncSession = Depends(get_async_session),
) -> UserRepository:
    return UserRepository(session)


def get_checklist_repository(
    session: AsyncSession = Depends(get_async_session),
) -> ChecklistRepository:
    return ChecklistRepository(session)


def get_demo_limit_repository(
    session: AsyncSession = Depends(get_async_session),
) -> DemoLimitRepository:
    return DemoLimitRepository(session)


def get_audit_repository(
    session: AsyncSession = Depends(get_async_session),
) -> AuditRepository:
    return AuditRepository(session)


def get_demo_limit_service(
    repo: DemoLimitRepository = Depends(get_demo_limit_repository),
    config=Depends(get_config),
) -> DemoLimitService:
    return DemoLimitService(repo=repo, cfg=config)


def get_audit_service(
    repo: AuditRepository = Depends(get_audit_repository),
) -> AuditService:
    return AuditService(repo=repo)


def get_parsing_logs_service(
    config=Depends(get_config),
) -> ParsingLogsService:
    return ParsingLogsService(config=config)


def get_app_logs_service(
    config=Depends(get_config),
) -> AppLogsService:
    return AppLogsService(config=config)


@lru_cache
def get_file_encryption_service() -> FileEncryptionService:
    config = load_config()
    return FileEncryptionService(config.security.file_encryption_key)


async def get_current_user(
    request: Request,
    config=Depends(get_config),
    users: UserRepository = Depends(get_user_repository),
) -> UserORM:
    token = request.cookies.get(ACCESS_COOKIE_NAME)
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()
    if not token:
        raise UnauthorizedError("Authentication required")

    payload = decode_access_token(token, config)
    user_id = int(payload["sub"])
    user = await users.get_by_id(user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("Invalid user")
    return user


async def get_current_user_optional(
    request: Request,
    config=Depends(get_config),
    users: UserRepository = Depends(get_user_repository),
) -> UserORM | None:
    token = request.cookies.get(ACCESS_COOKIE_NAME)
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()
    if not token:
        return None
    try:
        payload = decode_access_token(token, config)
    except UnauthorizedError:
        return None
    user = await users.get_by_id(int(payload["sub"]))
    if user is None or not user.is_active:
        return None
    return user


def require_roles(roles: list[UserRole]):
    async def _guard(user: UserORM = Depends(get_current_user)) -> UserORM:
        if user.role not in roles:
            raise ForbiddenError("Insufficient permissions")
        return user

    return _guard


_pipeline_reader_guard = require_roles(
    [UserRole.ADMIN, UserRole.ENGINEER, UserRole.DEMO]
)
PipelineReaderUser = Annotated[UserORM, Depends(_pipeline_reader_guard)]


async def get_passport_service(
    current_user: PipelineReaderUser,
    repo: PipelineRepository = Depends(get_pipeline_repository),
    config=Depends(get_config),
) -> PassportService:
    output_dir = user_passports_dir(
        config, user_id=current_user.id, username=current_user.username
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    return PassportService(
        pipeline_repo=repo,
        template_path=Path(config.word_exporter.word_template_path),
        output_dir=output_dir,
        encryption_service=FileEncryptionService(config.security.file_encryption_key),
        remove_source_after_processing=config.security.remove_source_after_processing,
    )


def get_excel_import_service(
    config=Depends(get_config),
    job_service: JobService = Depends(get_job_service),
) -> ExcelImportService:
    return ExcelImportService(
        session_factory=AsyncSessionLocal,
        job_service=job_service,
        preview_output_dir=Path(config.excel_import.preview_output_dir),
    )


@lru_cache
def get_import_service() -> PipelineImportService:
    job_service = JobService(session_factory=AsyncSessionLocal)

    importer = PDFPipelineImporter(
        repo_factory=pipeline_repo_factory(session_factory=AsyncSessionLocal),
        job_service=job_service,
    )

    return PipelineImportService(
        job_service=job_service,
        importer=importer,
    )


@lru_cache
def get_pdf_batch_import_service() -> PdfBatchImportService:
    job_service = JobService(session_factory=AsyncSessionLocal)
    importer = PDFPipelineImporter(
        repo_factory=pipeline_repo_factory(session_factory=AsyncSessionLocal),
        job_service=job_service,
    )
    return PdfBatchImportService(job_service=job_service, importer=importer)


def get_excel_batch_import_service(
    config=Depends(get_config),
    job_service: JobService = Depends(get_job_service),
) -> ExcelBatchImportService:
    excel_import = ExcelImportService(
        session_factory=AsyncSessionLocal,
        job_service=job_service,
        preview_output_dir=Path(config.excel_import.preview_output_dir),
    )
    return ExcelBatchImportService(
        job_service=job_service,
        excel_import_service=excel_import,
    )


def get_word_batch_import_service(
    job_service: JobService = Depends(get_job_service),
) -> WordBatchImportService:
    return WordBatchImportService(
        job_service=job_service,
        word_import_service=WordDocumentImportService(session_factory=AsyncSessionLocal),
    )


def get_ocr_recognition_service() -> OcrRecognitionService:
    return OcrRecognitionService(session_factory=AsyncSessionLocal)


def get_ocr_batch_service(
    recognition_service: OcrRecognitionService = Depends(get_ocr_recognition_service),
) -> OcrBatchService:
    return OcrBatchService(recognition_service=recognition_service)


def get_instrument_embedment_service() -> InstrumentEmbedmentService:
    return InstrumentEmbedmentService()

