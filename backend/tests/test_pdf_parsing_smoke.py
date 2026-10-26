from pathlib import Path

import pytest

from backend.app.infrastructure.files.pdf.pdf_table_extractor import PDFTableExtractor
from backend.app.domain.parsing.parse_pipeline_from_tables import ParsePipelineFromTables


@pytest.mark.asyncio
async def test_pdf_parsing_smoke_writes_debug_logs() -> None:
    """
    Небольшой "smoke"-тест, который прогоняет несколько реальных PDF-файлов
    через PDFTableExtractor + ParsePipelineFromTables и сохраняет краткий отчёт
    в лог-файлы. Нужен для быстрой ручной проверки без поднятия Docker.
    """
    # Ищем пару PDF в data/raw/pdf (если их нет — просто пропускаем тест).
    pdf_dir = Path("data/raw/pdf")
    if not pdf_dir.exists():
        pytest.skip("data/raw/pdf directory not found, skipping smoke test")

    pdf_files = sorted(pdf_dir.glob("*.pdf"))[:2]
    if not pdf_files:
        pytest.skip("No PDF files found in data/raw/pdf, skipping smoke test")

    extractor = PDFTableExtractor()

    for pdf_path in pdf_files:
        parser = ParsePipelineFromTables(source=str(pdf_path))

        async for _page_num, page_tables in extractor.iter_tables_by_page(
            pdf_path=pdf_path,
            start_page=1,
            on_progress=None,
        ):
            parser.process_tables(page_tables)

        pipelines = parser.snapshot()

        # Пишем подробный текстовый отчёт по файлу.
        log_path = Path("data/logs/tests/parsing") / f"{pdf_path.stem}_parse_report.txt"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("w", encoding="utf-8") as f:
            f.write(f"PDF: {pdf_path}\n")
            f.write(f"Pipelines total: {len(pipelines)}\n")
            f.write(f"Spec items total: {parser.spec_items_count()}\n\n")

            for p in pipelines:
                f.write(f"=== PIPELINE {p.name} ===\n")
                f.write(f"Medium: {p.medium}\n")
                f.write(f"Mounting scheme: {p.mounting_scheme}\n")
                f.write(f"Flow direction: {p.flow_direction}\n")
                f.write(f"Parameters:\n  {p.parameters}\n")
                f.write(f"Pipelines_len: {p.pipelines_len}\n")
                f.write(f"Specifications count: {len(p.specifications)}\n")
                for spec in p.specifications:
                    f.write(f"\n  --- SPEC page={spec.page} ---\n")
                    f.write(f"  Armature ({len(spec.pipeline_armature)}):\n")
                    for item in spec.pipeline_armature:
                        f.write(f"    {item}\n")
                    f.write(f"  Pipes ({len(spec.pipes)}):\n")
                    for item in spec.pipes:
                        f.write(f"    {item}\n")
                    f.write(f"  Connection parts ({len(spec.connection_parts)}):\n")
                    for item in spec.connection_parts:
                        f.write(f"    {item}\n")
                    f.write(f"  Flanges ({len(spec.flanges)}):\n")
                    for item in spec.flanges:
                        f.write(f"    {item}\n")
                    f.write(f"  Supports ({len(spec.supports)}):\n")
                    for item in spec.supports:
                        f.write(f"    {item}\n")
                f.write("\n")

        assert log_path.exists()
        assert log_path.stat().st_size > 0

