import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from backend.app.domain.models.specification import Specification, Pipe
from backend.app.domain.parsing.pipeline_factory import PipelineFactory
from backend.app.domain.pdf_import.pdf_pipeline_importer import PDFPipelineImporter


class _FakeJobService:
    def __init__(self):
        self.progress_calls = []

    async def update_progress(self, job_id: int, progress: int | None = None, extra: dict | None = None):
        self.progress_calls.append((job_id, progress, extra))


class _FakeRepo:
    def __init__(self):
        self.saved = []
        self.by_name = {}
        self.last_job_by_pipeline = {}
        self.modes = []

    async def save_or_update(self, pipeline, replace_pages=None, *, job_id=None):
        prev_job = self.last_job_by_pipeline.get(pipeline.name)
        mode = "full_refresh" if prev_job is not None and job_id is not None and prev_job != job_id else "merge"
        self.saved.append((pipeline.name, set(replace_pages or []), job_id))
        self.modes.append(mode)
        if job_id is not None:
            self.last_job_by_pipeline[pipeline.name] = job_id
        self.by_name[pipeline.name] = pipeline

    async def get_by_name(self, name: str):
        return self.by_name.get(name)


def test_importer_updates_progress_and_saves_touched_pipelines(monkeypatch):
    repo = _FakeRepo()
    job_service = _FakeJobService()
    factory = PipelineFactory()

    class FakeSource:
        def __init__(self, pdf_path, job_id, job_service):
            self.pdf_path = pdf_path
            self.job_id = job_id
            self.job_service = job_service

        async def iter_tables_by_page(self, start_page: int = 1):
            yield 6, ["page6_tables"]
            yield 7, ["page7_tables"]

    class FakeParser:
        def __init__(self):
            self._counter = 0
            self._pipeline = factory.create("PIPE-1")

        def process_tables(self, _):
            self._counter += 1
            page = "6.1" if self._counter == 1 else "6.2"
            self._pipeline.specifications.append(
                Specification(
                    page=page,
                    pipes=[Pipe(position=self._counter, name="P", unit="m", quantity=1.0, dimensions="57x3")],
                )
            )
            return {"PIPE-1": {page}}

        def snapshot(self, _):
            return [self._pipeline]

        def spec_items_count(self):
            return self._counter

        def pipelines_count(self):
            return 1

    monkeypatch.setattr(
        "backend.app.domain.pdf_import.pdf_pipeline_importer.PDFTableSource",
        FakeSource,
    )
    monkeypatch.setattr(
        "backend.app.domain.pdf_import.pdf_pipeline_importer.ParsePipelineFromTables",
        FakeParser,
    )

    @asynccontextmanager
    async def fake_repo_factory():
        yield repo

    importer = PDFPipelineImporter(
        repo_factory=lambda: fake_repo_factory(),
        job_service=job_service,
    )

    asyncio.run(importer.run_from_page(Path("dummy.pdf"), job_id=123, start_page=1))

    assert len(repo.saved) == 2
    assert repo.saved[0] == ("PIPE-1", {"6.1"}, 123)
    assert repo.saved[1] == ("PIPE-1", {"6.2"}, 123)
    assert repo.modes == ["merge", "merge"]
    assert len(job_service.progress_calls) == 2
    assert job_service.progress_calls[0][2]["pages"] == 6
    assert job_service.progress_calls[1][2]["pages"] == 7


def test_importer_marks_first_touch_of_new_job_then_merges(monkeypatch):
    repo = _FakeRepo()
    job_service = _FakeJobService()
    factory = PipelineFactory()

    class FakeSource:
        def __init__(self, pdf_path, job_id, job_service):
            self.pdf_path = pdf_path
            self.job_id = job_id
            self.job_service = job_service

        async def iter_tables_by_page(self, start_page: int = 1):
            yield 6, ["page6_tables"]
            yield 7, ["page7_tables"]

    class FakeParser:
        def __init__(self):
            self._counter = 0
            self._pipeline = factory.create("PIPE-1")

        def process_tables(self, _):
            self._counter += 1
            page = "6.1" if self._counter == 1 else "6.2"
            self._pipeline.specifications.append(
                Specification(
                    page=page,
                    pipes=[Pipe(position=self._counter, name="P", unit="m", quantity=1.0, dimensions="57x3")],
                )
            )
            return {"PIPE-1": {page}}

        def snapshot(self, _):
            return [self._pipeline]

        def spec_items_count(self):
            return self._counter

        def pipelines_count(self):
            return 1

    monkeypatch.setattr(
        "backend.app.domain.pdf_import.pdf_pipeline_importer.PDFTableSource",
        FakeSource,
    )
    monkeypatch.setattr(
        "backend.app.domain.pdf_import.pdf_pipeline_importer.ParsePipelineFromTables",
        FakeParser,
    )

    @asynccontextmanager
    async def fake_repo_factory():
        yield repo

    importer = PDFPipelineImporter(
        repo_factory=lambda: fake_repo_factory(),
        job_service=job_service,
    )

    asyncio.run(importer.run_from_page(Path("dummy.pdf"), job_id=100, start_page=1))
    asyncio.run(importer.run_from_page(Path("dummy.pdf"), job_id=200, start_page=1))

    assert repo.saved == [
        ("PIPE-1", {"6.1"}, 100),
        ("PIPE-1", {"6.2"}, 100),
        ("PIPE-1", {"6.1"}, 200),
        ("PIPE-1", {"6.2"}, 200),
    ]
    assert repo.modes == ["merge", "merge", "full_refresh", "merge"]
