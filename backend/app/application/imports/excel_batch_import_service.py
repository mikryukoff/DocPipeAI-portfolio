import asyncio
from pathlib import Path
from time import time

from loguru import logger

from backend.app.application.imports.excel_import_service import ExcelImportService
from backend.app.application.jobs.job_service import JobService
from backend.app.infrastructure.db.models.job import JobORM
from backend.app.shared.job_workspace_cleanup import maybe_delete_job_workspace


class ExcelBatchImportService:
    def __init__(
        self,
        job_service: JobService,
        excel_import_service: ExcelImportService,
    ):
        self.job_service = job_service
        self.excel_import_service = excel_import_service

    async def start_batch_import(
        self,
        job_id: int,
        excel_paths: list[Path],
        user_log_key: str,
        *,
        job_workspace: str | None = None,
    ) -> JobORM:
        if not excel_paths:
            raise ValueError("no_excel_files")

        excel_paths = sorted(excel_paths, key=lambda p: p.name)

        logger.info(
            "Excel batch import scheduled. job_id={} files_total={} user_log_key={}",
            job_id,
            len(excel_paths),
            user_log_key,
        )

        task = asyncio.create_task(
            self._run(
                job_id,
                excel_paths,
                user_log_key,
                job_workspace=job_workspace,
            ),
            name=f"excel_batch_import_{job_id}",
        )
        self._attach_task_logger(task, task_name="excel_batch_import", job_id=job_id)
        return await self.job_service.get_status(job_id)

    async def _run(
        self,
        job_id: int,
        excel_paths: list[Path],
        user_log_key: str,
        *,
        job_workspace: str | None = None,
    ):
        started_at = time()
        try:
            await self.job_service.start_processing(job_id)
            total_sheets = 0
            total_armature_rows = 0
            total_flow_updates = 0
            total_param_updates = 0

            inspect_dir: Path | None = None
            if job_workspace:
                inspect_dir = Path(job_workspace) / "inspect"
                inspect_dir.mkdir(parents=True, exist_ok=True)

            for idx, excel_path in enumerate(excel_paths, start=1):
                await self.excel_import_service._process(  # type: ignore[attr-defined]
                    job_id=job_id,
                    excel_path=excel_path,
                    started_at=started_at,
                    user_log_key=user_log_key,
                    inspect_output_dir=inspect_dir,
                )

                # Берём статистику по текущему Excel-файлу и аккумулируем.
                job = await self.job_service.get_status(job_id)
                stats = job.extra or {}
                total_sheets += int(stats.get("sheets_processed") or 0)
                total_armature_rows += int(stats.get("armature_updated_rows") or 0)
                total_flow_updates += int(stats.get("flow_direction_updated_pipelines") or 0)
                total_param_updates += int(stats.get("parameters_updated_pipelines") or 0)

                progress = int(idx / len(excel_paths) * 100)
                await self.job_service.update_progress(
                    job_id,
                    progress=progress,
                    extra={
                        # старые поля (для обратной совместимости)
                        "sheets_processed": total_sheets,
                        "armature_updated_rows": total_armature_rows,
                        "flow_direction_updated_pipelines": total_flow_updates,
                        "parameters_updated_pipelines": total_param_updates,
                        # агрегированные поля по всей пачке
                        "pipelines_total": total_flow_updates or total_param_updates,
                        "spec_items_total": total_armature_rows,
                        "files_total": len(excel_paths),
                        "duration_sec": time() - started_at,
                        "files_processed": idx,
                        "current_excel_file": excel_path.name,
                    },
                )
            await self.job_service.finish(job_id)
        except Exception as exc:
            logger.exception("Excel batch import crashed. job_id={}", job_id)
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

