from collections.abc import AsyncIterator
from time import time
from pathlib import Path
from typing import Callable

import pdfplumber
from loguru import logger
from backend.app.infrastructure.files.pdf.models import PDFTable
from backend.app.infrastructure.files.pdf.pdf_table_cleaner import clean_table


# Координатные области для разных таблиц на листе (из отладочного скрипта):
# (x0, top, x1, bottom) в единицах PDF.
SPEC_TABLE_CROP_BOX: tuple[float, float, float, float] = (
    790.0,  # x0 — левая граница области спецификации
    40.0,   # top — верхняя граница
    1181.0, # x1 — правая граница
    680.0,  # bottom — нижняя граница
)
PARAMS_TABLE_CROP_BOX: tuple[float, float, float, float] = (
    55.0,   # x0 — левая граница области параметров
    655.0,  # top — верхняя граница
    655.0,  # x1 — правая граница
    830.0,  # bottom — нижняя граница
)
MAIN_TABLE_CROP_BOX: tuple[float, float, float, float] = (
    680.0,  # x0 — левая граница основной таблицы (подписи, рамки и т.п.)
    675.0,  # top — верхняя граница
    1181.0, # x1 — правая граница
    830.0,  # bottom — нижняя граница
)


class PDFTableExtractor:
    @staticmethod
    def _table_settings() -> dict[str, int]:
        # Глобальные настройки сетки: аналог пресета snap1 из отладочного скрипта.
        # snap_x/y_tolerance=1 дают аккуратную сетку для всех нужных таблиц.
        return {
            "snap_x_tolerance": 1,
            "snap_y_tolerance": 1,
        }

    @staticmethod
    def _extract_rows_from_crop(
        *,
        page,
        page_num: int,
        crop_box: tuple[float, float, float, float],
        table_settings: dict[str, int],
        first_table_only: bool = False,
    ) -> list[list[str]]:
        cropped = page.crop(crop_box)
        raw = cropped.extract_tables(table_settings=table_settings) or []
        if first_table_only and raw:
            raw = raw[:1]
        logger.debug(
            "Extracted raw tables from crop. page={} crop_box={} count={} first_table_only={}",
            page_num,
            crop_box,
            len(raw),
            first_table_only,
        )
        rows: list[list[str]] = []
        for t in raw:
            cleaned = clean_table(t)
            if not cleaned:
                continue
            rows.extend(cleaned)
        return rows

    def _extract_page_tables(self, *, page, page_num: int) -> list[PDFTable]:
        table_settings = self._table_settings()
        params_rows = self._extract_rows_from_crop(
            page=page,
            page_num=page_num,
            crop_box=PARAMS_TABLE_CROP_BOX,
            table_settings=table_settings,
        )
        spec_rows = self._extract_rows_from_crop(
            page=page,
            page_num=page_num,
            crop_box=SPEC_TABLE_CROP_BOX,
            table_settings=table_settings,
            first_table_only=False,
        )
        main_rows = self._extract_rows_from_crop(
            page=page,
            page_num=page_num,
            crop_box=MAIN_TABLE_CROP_BOX,
            table_settings=table_settings,
        )
        page_tables: list[PDFTable] = []
        # ВАЖНО: не смешиваем строки разных таблиц.
        # В парсер параметров должны идти только строки из таблицы параметров,
        # в парсер спецификации — только строки таблицы спецификации.
        if params_rows:
            page_tables.append(
                PDFTable(
                    page=str(page_num),
                    rows=params_rows + main_rows,
                    kind="params",
                )
            )
        if spec_rows:
            page_tables.append(
                PDFTable(
                    page=str(page_num),
                    rows=spec_rows,
                    kind="spec",
                )
            )
        return page_tables

    def extract_single_page(
        self,
        *,
        pdf_path: str | Path,
        page_num: int = 1,
    ) -> tuple[list[list[str]], list[list[str]]]:
        with pdfplumber.open(pdf_path) as pdf:
            pages = pdf.pages
            if page_num < 1 or page_num > len(pages):
                raise ValueError(f"page_num out of range: {page_num}")
            page = pages[page_num - 1]
            page_tables = self._extract_page_tables(page=page, page_num=page_num)

        params_rows: list[list[str]] = []
        spec_rows: list[list[str]] = []
        for table in page_tables:
            if table.kind == "params":
                params_rows = table.rows
            elif table.kind == "spec":
                spec_rows = table.rows
        return params_rows, spec_rows

    async def iter_tables_by_page(
            self,
            pdf_path: str | Path,
            start_page: int = 1,
            on_progress: Callable | None = None,
    ) -> AsyncIterator[tuple[int, list[PDFTable]]]:
        with pdfplumber.open(pdf_path) as pdf:
            pages = pdf.pages
            first_data_page = max(1, start_page)
            total_pages = max(len(pages) - first_data_page + 1, 1)
            logger.info("Open PDF for extraction. path={} pages={} data_pages={}", pdf_path, len(pages), total_pages)

            processed = 0

            for page_num, page in enumerate(pages, 1):
                if page_num < first_data_page:
                    continue

                processed += 1
                page_tables = self._extract_page_tables(page=page, page_num=page_num)

                progress = int(processed / total_pages * 100)
                if on_progress is not None:
                    # В on_progress передаём только прогресс по файлу, без статистики —
                    # агрегированные stats обновляются на уровне импортёров/батч-сервисов.
                    await on_progress(
                        progress=progress,
                        extra=None,
                    )

                logger.debug("Page extraction completed. page={} cleaned_tables={} progress={}", page_num, len(page_tables), progress)
                yield page_num, page_tables
