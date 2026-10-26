from datetime import datetime

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.infrastructure.db.models.job import JobORM, JobStatus


class JobRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        filename: str,
        extra: dict | None = None,
        *,
        user_id: int | None = None,
    ) -> JobORM:
        job = JobORM(filename=filename, extra=extra, user_id=user_id)
        self.session.add(job)
        await self.session.commit()
        await self.session.refresh(job)
        return job

    async def get(self, job_id: int) -> JobORM | None:
        return await self.session.get(JobORM, job_id)

    async def update(
        self,
        job: JobORM,
        *,
        status: str | None = None,
        progress: int | None = None,
        error: str | None = None,
        extra: dict | None = None
    ):
        if status is not None:
            job.status = status
        if progress is not None:
            job.progress = progress
        if error is not None:
            job.error = error
        if extra is not None:
            job.extra = extra
        await self.session.commit()

    async def get_last_failed_by_filename(self, filename: str) -> JobORM | None:
        stmt = (
            select(JobORM)
            .where(JobORM.filename == filename, JobORM.status == JobStatus.ERROR)
            .order_by(JobORM.id.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_last_failed_by_source_basename(
        self,
        *,
        user_id: int,
        basename: str,
    ) -> JobORM | None:
        """Последняя ошибка по имени файла (без пути) и пользователю (для резюма после job-каталогов)."""
        if not basename:
            return None
        like_fwd = f"%/{basename}"
        like_back = f"%\\\\{basename}"
        stmt = (
            select(JobORM)
            .where(
                JobORM.user_id == user_id,
                JobORM.status == JobStatus.ERROR,
                or_(
                    JobORM.filename == basename,
                    JobORM.filename.like(like_fwd),
                    JobORM.filename.like(like_back),
                ),
            )
            .order_by(JobORM.id.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_last_active(self) -> JobORM | None:
        stmt = (
            select(JobORM)
            .where(JobORM.status.in_([JobStatus.PENDING, JobStatus.PROCESSING]))
            .order_by(JobORM.id.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_errors(
        self,
        *,
        user_id: int | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[JobORM]:
        stmt = select(JobORM).where(JobORM.status == JobStatus.ERROR)
        if user_id is not None:
            stmt = stmt.where(JobORM.user_id == user_id)
        if date_from is not None:
            stmt = stmt.where(JobORM.created_at >= date_from)
        if date_to is not None:
            stmt = stmt.where(JobORM.created_at <= date_to)
        stmt = stmt.order_by(JobORM.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars())

    async def clear_errors(
        self,
        *,
        user_id: int | None = None,
        source: str | None = None,
    ) -> int:
        stmt = delete(JobORM).where(JobORM.status == JobStatus.ERROR)
        if user_id is not None:
            stmt = stmt.where(JobORM.user_id == user_id)
        if source:
            # JSON-фильтрация по extra.source. Работает для SQLite/Postgres.
            stmt = stmt.where(JobORM.extra["source"].as_string() == source.strip().lower())
        result = await self.session.execute(stmt)
        await self.session.commit()
        return int(result.rowcount or 0)
