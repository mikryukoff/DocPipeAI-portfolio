import asyncio
from pathlib import Path

from backend.app.infrastructure.files.pdf.models import PDFTable
from backend.app.infrastructure.files.pdf.pdf_table_extractor import PDFTableExtractor


class _FakePage:
    def __init__(self, tables):
        self._tables = tables

    def extract_tables(self, **kwargs):
        return self._tables

    # В боевом коде используется page.crop(...), поэтому в фейковой странице
    # просто возвращаем себя же, чтобы таблицы не менялись.
    def crop(self, *_args, **_kwargs):
        return self


class _FakePDF:
    def __init__(self, pages):
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


def test_iter_tables_by_page_respects_start_page_and_reports_progress(monkeypatch):
    fake_pages = [
        _FakePage([]),  # 1
        _FakePage([]),  # 2
        _FakePage([]),  # 3
        _FakePage([]),  # 4
        _FakePage([]),  # 5
        _FakePage([[["A"]]]),  # 6
        _FakePage([[["B"]]]),  # 7
        _FakePage([]),  # 8
    ]

    def fake_open(_):
        return _FakePDF(fake_pages)

    monkeypatch.setattr(
        "backend.app.infrastructure.files.pdf.pdf_table_extractor.pdfplumber.open",
        fake_open,
    )
    monkeypatch.setattr(
        "backend.app.infrastructure.files.pdf.pdf_table_extractor.clean_table",
        lambda table: table,
    )

    async def _run():
        extractor = PDFTableExtractor()
        pages = []
        progress_updates = []

        async def _progress(progress: int, extra: dict):
            progress_updates.append((progress, extra))

        async for page_num, page_tables in extractor.iter_tables_by_page(
            pdf_path=Path("dummy.pdf"),
            start_page=6,
            on_progress=_progress,
        ):
            pages.append((page_num, page_tables))

        return pages, progress_updates

    pages, progress_updates = asyncio.run(_run())

    assert [p for p, _ in pages] == [6, 7, 8]
    assert isinstance(pages[0][1][0], PDFTable)
    assert pages[0][1][0].page == "6"
    # Для страницы 7 первая строка первой таблицы должна соответствовать "B".
    assert pages[1][1][0].rows[0] == ["B"]
    assert progress_updates[-1][0] == 100
    # extra не передаётся (агрегация stats на уровне импортёра)
    assert progress_updates[-1][1] is None
