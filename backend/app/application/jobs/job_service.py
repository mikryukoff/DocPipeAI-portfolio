from pathlib import Path
from datetime import UTC, datetime

from loguru import logger
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from backend.app.application.exceptions import JobNotFoundError
from backend.app.infrastructure.db.models.job import JobORM, JobStatus
from backend.app.infrastructure.repositories.job_repository import JobRepository


class JobService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ):
        self.session_factory = session_factory

    async def create(
        self,
        filename: str,
        extra: dict | None = None,
        *,
        user_id: int | None = None,
    ) -> JobORM:
        async with self.session_factory() as session:
            repo = JobRepository(session)
            job = await repo.create(filename, extra=extra, user_id=user_id)
            logger.info(
                "Job created. job_id={} user_id={} filename={}",
                job.id,
                user_id,
                filename,
            )
            return job

    async def get_resume_page(self, pdf_path: str | Path, *, user_id: int | None = None) -> int:
        basename = Path(pdf_path).name
        async with self.session_factory() as session:
            repo = JobRepository(session)
            if user_id is not None:
                failed_job = await repo.get_last_failed_by_source_basename(
                    user_id=user_id, basename=basename
                )
            else:
                failed_job = await repo.get_last_failed_by_filename(str(pdf_path))
            if not failed_job or not failed_job.extra:
                return 1

            page = failed_job.extra.get("pages")
            if not isinstance(page, int) or page < 1:
                return 1
            return page + 1

    async def start_processing(self, job_id: int):
        async with self.session_factory() as session:
            repo = JobRepository(session)
            job = await self._require_job(repo, job_id)
            if self._is_cancelled(job):
                logger.info("Skip start_processing for cancelled job. job_id={}", job_id)
                return
            await repo.update(job, status=JobStatus.PROCESSING)
            logger.info("Job status set to PROCESSING. job_id={}", job_id)

    async def update_progress(self, job_id: int, progress: int | None = None, extra: dict | None = None):
        async with self.session_factory() as session:
            repo = JobRepository(session)
            job = await self._require_job(repo, job_id)
            if self._is_cancelled(job):
                raise RuntimeError("Job cancelled by user")
            merged_extra = dict(job.extra or {})
            if extra:
                merged_extra.update(extra)

            await repo.update(job, progress=progress, extra=merged_extra)
            logger.debug("Job progress updated. job_id={} progress={}", job_id, progress)

    async def finish(self, job_id: int, progress: int = 100):
        async with self.session_factory() as session:
            repo = JobRepository(session)
            job = await self._require_job(repo, job_id)
            if self._is_cancelled(job):
                logger.info("Skip finish for cancelled job. job_id={}", job_id)
                return

            await repo.update(
                job,
                status=JobStatus.DONE,
                progress=progress,
            )
            logger.info("Job finished. job_id={} progress={}", job_id, progress)

    async def fail(self, job_id: int, error: str):
        async with self.session_factory() as session:
            repo = JobRepository(session)
            job = await self._require_job(repo, job_id)
            if self._is_cancelled(job):
                logger.info("Skip fail for cancelled job. job_id={}", job_id)
                return
            safe_error = self._truncate_error(error)

            await repo.update(
                job,
                status=JobStatus.ERROR,
                error=safe_error,
            )
            logger.error("Job failed. job_id={} error={}", job_id, safe_error)

    async def cancel(
        self,
        job_id: int,
        *,
        cancelled_by_user_id: int | None = None,
        cancelled_by_username: str | None = None,
        reason: str = "Job cancelled by user",
    ) -> JobORM:
        async with self.session_factory() as session:
            repo = JobRepository(session)
            job = await self._require_job(repo, job_id)
            merged_extra = dict(job.extra or {})
            merged_extra["cancel_requested"] = True
            merged_extra["cancelled_at"] = datetime.now(tz=UTC).isoformat()
            if cancelled_by_user_id is not None:
                merged_extra["cancelled_by_user_id"] = cancelled_by_user_id
            if cancelled_by_username:
                merged_extra["cancelled_by_username"] = cancelled_by_username
            merged_extra["waiting_user_input"] = False
            merged_extra["waiting_embedment_input"] = False
            merged_extra["embedment_pending"] = None
            merged_extra["embedment_pending_total"] = 0

            await repo.update(
                job,
                status=JobStatus.ERROR,
                error=self._truncate_error(reason),
                extra=merged_extra,
            )
            logger.warning(
                "Job cancelled. job_id={} by_user_id={} by_username={}",
                job_id,
                cancelled_by_user_id,
                cancelled_by_username,
            )
            return job

    async def get_status(self, job_id: int) -> JobORM:
        async with self.session_factory() as session:
            repo = JobRepository(session)
            return await self._require_job(repo, job_id)

    async def get_active_job(self) -> JobORM | None:
        async with self.session_factory() as session:
            repo = JobRepository(session)
            return await repo.get_last_active()

    async def list_failed_jobs(
        self,
        *,
        user_id: int | None = None,
        source: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[JobORM]:
        # Берём небольшой запас, чтобы корректно отфильтровать по source в Python.
        query_limit = max(limit + offset + 200, 500)
        async with self.session_factory() as session:
            repo = JobRepository(session)
            rows = await repo.list_errors(
                user_id=user_id,
                date_from=date_from,
                date_to=date_to,
                limit=query_limit,
                offset=0,
            )
        source_key = (source or "").strip().lower()
        if source_key:
            rows = [
                row for row in rows
                if str((row.extra or {}).get("source") or "").strip().lower() == source_key
            ]
        if offset > 0:
            rows = rows[offset:]
        return rows[: max(1, limit)]

    async def clear_failed_jobs(
        self,
        *,
        user_id: int | None = None,
        source: str | None = None,
    ) -> int:
        async with self.session_factory() as session:
            repo = JobRepository(session)
            return await repo.clear_errors(user_id=user_id, source=source)

    @staticmethod
    def _truncate_error(error: str, max_len: int = 255) -> str:
        if len(error) <= max_len:
            return error
        suffix = "... [truncated]"
        return error[: max_len - len(suffix)] + suffix

    @staticmethod
    def _is_cancelled(job: JobORM) -> bool:
        if job.status != JobStatus.ERROR:
            return False
        extra = job.extra or {}
        return bool(extra.get("cancel_requested"))

    @staticmethod
    async def _require_job(repo: JobRepository, job_id: int) -> JobORM:
        job = await repo.get(job_id)
        if not job:
            raise JobNotFoundError(job_id)
        return job
