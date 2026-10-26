import asyncio
from pathlib import Path
from time import time

from loguru import logger

from backend.app.application.imports.word_import_service import WordDocumentImportService
from backend.app.application.jobs.job_service import JobService
from backend.app.infrastructure.db.models.job import JobORM
from backend.app.shared.job_workspace_cleanup import maybe_delete_job_workspace


class WordBatchImportService:
    def __init__(
        self,
        job_service: JobService,
        word_import_service: WordDocumentImportService,
    ):
        self.job_service = job_service
        self.word_import_service = word_import_service

    async def start_batch_import(
        self,
        job_id: int,
        docx_paths: list[Path],
        *,
        word_import_kind: str,
        pages_limit: int,
        user_log_key: str | None = None,
        job_workspace: str | None = None,
    ) -> JobORM:
        if not docx_paths:
            raise ValueError("no_word_files")

        logger.info(
            "Word batch import scheduled. job_id={} kind={} files_total={}",
            job_id,
            word_import_kind,
            len(docx_paths),
        )

        task = asyncio.create_task(
            self._run(
                job_id,
                docx_paths,
                word_import_kind=word_import_kind,
                pages_limit=pages_limit,
                user_log_key=user_log_key,
                job_workspace=job_workspace,
            ),
            name=f"word_batch_import_{job_id}",
        )
        self._attach_task_logger(task, task_name="word_batch_import", job_id=job_id)
        return await self.job_service.get_status(job_id)

    async def _run(
        self,
        job_id: int,
        docx_paths: list[Path],
        *,
        word_import_kind: str,
        pages_limit: int,
        user_log_key: str | None = None,
        job_workspace: str | None = None,
    ):
        started_at = time()
        try:
            await self.job_service.start_processing(job_id)
            total_files = len(docx_paths)
            results: list[dict] = []

            for idx, path in enumerate(docx_paths, start=1):
                await self.job_service.update_progress(
                    job_id,
                    progress=int((idx - 1) / max(total_files, 1) * 100),
                    extra={
                        "source": "word",
                        "word_import_kind": word_import_kind,
                        "files_processed": idx - 1,
                        "files_total": total_files,
                        "current_file": path.name,
                        "duration_sec": time() - started_at,
                    },
                )

                async def emit(
                    p: int,
                    inner: dict | None = None,
                    *,
                    _idx: int = idx,
                    _total: int = total_files,
                ) -> None:
                    base = int((_idx - 1) / max(_total, 1) * 100)
                    span = 100.0 / max(_total, 1)
                    overall = int(base + (p / 100.0) * span)
                    merged = dict(inner or {})
                    merged.setdefault("source", "word")
                    merged["files_processed"] = _idx - 1
                    merged["files_total"] = _total
                    merged["current_file"] = path.name
                    merged["duration_sec"] = time() - started_at
                    await self.job_service.update_progress(
                        job_id, progress=min(99, overall), extra=merged
                    )

                raw: dict
                if word_import_kind == "passport_vik":
                    raw = await self.word_import_service.import_passport_vik(
                        file_name=path.name,
                        docx_bytes=path.read_bytes(),
                        pages_limit=pages_limit,
                        job_id=job_id,
                        user_log_key=user_log_key,
                        on_progress=emit,
                    )
                elif word_import_kind == "pipelines_tests":
                    raw = await self.word_import_service.import_pipelines_tests(
                        file_name=path.name,
                        docx_bytes=path.read_bytes(),
                        pages_limit=pages_limit,
                        job_id=job_id,
                        user_log_key=user_log_key,
                        on_progress=emit,
                    )
                else:
                    raw = {}
                merged = dict(raw) if isinstance(raw, dict) else {}
                merged["source_file"] = path.name
                results.append(merged)

            fin_extra: dict = {
                "source": "word",
                "word_import_kind": word_import_kind,
                "files_processed": total_files,
                "files_total": total_files,
                "word_results": results,
                "duration_sec": round(time() - started_at, 2),
            }
            last = results[-1] if results else None
            if isinstance(last, dict) and last.get("filename"):
                fin_extra["word_download_stem"] = str(last["filename"])
            await self.job_service.update_progress(job_id, extra=fin_extra)
            await self.job_service.finish(job_id, progress=100)
        except Exception as exc:
            logger.exception("Word batch import crashed. job_id={}", job_id)
            await self.job_service.fail(job_id, str(exc))
        finally:
            maybe_delete_job_workspace(job_workspace=job_workspace, job_id=job_id)

    @staticmethod
    def _attach_task_logger(task: asyncio.Task, *, task_name: str, job_id: int) -> None:
        def _on_done(done_task: asyncio.Task) -> None:
            try:
                done_task.result()
            except asyncio.CancelledError:
                logger.warning(
                    "Background task cancelled. task_name={} job_id={}",
                    task_name,
                    job_id,
                )
            except Exception:
                logger.exception(
                    "Background task failed unexpectedly. task_name={} job_id={}",
                    task_name,
                    job_id,
                )

        task.add_done_callback(_on_done)
