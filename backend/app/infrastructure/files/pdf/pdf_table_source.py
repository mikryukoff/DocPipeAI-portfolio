from pathlib import Path
from collections.abc import AsyncIterator

from backend.app.infrastructure.files.pdf.pdf_table_extractor import PDFTableExtractor
from backend.app.application.jobs.job_service import JobService
from backend.app.infrastructure.files.pdf.models import PDFTable


class PDFTableSource:
    def __init__(
        self,
        pdf_path: Path,
        job_id: int,
        job_service: JobService,
    ):
        self.pdf_path = pdf_path
        self.job_id = job_id
        self.job_service = job_service
        self.extractor = PDFTableExtractor()

    async def iter_tables_by_page(self, start_page: int = 1) -> AsyncIterator[tuple[int, list[PDFTable]]]:
        async for page_num, page_tables in self.extractor.iter_tables_by_page(
            pdf_path=self.pdf_path,
            start_page=start_page,
            # Прогресс по job обновляется на уровне PDFPipelineImporter:
            # там есть агрегированные stats по странице (pages/pipelines/spec_items).
            # Дублировать update_progress здесь не нужно.
            on_progress=None,
        ):
            yield page_num, page_tables
