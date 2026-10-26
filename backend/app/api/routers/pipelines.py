from pathlib import Path
import asyncio
import base64
import tempfile
from time import time
from typing import Any

from fastapi import (
    APIRouter,
    UploadFile,
    File,
    Form,
    Depends,
    Request,
    WebSocket,
    WebSocketDisconnect,
    Query,
    Body,
    BackgroundTasks,
)
from fastapi import Response
from fastapi.responses import FileResponse
from loguru import logger

from backend.app.config import Config
from backend.app.api.dependencies import (
    get_audit_service,
    get_instrument_embedment_service,
    get_ocr_batch_service,
    get_passport_service,
    get_job_service,
    get_config,
    get_demo_limit_service,
    get_pdf_batch_import_service,
    get_excel_batch_import_service,
    get_word_batch_import_service,
    get_pipeline_repository,
    get_spec_item_repository,
    PipelineReaderUser,
    require_roles,
)
from backend.app.application.embedment.instrument_embedment_service import InstrumentEmbedmentService
from backend.app.application.ocr.ocr_batch_service import OcrBatchService
from backend.app.domain.parsing.drawing_4_store import get_drawing_4_store
from backend.app.api.schemas.pipelines import (
    InstrumentEmbedmentUpdate,
    PassportsZipRequest,
)
from backend.app.application.security.audit_service import AuditService
from backend.app.application.security.demo_limit_service import DemoLimitService
from backend.app.application.exceptions import (
    EmptyUploadError,
    ForbiddenError,
    PipelineNotFoundError,
    UnauthorizedError,
    ValidationError,
)
from backend.app.application.imports.excel_batch_import_service import (
    ExcelBatchImportService,
)
from backend.app.application.imports.pdf_batch_import_service import PdfBatchImportService
from backend.app.application.imports.word_batch_import_service import WordBatchImportService
from backend.app.application.passports.passport_service import PassportService
from backend.app.application.jobs.job_service import JobService
from backend.app.api.file_utils import save_upload_files, extract_archive
from backend.app.infrastructure.db.database import AsyncSessionLocal
from backend.app.infrastructure.db.models.job import JobStatus
from backend.app.infrastructure.db.models.user import UserORM, UserRole
from backend.app.infrastructure.repositories.pipeline_repository import PipelineRepository
from backend.app.infrastructure.repositories.spec_item_repository import SpecItemRepository
from backend.app.infrastructure.repositories.user_repository import UserRepository
from backend.app.infrastructure.files.pdf.pdf_table_debug_render import (
    render_drawing_check_table_snapshots,
)
from backend.app.security.tokens import ACCESS_COOKIE_NAME, decode_access_token
from backend.app.shared.job_workspace_cleanup import maybe_delete_job_workspace
from backend.app.shared.http_content_disposition import attachment_content_disposition
from backend.app.shared.passport_disk_cleanup import unlink_generated_passport_files
from backend.app.shared.user_data_paths import job_dir, job_uploads_dir, user_passports_dir
from backend.app.shared.user_log_key import format_user_log_key
from backend.app.domain.parsing.specification.spec_section_mapping_store import (
    SpecSectionMappingStore,
    UNDEFINED_SECTION_LABEL,
    USER_UNDEFINED_SECTION_LABEL,
    allowed_tables_for_ui,
    normalize_item_name,
    normalize_section_for_storage,
    resolve_table_choice_to_section_ru,
    table_to_sections_map_for_ui,
)
router = APIRouter(prefix="/pipelines", tags=["Pipelines"])
_WS_ALLOWED_ROLES = {UserRole.ADMIN, UserRole.ENGINEER, UserRole.DEMO}


def _apply_spec_sections_update_payload(
    store: SpecSectionMappingStore,
    payload: Any,
) -> int:
    """
    Принимает либо legacy-объект «ключ → раздел (строка)»,
    либо {"items": [{"name", "table", "section"?, "mark_not_spec"?}, ...]}.
    """
    if not isinstance(payload, dict):
        raise ValidationError(
            "Invalid request body",
            details={"reason": "expected_json_object"},
        )
    if "items" in payload:
        raw_items = payload.get("items")
        if not isinstance(raw_items, list):
            raise ValidationError(
                "Field items must be a list",
                details={"reason": "items_must_be_list"},
            )
        flat: dict[str, str] = {}
        for idx, raw in enumerate(raw_items):
            if not isinstance(raw, dict):
                continue
            name = normalize_item_name(str(raw.get("name") or ""))
            if not name:
                continue
            if raw.get("mark_not_spec") is True:
                flat[name] = USER_UNDEFINED_SECTION_LABEL
                continue
            table = str(raw.get("table") or "").strip()
            if not table:
                raise ValidationError(
                    "Укажите таблицу для элемента",
                    details={"reason": "table_required", "item": name, "index": idx},
                )
            section_raw = raw.get("section")
            section_ov = (
                section_raw.strip()
                if isinstance(section_raw, str) and section_raw.strip()
                else None
            )
            full_hint = normalize_item_name(
                str(raw.get("full_name") or raw.get("fullName") or "").strip()
            )
            infer_name = full_hint or name
            try:
                section_ru = resolve_table_choice_to_section_ru(
                    table, section_ov, item_name=infer_name
                )
            except ValueError as exc:
                reason = str(exc)
                if reason == "section_required":
                    msg = "Укажите раздел внутри выбранной таблицы"
                elif reason == "invalid_table":
                    msg = "Неизвестная таблица"
                elif reason == "invalid_section_for_table":
                    msg = "Раздел не соответствует выбранной таблице"
                else:
                    msg = "Ошибка сопоставления таблицы и раздела"
                raise ValidationError(
                    msg,
                    details={"reason": reason, "item": name, "table": table, "index": idx},
                ) from exc
            normalized = normalize_section_for_storage(section_ru)
            if normalized is None:
                raise ValidationError(
                    "Некорректный раздел после сопоставления",
                    details={"reason": "invalid_resolved_section", "item": name},
                )
            flat[name] = normalized
        return store.update_many(flat)

    legacy: dict[str, str] = {}
    for key, value in payload.items():
        if key == "items":
            continue
        if isinstance(value, str):
            legacy[str(key)] = value
    return store.update_many(legacy)


def _raise_empty_upload_for_source(
    *,
    archive: UploadFile | None,
    fallback_name: str,
) -> None:
    archive_name = Path(archive.filename or fallback_name).name if archive is not None else Path(fallback_name).name
    if archive is not None:
        raise ValidationError(
            "File validation failed",
            details={
                "files": [archive_name],
                "filename": archive_name,
                "reason": "archive_has_no_allowed_files",
                "stage": "archive_extract",
            },
        )
    raise EmptyUploadError()


def _get_request_id(request: Request | None) -> str:
    if request is None:
        return "N/A"
    return str(getattr(request.state, "request_id", "N/A"))


def _log_upload_stage(
    *,
    stage: str,
    request_id: str,
    user_id: int | None,
    filename: str | None = None,
    job_id: int | None = None,
    kind: str | None = None,
    extra: dict | None = None,
) -> None:
    logger.info(
        "Upload stage event. stage={} request_id={} user_id={} job_id={} kind={} filename={} extra={}",
        stage,
        request_id,
        user_id,
        job_id,
        kind or "N/A",
        filename or "N/A",
        extra or {},
    )


async def _update_progress_safe(job_service: JobService, *, job_id: int, extra: dict) -> None:
    try:
        await job_service.update_progress(job_id, extra=extra)
    except Exception:
        logger.exception("Failed to update job progress. job_id={}", job_id)


def _schedule_background_task(coro: Any, *, task_name: str, job_id: int) -> None:
    task = asyncio.create_task(coro)

    def _on_done(done_task: asyncio.Task) -> None:
        try:
            done_task.result()
        except asyncio.CancelledError:
            logger.warning("Background task cancelled. task_name={} job_id={}", task_name, job_id)
        except Exception:
            logger.exception("Background task failed unexpectedly. task_name={} job_id={}", task_name, job_id)

    task.add_done_callback(_on_done)


async def _fail_job_safe(job_service: JobService, *, job_id: int, reason: str) -> None:
    try:
        await job_service.fail(job_id, reason)
    except Exception:
        logger.exception("Failed to mark job as ERROR. job_id={}", job_id)


def _schedule_passport_disk_cleanup(
    background_tasks: BackgroundTasks,
    cfg: Config,
    user: UserORM,
    pipeline_names: list[str],
) -> None:
    if not cfg.user_data.delete_generated_passports_after_download:
        return
    out = user_passports_dir(cfg, user_id=user.id, username=user.username)
    background_tasks.add_task(unlink_generated_passport_files, out, list(pipeline_names))


async def _run_ocr_pdf_import_background(
    job_service: JobService,
    ocr_batch_service: OcrBatchService,
    *,
    job_id: int,
    kind: str,
    pdf_paths: list[Path],
    pages_limit: int,
    job_workspace: str | None = None,
) -> None:
    """Фоновая OCR-обработка: HTTP отвечает сразу с job_id, прогресс — через WebSocket."""
    started_at = time()
    try:

        async def emit(progress: int, extra: dict | None = None) -> None:
            m = dict(extra or {})
            m["duration_sec"] = round(time() - started_at, 2)
            await job_service.update_progress(job_id, progress=progress, extra=m)

        results = await ocr_batch_service.process_pdf_paths(
            kind=kind,
            pdf_paths=pdf_paths,
            pages_limit=pages_limit,
            on_progress=emit,
        )
        fin_extra: dict = {"duration_sec": round(time() - started_at, 2)}
        if results:
            last = results[-1]
            if isinstance(last, dict):
                fn = last.get("filename")
                if fn:
                    fin_extra["ocr_download_stem"] = str(fn)
        await job_service.update_progress(job_id, extra=fin_extra)
        await job_service.finish(job_id, progress=100)
    except Exception as exc:
        logger.exception("OCR PDF import failed. job_id={}", job_id)
        await _update_progress_safe(
            job_service,
            job_id=job_id,
            extra={"duration_sec": round(time() - started_at, 2)},
        )
        await _fail_job_safe(job_service, job_id=job_id, reason=str(exc))
    finally:
        maybe_delete_job_workspace(job_workspace=job_workspace, job_id=job_id)


async def _authorize_ws_user(websocket: WebSocket, *, config: Config) -> UserORM:
    token = websocket.cookies.get(ACCESS_COOKIE_NAME)
    if not token:
        auth_header = websocket.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()
    if not token:
        raise UnauthorizedError("Authentication required")

    payload = decode_access_token(token, config)
    user_id = int(payload["sub"])
    async with AsyncSessionLocal() as session:
        users = UserRepository(session)
        user = await users.get_by_id(user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("Invalid user")
    if user.role not in _WS_ALLOWED_ROLES:
        raise ForbiddenError("Insufficient permissions")
    return user


# Тип PDF для POST /from-pdf (маршрутизация на импорт трубопроводов или OCR-обработчики).
PDF_IMPORT_KIND_PIPELINE = "pipeline_drawings"
PDF_IMPORT_KIND_INSTRUMENT = "instrument_drawings"
PDF_IMPORT_KIND_COMPENSATORS = "passport_compensators"
PDF_IMPORT_KIND_RNGS = "passport_rngs"
PDF_IMPORT_KIND_VIK = "passport_vik"
PDF_IMPORT_KIND_PIPELINES_TESTS = "pipelines_tests"
_PDF_IMPORT_KINDS = frozenset(
    {
        PDF_IMPORT_KIND_PIPELINE,
        PDF_IMPORT_KIND_INSTRUMENT,
        PDF_IMPORT_KIND_COMPENSATORS,
        PDF_IMPORT_KIND_RNGS,
        PDF_IMPORT_KIND_VIK,
        PDF_IMPORT_KIND_PIPELINES_TESTS,
    }
)


@router.post("/from-pdf")
async def import_from_pdf(
    request: Request,
    file: UploadFile | None = File(default=None),
    files: list[UploadFile] | None = File(default=None),
    archive: UploadFile | None = File(default=None),
    pdf_import_kind: str = Form(PDF_IMPORT_KIND_PIPELINE),
    pages_limit: int = Form(0),
    config: Config = Depends(get_config),
    batch_service: PdfBatchImportService = Depends(get_pdf_batch_import_service),
    job_service: JobService = Depends(get_job_service),
    ocr_batch_service: OcrBatchService = Depends(get_ocr_batch_service),
    current_user: UserORM = Depends(require_roles([UserRole.ADMIN, UserRole.ENGINEER, UserRole.DEMO])),
):
    request_id = _get_request_id(request)
    # Фоллбек: если архивный файл пришёл в поле "file", обрабатываем как архив.
    if (
        archive is None
        and file is not None
        and file.filename
        and Path(file.filename).suffix.lower() in {".zip", ".rar"}
    ):
        archive, file = file, None

    if archive is not None and (file is not None or files):
        raise ValidationError(
            "Provide either files or archive, not both",
            details={
                "reason": "files_or_archive_conflict",
                "stage": "upload_validation",
            },
        )

    upload_files: list[UploadFile] = []
    if file is not None:
        upload_files.append(file)
    if files:
        upload_files.extend(files)

    kind = (pdf_import_kind or PDF_IMPORT_KIND_PIPELINE).strip()
    if kind not in _PDF_IMPORT_KINDS:
        raise ValidationError(
            "Неизвестный тип PDF-импорта",
            details={
                "reason": "unknown_import_kind",
                "stage": "upload_validation",
                "field": "pdf_import_kind",
                "provided_value": kind,
                "allowed_values": sorted(_PDF_IMPORT_KINDS),
            },
        )

    user_log_key = format_user_log_key(
        user_id=current_user.id, username=current_user.username
    )
    if archive is not None:
        job_filename = Path(archive.filename or "archive.zip").name
    elif upload_files:
        job_filename = Path(upload_files[0].filename or "upload.pdf").name
    else:
        raise EmptyUploadError()

    _log_upload_stage(
        stage="upload_received",
        request_id=request_id,
        user_id=current_user.id,
        filename=job_filename,
        kind=kind,
        extra={
            "has_archive": archive is not None,
            "files_count": len(upload_files),
        },
    )

    max_size = config.upload_validation.max_upload_size_mb * 1024 * 1024

    if kind == PDF_IMPORT_KIND_PIPELINE:
        allowed_exts = {".pdf"}
        job = await job_service.create(
            job_filename,
            extra={
                "source": "pdf",
                "mode": "batch",
                "pdf_import_kind": kind,
                "user_log_key": user_log_key,
                "request_id": request_id,
                "files_total": 0,
                "files_processed": 0,
                "files": [],
            },
            user_id=current_user.id,
        )
        pdf_upload_dir = job_uploads_dir(
            config,
            user_id=current_user.id,
            username=current_user.username,
            job_id=job.id,
        )
        pdf_upload_dir.mkdir(parents=True, exist_ok=True)
        ws = str(
            job_dir(
                config,
                user_id=current_user.id,
                username=current_user.username,
                job_id=job.id,
            ).resolve()
        )
        try:
            _log_upload_stage(
                stage="upload_validation_start",
                request_id=request_id,
                user_id=current_user.id,
                job_id=job.id,
                filename=job_filename,
                kind=kind,
            )
            if archive is not None:
                pdf_paths = extract_archive(
                    archive,
                    pdf_upload_dir,
                    allowed_exts,
                    allowed_mime_types=set(config.upload_validation.allowed_mime_archive),
                    max_size_bytes=max_size,
                )
            else:
                pdf_paths = save_upload_files(
                    upload_files,
                    pdf_upload_dir,
                    allowed_exts,
                    allowed_mime_types=set(config.upload_validation.allowed_mime_pdf),
                    max_size_bytes=max_size,
                )
            if not pdf_paths:
                _raise_empty_upload_for_source(
                    archive=archive,
                    fallback_name=job_filename,
                )
            _log_upload_stage(
                stage="upload_validation_done",
                request_id=request_id,
                user_id=current_user.id,
                job_id=job.id,
                filename=job_filename,
                kind=kind,
                extra={"accepted_files": [p.name for p in pdf_paths]},
            )
        except Exception as exc:
            logger.exception(
                "PDF upload failed before batch start. request_id={} user_id={} job_id={} kind={} filename={}",
                request_id,
                current_user.id,
                job.id,
                kind,
                job_filename,
            )
            await _fail_job_safe(job_service, job_id=job.id, reason=str(exc))
            maybe_delete_job_workspace(job_workspace=ws, job_id=job.id)
            raise

        await job_service.update_progress(
            job.id,
            extra={
                "files": [p.name for p in pdf_paths],
                "files_total": len(pdf_paths),
            },
        )
        logger.info(
            "PDF uploaded. kind={} files_count={} first_file={}",
            kind,
            len(pdf_paths),
            pdf_paths[0].name if pdf_paths else "N/A",
        )
        job = await batch_service.start_batch_import(
            job.id,
            pdf_paths,
            user_log_key,
            job_workspace=ws,
        )
        logger.info("PDF batch import job created. job_id={} files={}", job.id, len(pdf_paths))
        return {
            "import_kind": kind,
            "job_id": job.id,
            "status": job.status,
        }

    allowed_exts = {".pdf"}
    lim = max(0, int(pages_limit or 0))
    ocr_job = await job_service.create(
        job_filename,
        extra={
            "ocr_kind": kind,
            "source": "ocr_pdf",
            "user_log_key": user_log_key,
            "request_id": request_id,
            "files_total": 0,
            "files_processed": 0,
            "files": [],
        },
        user_id=current_user.id,
    )
    ocr_upload_dir = job_uploads_dir(
        config,
        user_id=current_user.id,
        username=current_user.username,
        job_id=ocr_job.id,
    )
    ocr_upload_dir.mkdir(parents=True, exist_ok=True)
    ocr_ws = str(
        job_dir(
            config,
            user_id=current_user.id,
            username=current_user.username,
            job_id=ocr_job.id,
        ).resolve()
    )
    try:
        _log_upload_stage(
            stage="upload_validation_start",
            request_id=request_id,
            user_id=current_user.id,
            job_id=ocr_job.id,
            filename=job_filename,
            kind=kind,
        )
        if archive is not None:
            ocr_pdf_paths = extract_archive(
                archive,
                ocr_upload_dir,
                allowed_exts,
                allowed_mime_types=set(config.upload_validation.allowed_mime_archive),
                max_size_bytes=max_size,
            )
        else:
            if not upload_files:
                raise EmptyUploadError()
            ocr_pdf_paths = save_upload_files(
                upload_files,
                ocr_upload_dir,
                allowed_exts,
                allowed_mime_types=set(config.upload_validation.allowed_mime_pdf),
                max_size_bytes=max_size,
            )
        if not ocr_pdf_paths:
            _raise_empty_upload_for_source(
                archive=archive,
                fallback_name=job_filename,
            )
        _log_upload_stage(
            stage="upload_validation_done",
            request_id=request_id,
            user_id=current_user.id,
            job_id=ocr_job.id,
            filename=job_filename,
            kind=kind,
            extra={"accepted_files": [p.name for p in ocr_pdf_paths]},
        )
    except Exception as exc:
        logger.exception(
            "OCR upload failed before processing start. request_id={} user_id={} job_id={} kind={} filename={}",
            request_id,
            current_user.id,
            ocr_job.id,
            kind,
            job_filename,
        )
        await _fail_job_safe(job_service, job_id=ocr_job.id, reason=str(exc))
        maybe_delete_job_workspace(job_workspace=ocr_ws, job_id=ocr_job.id)
        raise

    await job_service.update_progress(
        ocr_job.id,
        extra={
            "files": [p.name for p in ocr_pdf_paths],
            "files_total": len(ocr_pdf_paths),
        },
    )
    logger.info(
        "PDF uploaded. kind={} files_count={} first_file={}",
        kind,
        len(ocr_pdf_paths),
        ocr_pdf_paths[0].name if ocr_pdf_paths else "N/A",
    )
    await job_service.start_processing(ocr_job.id)
    _schedule_background_task(
        _run_ocr_pdf_import_background(
            job_service,
            ocr_batch_service,
            job_id=ocr_job.id,
            kind=kind,
            pdf_paths=list(ocr_pdf_paths),
            pages_limit=lim,
            job_workspace=ocr_ws,
        ),
        task_name="ocr_pdf_import",
        job_id=ocr_job.id,
    )
    logger.info(
        "PDF OCR branch scheduled. job_id={} kind={} files={}",
        ocr_job.id,
        kind,
        len(ocr_pdf_paths),
    )
    return {
        "import_kind": kind,
        "job_id": ocr_job.id,
        "status": ocr_job.status,
    }


@router.post("/pdf-drawing-check")
async def check_pdf_drawing(
    file: UploadFile | None = File(default=None),
    files: list[UploadFile] | None = File(default=None),
    page: int = Form(1),
    config: Config = Depends(get_config),
    _: UserORM = Depends(require_roles([UserRole.ADMIN, UserRole.ENGINEER, UserRole.DEMO])),
):
    upload_files: list[UploadFile] = []
    if file is not None:
        upload_files.append(file)
    if files:
        upload_files.extend(files)
    if not upload_files:
        raise EmptyUploadError()
    if len(upload_files) != 1:
        raise ValidationError(
            "Для проверки нужен ровно один PDF-файл",
            details={
                "reason": "single_file_required",
                "stage": "upload_validation",
                "files_count": len(upload_files),
            },
        )
    if page < 1:
        raise ValidationError(
            "Некорректный номер страницы",
            details={"reason": "invalid_page", "page": page},
        )

    max_size = config.upload_validation.max_upload_size_mb * 1024 * 1024
    with tempfile.TemporaryDirectory(prefix="pdf_check_") as tmp:
        saved = save_upload_files(
            upload_files,
            Path(tmp),
            {".pdf"},
            allowed_mime_types=set(config.upload_validation.allowed_mime_pdf),
            max_size_bytes=max_size,
        )
        if not saved:
            raise EmptyUploadError()
        pdf_path = saved[0]

        def _snapshots() -> tuple[bytes, bytes]:
            return render_drawing_check_table_snapshots(pdf_path, page_num=page)

        try:
            params_png, spec_png = await asyncio.to_thread(_snapshots)
        except ValueError as exc:
            raise ValidationError(
                str(exc),
                details={"reason": "invalid_page", "page": page},
            ) from exc

    return {
        "filename": pdf_path.name,
        "page": page,
        "params_png_base64": base64.standard_b64encode(params_png).decode("ascii"),
        "spec_png_base64": base64.standard_b64encode(spec_png).decode("ascii"),
    }


@router.post("/from-excel")
async def import_from_excel(
    request: Request,
    file: UploadFile | None = File(default=None),
    files: list[UploadFile] | None = File(default=None),
    archive: UploadFile | None = File(default=None),
    config: Config = Depends(get_config),
    batch_service: ExcelBatchImportService = Depends(get_excel_batch_import_service),
    job_service: JobService = Depends(get_job_service),
    current_user: UserORM = Depends(require_roles([UserRole.ADMIN, UserRole.ENGINEER, UserRole.DEMO])),
):
    request_id = _get_request_id(request)
    # Фоллбек: если архивный файл пришёл в поле "file", обрабатываем как архив.
    if (
        archive is None
        and file is not None
        and file.filename
        and Path(file.filename).suffix.lower() in {".zip", ".rar"}
    ):
        archive, file = file, None

    if archive is not None and (file is not None or files):
        raise ValidationError(
            "Provide either files or archive, not both",
            details={
                "reason": "files_or_archive_conflict",
                "stage": "upload_validation",
            },
        )

    upload_files: list[UploadFile] = []
    if file is not None:
        upload_files.append(file)
    if files:
        upload_files.extend(files)

    user_log_key = format_user_log_key(
        user_id=current_user.id, username=current_user.username
    )
    if archive is not None:
        job_filename = Path(archive.filename or "archive.zip").name
    elif upload_files:
        job_filename = Path(upload_files[0].filename or "upload.xlsx").name
    else:
        raise EmptyUploadError()

    _log_upload_stage(
        stage="upload_received",
        request_id=request_id,
        user_id=current_user.id,
        filename=job_filename,
        kind="excel_batch",
        extra={
            "has_archive": archive is not None,
            "files_count": len(upload_files),
        },
    )

    job = await job_service.create(
        job_filename,
        extra={
            "source": "excel",
            "mode": "batch",
            "user_log_key": user_log_key,
            "request_id": request_id,
            "files_total": 0,
            "files_processed": 0,
            "files": [],
        },
        user_id=current_user.id,
    )
    excel_upload_dir = job_uploads_dir(
        config,
        user_id=current_user.id,
        username=current_user.username,
        job_id=job.id,
    )
    excel_upload_dir.mkdir(parents=True, exist_ok=True)

    allowed_exts = {".xlsx", ".xlsm", ".xls"}
    # Browsers occasionally send Excel uploads as application/octet-stream.
    excel_allowed_mime_types = set(config.upload_validation.allowed_mime_excel) | {
        "application/octet-stream"
    }
    max_size = config.upload_validation.max_upload_size_mb * 1024 * 1024
    ws = str(
        job_dir(
            config,
            user_id=current_user.id,
            username=current_user.username,
            job_id=job.id,
        ).resolve()
    )
    try:
        _log_upload_stage(
            stage="upload_validation_start",
            request_id=request_id,
            user_id=current_user.id,
            job_id=job.id,
            filename=job_filename,
            kind="excel_batch",
        )
        if archive is not None:
            excel_paths = extract_archive(
                archive,
                excel_upload_dir,
                allowed_exts,
                allowed_mime_types=set(config.upload_validation.allowed_mime_archive),
                max_size_bytes=max_size,
            )
        else:
            if not upload_files:
                raise EmptyUploadError()
            excel_paths = save_upload_files(
                upload_files,
                excel_upload_dir,
                allowed_exts,
                allowed_mime_types=excel_allowed_mime_types,
                max_size_bytes=max_size,
            )
        if not excel_paths:
            _raise_empty_upload_for_source(
                archive=archive,
                fallback_name=job_filename,
            )
        _log_upload_stage(
            stage="upload_validation_done",
            request_id=request_id,
            user_id=current_user.id,
            job_id=job.id,
            filename=job_filename,
            kind="excel_batch",
            extra={"accepted_files": [p.name for p in excel_paths]},
        )
    except Exception as exc:
        logger.exception(
            "Excel upload failed before batch start. request_id={} user_id={} job_id={} filename={}",
            request_id,
            current_user.id,
            job.id,
            job_filename,
        )
        await _fail_job_safe(job_service, job_id=job.id, reason=str(exc))
        maybe_delete_job_workspace(job_workspace=ws, job_id=job.id)
        raise

    await job_service.update_progress(
        job.id,
        extra={
            "files": [p.name for p in excel_paths],
            "files_total": len(excel_paths),
        },
    )

    logger.info(
        "Excel batch uploaded. files_count={} first_file={}",
        len(excel_paths),
        excel_paths[0].name if excel_paths else "N/A",
    )

    job = await batch_service.start_batch_import(
        job.id,
        excel_paths,
        user_log_key,
        job_workspace=ws,
    )
    logger.info("Excel batch import job created. job_id={} files={}", job.id, len(excel_paths))

    return {
        "job_id": job.id,
        "status": job.status,
    }


# Импорт Word (.docx): ВИК и испытания — отдельно от PDF/OCR.
WORD_IMPORT_KIND_VIK = "passport_vik"
WORD_IMPORT_KIND_PIPELINES_TESTS = "pipelines_tests"
_WORD_IMPORT_KINDS = frozenset(
    {
        WORD_IMPORT_KIND_VIK,
        WORD_IMPORT_KIND_PIPELINES_TESTS,
    }
)


@router.post("/from-word")
async def import_from_word(
    request: Request,
    file: UploadFile | None = File(default=None),
    files: list[UploadFile] | None = File(default=None),
    archive: UploadFile | None = File(default=None),
    word_import_kind: str = Form(WORD_IMPORT_KIND_VIK),
    pages_limit: int = Form(0),
    config: Config = Depends(get_config),
    batch_service: WordBatchImportService = Depends(get_word_batch_import_service),
    job_service: JobService = Depends(get_job_service),
    current_user: UserORM = Depends(require_roles([UserRole.ADMIN, UserRole.ENGINEER, UserRole.DEMO])),
):
    request_id = _get_request_id(request)
    if (
        archive is None
        and file is not None
        and file.filename
        and Path(file.filename).suffix.lower() in {".zip", ".rar"}
    ):
        archive, file = file, None

    if archive is not None and (file is not None or files):
        raise ValidationError(
            "Provide either files or archive, not both",
            details={
                "reason": "files_or_archive_conflict",
                "stage": "upload_validation",
            },
        )

    upload_files: list[UploadFile] = []
    if file is not None:
        upload_files.append(file)
    if files:
        upload_files.extend(files)

    kind = (word_import_kind or WORD_IMPORT_KIND_VIK).strip()
    if kind not in _WORD_IMPORT_KINDS:
        raise ValidationError(
            "Неизвестный тип импорта Word",
            details={
                "reason": "unknown_import_kind",
                "stage": "upload_validation",
                "field": "word_import_kind",
                "provided_value": kind,
                "allowed_values": sorted(_WORD_IMPORT_KINDS),
            },
        )

    user_log_key = format_user_log_key(
        user_id=current_user.id, username=current_user.username
    )
    if archive is not None:
        job_filename = Path(archive.filename or "archive.zip").name
    elif upload_files:
        job_filename = Path(upload_files[0].filename or "upload.docx").name
    else:
        raise EmptyUploadError()

    _log_upload_stage(
        stage="upload_received",
        request_id=request_id,
        user_id=current_user.id,
        filename=job_filename,
        kind=kind,
        extra={
            "has_archive": archive is not None,
            "files_count": len(upload_files),
        },
    )

    job = await job_service.create(
        job_filename,
        extra={
            "source": "word",
            "mode": "batch",
            "word_import_kind": kind,
            "user_log_key": user_log_key,
            "request_id": request_id,
            "files_total": 0,
            "files_processed": 0,
            "files": [],
        },
        user_id=current_user.id,
    )
    word_upload_dir = job_uploads_dir(
        config,
        user_id=current_user.id,
        username=current_user.username,
        job_id=job.id,
    )
    word_upload_dir.mkdir(parents=True, exist_ok=True)

    allowed_exts = {".docx"}
    max_size = config.upload_validation.max_upload_size_mb * 1024 * 1024
    word_mime_types = {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
    ws = str(
        job_dir(
            config,
            user_id=current_user.id,
            username=current_user.username,
            job_id=job.id,
        ).resolve()
    )
    try:
        _log_upload_stage(
            stage="upload_validation_start",
            request_id=request_id,
            user_id=current_user.id,
            job_id=job.id,
            filename=job_filename,
            kind=kind,
        )
        if archive is not None:
            docx_paths = extract_archive(
                archive,
                word_upload_dir,
                allowed_exts,
                allowed_mime_types=set(config.upload_validation.allowed_mime_archive),
                max_size_bytes=max_size,
            )
        else:
            if not upload_files:
                raise EmptyUploadError()
            docx_paths = save_upload_files(
                upload_files,
                word_upload_dir,
                allowed_exts,
                allowed_mime_types=word_mime_types,
                max_size_bytes=max_size,
            )
        if not docx_paths:
            _raise_empty_upload_for_source(
                archive=archive,
                fallback_name=job_filename,
            )
        _log_upload_stage(
            stage="upload_validation_done",
            request_id=request_id,
            user_id=current_user.id,
            job_id=job.id,
            filename=job_filename,
            kind=kind,
            extra={"accepted_files": [p.name for p in docx_paths]},
        )
    except Exception as exc:
        logger.exception(
            "Word upload failed before batch start. request_id={} user_id={} job_id={} kind={} filename={}",
            request_id,
            current_user.id,
            job.id,
            kind,
            job_filename,
        )
        await _fail_job_safe(job_service, job_id=job.id, reason=str(exc))
        maybe_delete_job_workspace(job_workspace=ws, job_id=job.id)
        raise

    await job_service.update_progress(
        job.id,
        extra={
            "files": [p.name for p in docx_paths],
            "files_total": len(docx_paths),
        },
    )

    logger.info(
        "Word batch uploaded. kind={} files_count={} first_file={}",
        kind,
        len(docx_paths),
        docx_paths[0].name if docx_paths else "N/A",
    )

    lim = max(0, int(pages_limit or 0))
    await batch_service.start_batch_import(
        job.id,
        docx_paths,
        word_import_kind=kind,
        pages_limit=lim,
        user_log_key=user_log_key,
        job_workspace=ws,
    )
    logger.info("Word batch import job created. job_id={} files={}", job.id, len(docx_paths))

    return {
        "import_kind": kind,
        "job_id": job.id,
        "status": job.status,
    }


@router.get("/all")
async def get_all_pipelines_names(
    _user: PipelineReaderUser,
    passport_service: PassportService = Depends(get_passport_service),
):
    pipeline_names = await passport_service.get_all_pipelines_names()
    return {"pipeline_names": pipeline_names}


@router.post("/passports/zip")
async def download_passports_zip(
    current_user: PipelineReaderUser,
    background_tasks: BackgroundTasks,
    config: Config = Depends(get_config),
    demo_limit_service: DemoLimitService = Depends(get_demo_limit_service),
    audit_service: AuditService = Depends(get_audit_service),
    passport_service: PassportService = Depends(get_passport_service),
    payload: PassportsZipRequest = Body(default_factory=PassportsZipRequest),
):
    names = []
    seen = set()
    for name in payload.pipeline_names:
        clean = (name or "").strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        names.append(clean)

    if not names:
        raise ValidationError("Не переданы имена трубопроводов для выгрузки")
    if len(names) > 500:
        raise ValidationError("Слишком много трубопроводов для одной выгрузки")

    if current_user.role == UserRole.DEMO:
        for _ in names:
            await demo_limit_service.check_and_increment(current_user.id)

    try:
        archive_payload, archive_name = await passport_service.generate_passports_zip(names)
    except KeyError as exc:
        pipeline_name = exc.args[0] if exc.args else ""
        raise PipelineNotFoundError(pipeline_name) from exc

    await audit_service.log(
        user_id=current_user.id,
        action="passport_bulk_download",
        details={"pipelines_count": len(names), "pipeline_names": names[:50]},
    )

    _schedule_passport_disk_cleanup(background_tasks, config, current_user, names)

    return Response(
        content=archive_payload,
        media_type="application/zip",
        headers=attachment_content_disposition(archive_name),
    )


@router.get("/{pipeline_name}/passport")
async def get_passport(
    pipeline_name: str,
    current_user: PipelineReaderUser,
    background_tasks: BackgroundTasks,
    config: Config = Depends(get_config),
    demo_limit_service: DemoLimitService = Depends(get_demo_limit_service),
    audit_service: AuditService = Depends(get_audit_service),
    passport_service: PassportService = Depends(get_passport_service),
):
    if current_user.role == UserRole.DEMO:
        await demo_limit_service.check_and_increment(current_user.id)
    try:
        payload, filename = await passport_service.generate_passport(pipeline_name)
    except KeyError as exc:
        raise PipelineNotFoundError(pipeline_name) from exc
    await audit_service.log(
        user_id=current_user.id,
        action="passport_download",
        details={"pipeline_name": pipeline_name},
    )

    _schedule_passport_disk_cleanup(
        background_tasks, config, current_user, [pipeline_name]
    )

    return Response(
        content=payload,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers=attachment_content_disposition(filename),
    )


@router.get("/jobs/active")
async def get_active_job(
    job_service: JobService = Depends(get_job_service),
    _: UserORM = Depends(require_roles([UserRole.ADMIN, UserRole.ENGINEER, UserRole.DEMO])),
):
    job = await job_service.get_active_job()
    if not job:
        return {"job_id": None}

    return {
        "job_id": job.id,
        "status": job.status,
        "progress": job.progress,
        "error": job.error,
        "stats": job.extra,
    }


@router.get("/jobs/{job_id}")
async def get_job_status(
    job_id: int,
    job_service: JobService = Depends(get_job_service),
    _: UserORM = Depends(require_roles([UserRole.ADMIN, UserRole.ENGINEER, UserRole.DEMO])),
):
    job = await job_service.get_status(job_id)
    logger.debug("Job status requested. job_id={} status={} progress={}", job_id, job.status, job.progress)

    return {
        "status": job.status,
        "progress": job.progress,
        "error": job.error,
        "stats": job.extra
    }


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(
    job_id: int,
    job_service: JobService = Depends(get_job_service),
    current_user: UserORM = Depends(require_roles([UserRole.ADMIN, UserRole.ENGINEER, UserRole.DEMO])),
):
    job = await job_service.get_status(job_id)
    owner_id = int(job.user_id) if job.user_id is not None else None
    if owner_id is not None and current_user.role != UserRole.ADMIN and owner_id != current_user.id:
        raise ForbiddenError("Insufficient permissions")
    if job.status in {JobStatus.DONE, JobStatus.ERROR}:
        return {
            "ok": True,
            "job_id": job.id,
            "status": job.status,
            "already_finished": True,
        }
    cancelled = await job_service.cancel(
        job_id,
        cancelled_by_user_id=current_user.id,
        cancelled_by_username=current_user.username,
    )
    return {
        "ok": True,
        "job_id": cancelled.id,
        "status": cancelled.status,
        "already_finished": False,
    }


@router.websocket("/ws")
async def pipelines_updates_ws(
    websocket: WebSocket,
    job_id: int | None = Query(default=None),
    job_service: JobService = Depends(get_job_service),
    config: Config = Depends(get_config),
):
    try:
        await _authorize_ws_user(websocket, config=config)
    except ForbiddenError:
        await websocket.close(code=4403, reason="Forbidden")
        return
    except UnauthorizedError:
        await websocket.close(code=4401, reason="Unauthorized")
        return

    await websocket.accept()
    last_payload: dict | None = None

    try:
        while True:
            job_payload = None
            if job_id is not None:
                try:
                    job = await job_service.get_status(job_id)
                except Exception:  # noqa: BLE001 - missing/deleted job must not kill ws
                    logger.warning(
                        "Failed to fetch job status for websocket payload. job_id={}",
                        job_id,
                    )
                    job = None
            else:
                job = await job_service.get_active_job()

            if job is not None:
                job_payload = {
                    "job_id": job.id,
                    "status": job.status,
                    "progress": job.progress,
                    "error": job.error,
                    "stats": job.extra,
                }

            # Для WS берём свежую DB-сессию на каждом цикле, иначе в long-lived соединении
            # список может не видеть новые записи из-за кэша/транзакции session.
            async with AsyncSessionLocal() as session:
                repo = PipelineRepository(session)
                pipeline_names = await repo.list_names()
            payload = {
                "type": "state",
                "job": job_payload,
                "pipeline_names": pipeline_names,
            }

            if payload != last_payload:
                await websocket.send_json(payload)
                last_payload = payload

            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        return


@router.get("/embedment-crop-image")
async def get_embedment_crop_image(
    path: str = Query(
        ...,
        description="Относительный путь к PNG из карты закладных (JSON в каталоге OCR parsed_texts)",
    ),
    config: Config = Depends(get_config),
    embedment_service: InstrumentEmbedmentService = Depends(get_instrument_embedment_service),
    _: UserORM = Depends(require_roles([UserRole.ADMIN, UserRole.ENGINEER, UserRole.DEMO])),
):
    found, media_type = embedment_service.resolve_embedment_crop_image(
        relative_path=path,
        crop_output_dir=config.ocr.crop_output_dir,
    )
    return FileResponse(found, media_type=media_type)


@router.get("/instrument-embedments/{pipeline_name}")
async def list_instrument_embedments(
    pipeline_name: str,
    repo: PipelineRepository = Depends(get_pipeline_repository),
    spec_repo: SpecItemRepository = Depends(get_spec_item_repository),
    embedment_service: InstrumentEmbedmentService = Depends(get_instrument_embedment_service),
    _: UserORM = Depends(require_roles([UserRole.ADMIN, UserRole.ENGINEER, UserRole.DEMO])),
):
    return await embedment_service.list_pipeline_embedments(
        pipeline_name=pipeline_name,
        repo=repo,
        spec_repo=spec_repo,
    )


@router.patch("/instrument-embedments/{pipeline_name}")
async def patch_instrument_embedments(
    pipeline_name: str,
    body: InstrumentEmbedmentUpdate,
    repo: PipelineRepository = Depends(get_pipeline_repository),
    spec_repo: SpecItemRepository = Depends(get_spec_item_repository),
    embedment_service: InstrumentEmbedmentService = Depends(get_instrument_embedment_service),
    _: UserORM = Depends(require_roles([UserRole.ADMIN, UserRole.ENGINEER, UserRole.DEMO])),
):
    return await embedment_service.patch_pipeline_embedments(
        pipeline_name=pipeline_name,
        body=body,
        repo=repo,
        spec_repo=spec_repo,
        drawing_store=get_drawing_4_store(),
    )


@router.get("/spec-sections/undefined")
async def get_undefined_spec_sections(
    _: UserORM = Depends(require_roles([UserRole.ADMIN, UserRole.ENGINEER, UserRole.DEMO])),
):
    store = SpecSectionMappingStore()
    return {
        "undefined_names": store.list_undefined(),
        "allowed_sections": SpecSectionMappingStore.allowed_sections_for_ui() + [USER_UNDEFINED_SECTION_LABEL],
        "allowed_tables": allowed_tables_for_ui(),
        "table_to_sections": table_to_sections_map_for_ui(),
        "undefined_label": UNDEFINED_SECTION_LABEL,
        "user_undefined_label": USER_UNDEFINED_SECTION_LABEL,
    }


@router.post("/spec-sections")
async def update_spec_sections(
    request: Request,
    _: UserORM = Depends(require_roles([UserRole.ADMIN, UserRole.ENGINEER, UserRole.DEMO])),
):
    try:
        payload = await request.json()
    except Exception as exc:
        raise ValidationError(
            "Body must be JSON",
            details={"reason": "invalid_json"},
        ) from exc
    store = SpecSectionMappingStore()
    updated = _apply_spec_sections_update_payload(store, payload)
    return {"updated": updated}
