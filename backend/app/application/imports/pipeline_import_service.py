import asyncio
from pathlib import Path

from loguru import logger

from backend.app.application.jobs.job_service import JobService
from backend.app.domain.pdf_import.pdf_pipeline_importer import PDFPipelineImporter
from backend.app.infrastructure.db.models.job import JobORM


class PipelineImportService:
    def __init__(
        self,
        job_service: JobService,
        importer: PDFPipelineImporter,
    ):
        self.job_service = job_service
        self.importer = importer

    async def start_import(
        self, pdf_path: Path, *, user_id: int | None = None
    ) -> JobORM:
        source_name = pdf_path.name
        resume_page = await self.job_service.get_resume_page(
            source_name, user_id=user_id
        )
        job = await self.job_service.create(
            source_name,
            extra={"resume_from_page": resume_page},
            user_id=user_id,
        )
        logger.info(
            "Import scheduled. job_id={} file={} resume_page={}",
            job.id,
            source_name,
            resume_page,
        )

        asyncio.create_task(
            self._run(job.id, pdf_path, resume_page)
        )

        return job

    async def _run(self, job_id: int, pdf_path: Path, resume_page: int):
        try:
            await self.job_service.start_processing(job_id)
            await self.importer.run_from_page(pdf_path, job_id, start_page=resume_page)
            await self.job_service.finish(job_id)
        except Exception as e:
            logger.exception("Import crashed. job_id={} file={}", job_id, pdf_path.name)
            await self.job_service.fail(job_id, str(e))
