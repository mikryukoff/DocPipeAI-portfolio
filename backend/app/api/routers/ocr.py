import asyncio
from pathlib import Path
from time import time

from fastapi import APIRouter, UploadFile, File, Form, Depends, BackgroundTasks
from fastapi.responses import FileResponse
from loguru import logger

from backend.app.api.dependencies import (
    get_config,
    get_job_service,
    require_roles,
)
from backend.app.application.exceptions import NotFoundError, ValidationError
from backend.app.config import Config
from backend.app.application.jobs.job_service import JobService
from backend.app.application.ocr.ocr_recognition_service import OcrRecognitionService
from backend.app.infrastructure.db.database import AsyncSessionLocal
from backend.app.infrastructure.db.models.user import UserORM, UserRole
from backend.app.shared.path_safety import resolve_safe_file, safe_filename_stem

router = APIRouter(tags=["OCR"])


def _standalone_job_service() -> JobService:
    return JobService(session_factory=AsyncSessionLocal)


def _standalone_recognition_service() -> OcrRecognitionService:
    return OcrRecognitionService(session_factory=AsyncSessionLocal)


async def _run_standalone_passport_rngs(
    job_id: int,
    *,
    file_name: str | None,
    pdf_bytes: bytes,
    pages_limit: int,
) -> None:
    js = _standalone_job_service()
    rec = _standalone_recognition_service()

    started_at = time()

    async def emit(progress: int, extra: dict | None = None) -> None:
        m = dict(extra or {})
        m.setdefault("source", "ocr_standalone")
        m.setdefault("files_total", 1)
        m.setdefault("files_processed", 0)
        m["duration_sec"] = round(time() - started_at, 2)
        await js.update_progress(job_id, progress=progress, extra=m)

    try:
        out = await rec.recognize_passport_rngs(
            file_name=file_name,
            pdf_bytes=pdf_bytes,
            pages_limit=pages_limit,
            on_progress=emit,
        )
        stem = out.get("filename") if isinstance(out, dict) else None
        fin = {"duration_sec": round(time() - started_at, 2)}
        if stem:
            fin["ocr_download_stem"] = str(stem)
        await js.update_progress(job_id, extra=fin)
        await js.finish(job_id, progress=100)
    except Exception as exc:
        await js.update_progress(job_id, extra={"duration_sec": round(time() - started_at, 2)})
        await js.fail(job_id, str(exc))
        logger.exception("Standalone OCR passport_rngs failed. job_id={}", job_id)


async def _run_standalone_drawing(
    job_id: int,
    *,
    file_name: str | None,
    pdf_bytes: bytes,
    pages_limit: int,
) -> None:
    js = _standalone_job_service()
    rec = _standalone_recognition_service()

    started_at = time()

    async def emit(progress: int, extra: dict | None = None) -> None:
        m = dict(extra or {})
        m.setdefault("source", "ocr_standalone")
        m.setdefault("files_total", 1)
        m.setdefault("files_processed", 0)
        m["duration_sec"] = round(time() - started_at, 2)
        await js.update_progress(job_id, progress=progress, extra=m)

    try:
        out = await rec.recognize_drawing(
            file_name=file_name,
            pdf_bytes=pdf_bytes,
            pages_limit=pages_limit,
            on_progress=emit,
        )
        stem = out.get("filename") if isinstance(out, dict) else None
        fin = {"duration_sec": round(time() - started_at, 2)}
        if stem:
            fin["ocr_download_stem"] = str(stem)
        await js.update_progress(job_id, extra=fin)
        await js.finish(job_id, progress=100)
    except Exception as exc:
        await js.update_progress(job_id, extra={"duration_sec": round(time() - started_at, 2)})
        await js.fail(job_id, str(exc))
        logger.exception("Standalone OCR drawing failed. job_id={}", job_id)


async def _run_standalone_compensators(
    job_id: int,
    *,
    diameter_file_name: str | None,
    diameter_pdf_bytes: bytes,
    gost_materials_file_name: str | None,
    gost_materials_pdf_bytes: bytes,
) -> None:
    js = _standalone_job_service()
    rec = _standalone_recognition_service()

    started_at = time()

    async def emit(progress: int, extra: dict | None = None) -> None:
        m = dict(extra or {})
        m.setdefault("source", "ocr_standalone")
        m.setdefault("files_total", 1)
        m.setdefault("files_processed", 0)
        m["duration_sec"] = round(time() - started_at, 2)
        await js.update_progress(job_id, progress=progress, extra=m)

    try:
        out = await rec.recognize_passport_compensators(
            diameter_file_name=diameter_file_name,
            diameter_pdf_bytes=diameter_pdf_bytes,
            gost_materials_file_name=gost_materials_file_name,
            gost_materials_pdf_bytes=gost_materials_pdf_bytes,
            on_progress=emit,
        )
        stem = out.get("filename") if isinstance(out, dict) else None
        fin = {"duration_sec": round(time() - started_at, 2)}
        if stem:
            fin["ocr_download_stem"] = str(stem)
        await js.update_progress(job_id, extra=fin)
        await js.finish(job_id, progress=100)
    except Exception as exc:
        await js.update_progress(job_id, extra={"duration_sec": round(time() - started_at, 2)})
        await js.fail(job_id, str(exc))
        logger.exception("Standalone OCR compensators failed. job_id={}", job_id)


async def _run_standalone_passport_vik(
    job_id: int,
    *,
    file_name: str | None,
    pdf_bytes: bytes,
    pages_limit: int,
) -> None:
    js = _standalone_job_service()
    rec = _standalone_recognition_service()

    started_at = time()

    async def emit(progress: int, extra: dict | None = None) -> None:
        m = dict(extra or {})
        m.setdefault("source", "ocr_standalone")
        m.setdefault("files_total", 1)
        m.setdefault("files_processed", 0)
        m["duration_sec"] = round(time() - started_at, 2)
        await js.update_progress(job_id, progress=progress, extra=m)

    try:
        out = await rec.recognize_passport_vik(
            file_name=file_name,
            pdf_bytes=pdf_bytes,
            pages_limit=pages_limit,
            on_progress=emit,
        )
        stem = out.get("filename") if isinstance(out, dict) else None
        fin = {"duration_sec": round(time() - started_at, 2)}
        if stem:
            fin["ocr_download_stem"] = str(stem)
        await js.update_progress(job_id, extra=fin)
        await js.finish(job_id, progress=100)
    except Exception as exc:
        await js.update_progress(job_id, extra={"duration_sec": round(time() - started_at, 2)})
        await js.fail(job_id, str(exc))
        logger.exception("Standalone OCR passport_vik failed. job_id={}", job_id)


async def _run_standalone_pipelines_tests(
    job_id: int,
    *,
    file_name: str | None,
    pdf_bytes: bytes,
    pages_limit: int,
) -> None:
    js = _standalone_job_service()
    rec = _standalone_recognition_service()

    started_at = time()

    async def emit(progress: int, extra: dict | None = None) -> None:
        m = dict(extra or {})
        m.setdefault("source", "ocr_standalone")
        m.setdefault("files_total", 1)
        m.setdefault("files_processed", 0)
        m["duration_sec"] = round(time() - started_at, 2)
        await js.update_progress(job_id, progress=progress, extra=m)

    try:
        out = await rec.recognize_pipelines_tests(
            file_name=file_name,
            pdf_bytes=pdf_bytes,
            pages_limit=pages_limit,
            on_progress=emit,
        )
        stem = out.get("filename") if isinstance(out, dict) else None
        fin = {"duration_sec": round(time() - started_at, 2)}
        if stem:
            fin["ocr_download_stem"] = str(stem)
        await js.update_progress(job_id, extra=fin)
        await js.finish(job_id, progress=100)
    except Exception as exc:
        await js.update_progress(job_id, extra={"duration_sec": round(time() - started_at, 2)})
        await js.fail(job_id, str(exc))
        logger.exception("Standalone OCR pipelines_tests failed. job_id={}", job_id)


@router.post("/api/recognize-passport-rngs")
async def recognize(
    file: UploadFile = File(...),
    pages_limit: int = Form(0),
    current_user: UserORM = Depends(require_roles([UserRole.ADMIN, UserRole.ENGINEER, UserRole.DEMO])),
    job_service: JobService = Depends(get_job_service),
):
    pdf_bytes = await file.read()
    job = await job_service.create(
        file.filename or "ocr-passport-rngs",
        extra={
            "ocr_kind": "passport_rngs",
            "source": "ocr_standalone",
            "files_total": 1,
            "files_processed": 0,
        },
        user_id=current_user.id,
    )
    await job_service.start_processing(job.id)
    asyncio.create_task(
        _run_standalone_passport_rngs(
            job.id,
            file_name=file.filename,
            pdf_bytes=pdf_bytes,
            pages_limit=pages_limit,
        )
    )
    return {"job_id": job.id, "status": job.status}


@router.post("/api/recognize-drawing")
async def recognize_drawing(
    file: UploadFile,
    pages_limit: int = Form(0),
    current_user: UserORM = Depends(require_roles([UserRole.ADMIN, UserRole.ENGINEER, UserRole.DEMO])),
    job_service: JobService = Depends(get_job_service),
):
    pdf_bytes = await file.read()
    job = await job_service.create(
        file.filename or "ocr-drawing",
        extra={
            "ocr_kind": "instrument_drawings",
            "source": "ocr_standalone",
            "files_total": 1,
            "files_processed": 0,
        },
        user_id=current_user.id,
    )
    await job_service.start_processing(job.id)
    asyncio.create_task(
        _run_standalone_drawing(
            job.id,
            file_name=file.filename,
            pdf_bytes=pdf_bytes,
            pages_limit=pages_limit,
        )
    )
    return {"job_id": job.id, "status": job.status}


@router.post("/api/recognize-passport-compensators")
async def recognize_passport_compensators(
    diameter_file: UploadFile = File(...),
    gost_materials_file: UploadFile = File(...),
    current_user: UserORM = Depends(require_roles([UserRole.ADMIN, UserRole.ENGINEER, UserRole.DEMO])),
    job_service: JobService = Depends(get_job_service),
):
    joined_name = (
        f"{diameter_file.filename or 'diameter'}__"
        f"{gost_materials_file.filename or 'gost_materials'}"
    )
    d_bytes = await diameter_file.read()
    g_bytes = await gost_materials_file.read()
    job = await job_service.create(
        joined_name,
        extra={
            "ocr_kind": "passport_compensators",
            "source": "ocr_standalone",
            "files_total": 1,
            "files_processed": 0,
        },
        user_id=current_user.id,
    )
    await job_service.start_processing(job.id)
    asyncio.create_task(
        _run_standalone_compensators(
            job.id,
            diameter_file_name=diameter_file.filename,
            diameter_pdf_bytes=d_bytes,
            gost_materials_file_name=gost_materials_file.filename,
            gost_materials_pdf_bytes=g_bytes,
        )
    )
    return {"job_id": job.id, "status": job.status}

@router.post("/api/recognize-passport-vik")
async def recognize_passport_vik(
    file: UploadFile = File(...),
    pages_limit: int = Form(0),
    current_user: UserORM = Depends(require_roles([UserRole.ADMIN, UserRole.ENGINEER, UserRole.DEMO])),
    job_service: JobService = Depends(get_job_service),
):
    pdf_bytes = await file.read()
    job = await job_service.create(
        file.filename or "ocr-passport-vik",
        extra={
            "ocr_kind": "passport_vik",
            "source": "ocr_standalone",
            "files_total": 1,
            "files_processed": 0,
        },
        user_id=current_user.id,
    )
    await job_service.start_processing(job.id)
    asyncio.create_task(
        _run_standalone_passport_vik(
            job.id,
            file_name=file.filename,
            pdf_bytes=pdf_bytes,
            pages_limit=pages_limit,
        )
    )
    return {"job_id": job.id, "status": job.status}


@router.post("/api/recognize-pipelines")
async def recognize_pipelines(
    file: UploadFile = File(...),
    pages_limit: int = Form(0),
    current_user: UserORM = Depends(require_roles([UserRole.ADMIN, UserRole.ENGINEER, UserRole.DEMO])),
    job_service: JobService = Depends(get_job_service),
):
    pdf_bytes = await file.read()
    job = await job_service.create(
        file.filename or "ocr-pipelines-tests",
        extra={
            "ocr_kind": "pipelines_tests",
            "source": "ocr_standalone",
            "files_total": 1,
            "files_processed": 0,
        },
        user_id=current_user.id,
    )
    await job_service.start_processing(job.id)
    asyncio.create_task(
        _run_standalone_pipelines_tests(
            job.id,
            file_name=file.filename,
            pdf_bytes=pdf_bytes,
            pages_limit=pages_limit,
        )
    )
    return {"job_id": job.id, "status": job.status}


@router.get("/api/download/{filename}")
async def download_json(
    filename: str,
    background_tasks: BackgroundTasks,
    config: Config = Depends(get_config),
    _: UserORM = Depends(require_roles([UserRole.ADMIN, UserRole.ENGINEER, UserRole.DEMO])),
):
    stem = safe_filename_stem(filename)
    if stem is None:
        raise ValidationError("Некорректное имя файла")

    parsed_output_dir = Path(config.ocr.parsed_output_dir)
    target = resolve_safe_file(
        output_dir=parsed_output_dir,
        filename_stem=stem,
        suffix=".json",
    )
    if target is None or not target.exists() or not target.is_file():
        raise NotFoundError("Файл не найден")

    background_tasks.add_task(target.unlink, missing_ok=True)
    return FileResponse(
        target,
        filename=f"{stem}.json",
        media_type="application/json",
    )
