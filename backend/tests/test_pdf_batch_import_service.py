from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from backend.app.application.imports.pdf_batch_import_service import PdfBatchImportService


class _FakeJobService:
    def __init__(self):
        self.progress_calls: list[dict] = []
        self.finish_calls: list[dict] = []
        self.fail_calls: list[dict] = []
        self.started_job_ids: list[int] = []

    async def start_processing(self, job_id: int):
        self.started_job_ids.append(job_id)

    async def update_progress(self, job_id: int, progress: int | None = None, extra: dict | None = None):
        self.progress_calls.append(
            {
                "job_id": job_id,
                "progress": progress,
                "extra": dict(extra or {}),
            }
        )

    async def finish(self, job_id: int, progress: int = 100):
        self.finish_calls.append({"job_id": job_id, "progress": progress})

    async def fail(self, job_id: int, error: str):
        self.fail_calls.append({"job_id": job_id, "error": error})


class _FakeImporter:
    def __init__(self):
        self.calls = 0

    async def run_from_page(self, *_args, **_kwargs):
        self.calls += 1
        if self.calls == 1:
            # Первый файл успешно дал статистику.
            return {
                "invalid_records": [],
                "blocked_pipelines": [],
                "pages_in_file": 4,
                "spec_items_in_file": 12,
                "all_pipelines_in_file": ["PIPE-1", "PIPE-2"],
                "valid_pipelines_in_file": ["PIPE-1", "PIPE-2"],
            }
        # Второй файл вернул ошибку без page/spec-метрик (как при частичных сбоях).
        return {
            "invalid_records": [
                {
                    "kind": "error",
                    "source": "2.pdf",
                    "pipeline": None,
                    "page": None,
                    "section": "file_import",
                    "row": [],
                    "error": "boom",
                }
            ],
            "blocked_pipelines": [],
            "valid_pipelines_in_file": [],
        }

    async def embedment_markers_all_resolved(self, _markers):
        return True


class _FakeImporterWithUndefined:
    async def run_from_page(self, *_args, **_kwargs):
        return {
            "invalid_records": [
                {
                    "kind": "section_undefined",
                    "source": "11-2.pdf",
                    "pipeline": None,
                    "page": "2",
                    "section": "not_defined",
                    "item_name": "Арматура",
                    "full_name": "Арматура фланцевая Ду50 Ру16",
                    "row": [],
                    "error": "spec_section_not_defined: Арматура",
                }
            ],
            "blocked_pipelines": [],
            "pages_in_file": 3,
            "spec_items_in_file": 0,
            "all_pipelines_in_file": [],
            "valid_pipelines_in_file": [],
        }

    async def embedment_markers_all_resolved(self, _markers):
        return True


class _FakeRepoForDup:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def delete_by_name(self, name: str) -> None:
        self.deleted.append(name)


class _FakeImporterCrossFileDuplicate:
    """Два файла с разным первым числом в имени и одной и той же линией."""

    def __init__(self) -> None:
        self.repo = _FakeRepoForDup()

    @asynccontextmanager
    async def repo_factory(self):
        yield self.repo

    async def run_from_page(self, *_args, **_kwargs):
        return {
            "invalid_records": [],
            "blocked_pipelines": [],
            "pages_in_file": 1,
            "spec_items_in_file": 1,
            "all_pipelines_in_file": ["SAME-PIPE"],
            "valid_pipelines_in_file": ["SAME-PIPE"],
        }

    async def embedment_markers_all_resolved(self, _markers):
        return True


class _FakeImporterSamePrefixTwoFiles:
    """222.1 и 222.2 — один префикс 222, одна линия, без кросс-дубликата."""

    async def run_from_page(self, *_args, **_kwargs):
        return {
            "invalid_records": [],
            "blocked_pipelines": [],
            "pages_in_file": 1,
            "spec_items_in_file": 1,
            "all_pipelines_in_file": ["PIPE-A"],
            "valid_pipelines_in_file": ["PIPE-A"],
        }

    async def embedment_markers_all_resolved(self, _markers):
        return True


class _FakeImporterSamePrefixPipelineMismatch:
    """1-1 и 1-2 — префикс 1, разные линии — несовпадение в группе."""

    def __init__(self) -> None:
        self.repo = _FakeRepoForDup()
        self._call = 0

    @asynccontextmanager
    async def repo_factory(self):
        yield self.repo

    async def run_from_page(self, *_args, **_kwargs):
        self._call += 1
        pipeline = "LINE-ONE" if self._call == 1 else "LINE-TWO"
        return {
            "invalid_records": [],
            "blocked_pipelines": [],
            "pages_in_file": 1,
            "spec_items_in_file": 1,
            "all_pipelines_in_file": [pipeline],
            "valid_pipelines_in_file": [pipeline],
        }

    async def embedment_markers_all_resolved(self, _markers):
        return True


@pytest.mark.asyncio
async def test_pdf_batch_does_not_reuse_stale_spec_items_when_file_has_no_stats():
    job_service = _FakeJobService()
    importer = _FakeImporter()
    service = PdfBatchImportService(job_service=job_service, importer=importer)

    await service._run(
        job_id=777,
        pdf_paths=[Path("1.pdf"), Path("2.pdf")],
        user_log_key="admin",
        job_workspace=None,
    )

    assert job_service.started_job_ids == [777]
    assert not job_service.fail_calls
    assert job_service.finish_calls == [{"job_id": 777, "progress": 99}]

    # Берём последний апдейт прогресса (после второго файла).
    final_progress = job_service.progress_calls[-1]["extra"]
    assert final_progress["files_processed"] == 2
    assert final_progress["pages"] == 4
    assert final_progress["spec_items"] == 12
    assert final_progress["spec_items_total"] == 12


@pytest.mark.asyncio
async def test_pdf_batch_reports_full_name_for_undefined_spec_items():
    job_service = _FakeJobService()
    importer = _FakeImporterWithUndefined()
    service = PdfBatchImportService(job_service=job_service, importer=importer)

    await service._run(
        job_id=778,
        pdf_paths=[Path("11-2.pdf")],
        user_log_key="admin",
        job_workspace=None,
    )

    final_progress = job_service.progress_calls[-1]["extra"]
    assert final_progress["undefined_spec_names"] == ["Арматура"]
    assert final_progress["undefined_spec_full_names"] == {
        "Арматура": "Арматура фланцевая Ду50 Ру16",
    }


@pytest.mark.asyncio
async def test_pdf_batch_cross_file_duplicate_prefix_blocks_and_deletes():
    job_service = _FakeJobService()
    importer = _FakeImporterCrossFileDuplicate()
    service = PdfBatchImportService(job_service=job_service, importer=importer)

    await service._run(
        job_id=779,
        pdf_paths=[Path("148.pdf"), Path("149.pdf"), Path("150.pdf")],
        user_log_key="admin",
        job_workspace=None,
    )

    assert importer.repo.deleted == ["SAME-PIPE"]
    final_extra = job_service.progress_calls[-1]["extra"]
    assert "SAME-PIPE" in final_extra["blocked_pipelines"]
    invalid_rows = final_extra.get("invalid_rows") or []
    dup_rows = [r for r in invalid_rows if r.get("section") == "cross_file_duplicate"]
    assert len(dup_rows) == 3
    sources = {str(r.get("source")) for r in dup_rows}
    assert sources == {"148.pdf", "149.pdf", "150.pdf"}
    assert job_service.finish_calls == [{"job_id": 779, "progress": 99}]


class _FakeImporterDotHierarchyTwoFiles:
    """1.1 и 1.1.1 — разные числовые группы, разные линии в PDF."""

    def __init__(self) -> None:
        self._call = 0

    async def run_from_page(self, *_args, **_kwargs):
        self._call += 1
        pipeline = "PIPE-ONE" if self._call == 1 else "PIPE-TWO"
        return {
            "invalid_records": [],
            "blocked_pipelines": [],
            "pages_in_file": 1,
            "spec_items_in_file": 1,
            "all_pipelines_in_file": [pipeline],
            "valid_pipelines_in_file": [pipeline],
        }

    async def embedment_markers_all_resolved(self, _markers):
        return True


@pytest.mark.asyncio
async def test_pdf_batch_dot_hierarchy_files_not_same_prefix_group():
    """1.1 и 1.1.1 — разные числовые группы, не считаются одним трубопроводом по префиксу."""
    job_service = _FakeJobService()
    importer = _FakeImporterDotHierarchyTwoFiles()
    service = PdfBatchImportService(job_service=job_service, importer=importer)

    await service._run(
        job_id=782,
        pdf_paths=[Path("1.1.pdf"), Path("1.1.1.pdf")],
        user_log_key="admin",
        job_workspace=None,
    )

    final_extra = job_service.progress_calls[-1]["extra"]
    invalid_rows = final_extra.get("invalid_rows") or []
    assert not any(r.get("section") == "cross_file_prefix_mismatch" for r in invalid_rows)
    assert not any(r.get("section") == "cross_file_duplicate" for r in invalid_rows)
    assert not final_extra.get("blocked_pipelines")
    assert job_service.finish_calls == [{"job_id": 782, "progress": 100}]


@pytest.mark.asyncio
async def test_pdf_batch_same_first_numeric_prefix_no_cross_duplicate():
    job_service = _FakeJobService()
    importer = _FakeImporterSamePrefixTwoFiles()
    service = PdfBatchImportService(job_service=job_service, importer=importer)

    await service._run(
        job_id=780,
        pdf_paths=[Path("222.1.pdf"), Path("222.2.pdf")],
        user_log_key="admin",
        job_workspace=None,
    )

    final_extra = job_service.progress_calls[-1]["extra"]
    invalid_rows = final_extra.get("invalid_rows") or []
    assert not any(r.get("section") == "cross_file_duplicate" for r in invalid_rows)
    assert not final_extra.get("blocked_pipelines")
    assert job_service.finish_calls == [{"job_id": 780, "progress": 100}]


@pytest.mark.asyncio
async def test_pdf_batch_same_prefix_different_pipelines_blocks_and_deletes():
    job_service = _FakeJobService()
    importer = _FakeImporterSamePrefixPipelineMismatch()
    service = PdfBatchImportService(job_service=job_service, importer=importer)

    await service._run(
        job_id=781,
        pdf_paths=[Path("1-1.pdf"), Path("1-2.pdf"), Path("1-3.pdf")],
        user_log_key="admin",
        job_workspace=None,
    )

    assert sorted(importer.repo.deleted) == ["LINE-ONE", "LINE-TWO"]
    final_extra = job_service.progress_calls[-1]["extra"]
    assert sorted(final_extra["blocked_pipelines"]) == ["LINE-ONE", "LINE-TWO"]
    invalid_rows = final_extra.get("invalid_rows") or []
    mismatch_rows = [r for r in invalid_rows if r.get("section") == "cross_file_prefix_mismatch"]
    assert len(mismatch_rows) == 3
    sources = {str(r.get("source")) for r in mismatch_rows}
    assert sources == {"1-1.pdf", "1-2.pdf", "1-3.pdf"}
    assert job_service.finish_calls == [{"job_id": 781, "progress": 99}]
