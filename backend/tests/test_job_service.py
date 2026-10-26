import asyncio
from types import SimpleNamespace

from backend.app.application.jobs.job_service import JobService
from backend.app.infrastructure.db.models.job import JobStatus


class _FakeSessionCtx:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return False


class _FakeSessionFactory:
    def __call__(self):
        return _FakeSessionCtx()


def test_job_service_merges_stats_and_truncates_error(monkeypatch):
    jobs = {
        1: SimpleNamespace(
            id=1,
            filename="file.pdf",
            status=JobStatus.PROCESSING,
            progress=10,
            error=None,
            extra={"pages": 5, "pipelines": 2},
        )
    }

    class FakeJobRepository:
        def __init__(self, _session):
            pass

        async def get(self, job_id: int):
            return jobs.get(job_id)

        async def update(self, job, *, status=None, progress=None, error=None, extra=None):
            if status is not None:
                job.status = status
            if progress is not None:
                job.progress = progress
            if error is not None:
                job.error = error
            if extra is not None:
                job.extra = extra

    monkeypatch.setattr(
        "backend.app.application.jobs.job_service.JobRepository",
        FakeJobRepository,
    )

    service = JobService(session_factory=_FakeSessionFactory())

    async def _run():
        await service.update_progress(
            1,
            progress=20,
            extra={"spec_items": 100},
        )
        await service.fail(1, "x" * 400)

    asyncio.run(_run())

    assert jobs[1].progress == 20
    assert jobs[1].extra == {"pages": 5, "pipelines": 2, "spec_items": 100}
    assert jobs[1].status == JobStatus.ERROR
    assert len(jobs[1].error) <= 255


def test_job_service_cancel_marks_job_and_blocks_progress(monkeypatch):
    jobs = {
        2: SimpleNamespace(
            id=2,
            filename="file2.pdf",
            status=JobStatus.PROCESSING,
            progress=35,
            error=None,
            extra={"files_total": 2},
        )
    }

    class FakeJobRepository:
        def __init__(self, _session):
            pass

        async def get(self, job_id: int):
            return jobs.get(job_id)

        async def update(self, job, *, status=None, progress=None, error=None, extra=None):
            if status is not None:
                job.status = status
            if progress is not None:
                job.progress = progress
            if error is not None:
                job.error = error
            if extra is not None:
                job.extra = extra

    monkeypatch.setattr(
        "backend.app.application.jobs.job_service.JobRepository",
        FakeJobRepository,
    )

    service = JobService(session_factory=_FakeSessionFactory())

    async def _run():
        await service.cancel(
            2,
            cancelled_by_user_id=10,
            cancelled_by_username="engineer",
        )

    asyncio.run(_run())

    assert jobs[2].status == JobStatus.ERROR
    assert jobs[2].error == "Job cancelled by user"
    assert jobs[2].extra["cancel_requested"] is True
    assert jobs[2].extra["cancelled_by_user_id"] == 10

    async def _update_after_cancel():
        await service.update_progress(2, progress=99, extra={"files_processed": 2})

    try:
        asyncio.run(_update_after_cancel())
        raised = False
    except RuntimeError as exc:
        raised = True
        assert "cancelled" in str(exc).lower()
    assert raised


def test_job_service_list_failed_jobs_filters_by_source(monkeypatch):
    jobs = [
        SimpleNamespace(
            id=10,
            user_id=1,
            filename="a.pdf",
            status=JobStatus.ERROR,
            error="bad pdf",
            created_at=1,
            extra={"source": "pdf"},
        ),
        SimpleNamespace(
            id=11,
            user_id=1,
            filename="b.xlsx",
            status=JobStatus.ERROR,
            error="bad excel",
            created_at=2,
            extra={"source": "excel"},
        ),
    ]

    class FakeJobRepository:
        def __init__(self, _session):
            pass

        async def list_errors(self, **_kwargs):
            return list(jobs)

    monkeypatch.setattr(
        "backend.app.application.jobs.job_service.JobRepository",
        FakeJobRepository,
    )

    service = JobService(session_factory=_FakeSessionFactory())

    async def _run():
        return await service.list_failed_jobs(source="excel", limit=20, offset=0)

    rows = asyncio.run(_run())
    assert len(rows) == 1
    assert rows[0].filename == "b.xlsx"
