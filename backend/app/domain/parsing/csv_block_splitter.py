import re
from loguru import logger

from backend.app.domain.models.table_block import TableBlock
from backend.app.infrastructure.files.pdf.models import PDFTable
from backend.app.shared.pipeline_name_extract import (
    extract_line_pipeline_name,
    extract_pipeline_name_from_cell,
    looks_like_pipeline_code,
)
from backend.app.shared.pipeline_number_format import normalize_pipeline_name


class CSVBlockSplitter:
    """
    Режет таблицу на логические блоки трубопроводов.
    Для таблиц, содержащих только один трубопровод.
    """

    @staticmethod
    def _filter_nonempty_rows(rows: list[list[str]]) -> list[list[str]]:
        out: list[list[str]] = []
        for row in rows:
            if any(cell and cell.strip() for cell in row):
                out.append(row)
        return out

    def split_spec_for_params_pipeline(
        self, table: PDFTable, pipeline_name: str
    ) -> list[TableBlock]:
        """
        Таблица спецификации (отдельный crop) привязывается к имени линии из таблицы
        параметров на той же странице, а не к подписи «Линия …» внутри спецификации.
        """
        name = normalize_pipeline_name(pipeline_name or "")
        if not name:
            return []
        return [
            TableBlock(
                pipeline_name=name,
                page="",
                rows=self._filter_nonempty_rows(table.rows),
            )
        ]

    def split(self, table: PDFTable) -> list[TableBlock]:
        blocks: list[TableBlock] = []

        # Ищем название трубопровода и страницу во всей таблице
        pipeline_name, page = self._find_pipeline_in_table(table.rows)

        if pipeline_name:
            blocks.append(
                TableBlock(
                    pipeline_name=pipeline_name,
                    page=page or "",
                    rows=self._filter_nonempty_rows(table.rows),
                )
            )

        return blocks

    @staticmethod
    def _find_pipeline_in_table(rows: list[list[str]]) -> tuple[str, str]:
        """Ищет название трубопровода и страницу во всей таблице"""
        first_pipeline_name = ""
        second_pipeline_name = ""
        pipeline_name = ""
        page = None

        # Ищем ячейку "Наименование линии / класс трубопровода"
        # и берём следующую непустую ячейку (полностью, чтобы не обрезать код типа XX01-41038-PSL-65).
        for row in rows:
            for i, cell in enumerate(row):
                if cell and ("Наименование линии / класс трубопровода" in cell):
                    for j in range(i + 1, len(row)):
                        next_cell = row[j]
                        if next_cell and next_cell.strip():
                            first_pipeline_name = extract_pipeline_name_from_cell(
                                next_cell.strip()
                            )
                            break
                    else:
                        continue
                    break

        for row in rows:
            for cell in row:
                if not cell:
                    continue
                line_name = extract_line_pipeline_name(cell.strip())
                if line_name:
                    second_pipeline_name = line_name
                    break

        candidates = [
            n
            for n in (first_pipeline_name, second_pipeline_name)
            if n and n.strip()
        ]
        code_like = [n for n in candidates if looks_like_pipeline_code(n)]
        pipeline_name = normalize_pipeline_name(
            max(code_like or candidates, key=len, default="")
        )

        logger.debug("pipeline_name={}", pipeline_name)
        return pipeline_name, page

    @staticmethod
    def _is_old_page(row: list[str]) -> bool:
        return len(row) == 1 and re.fullmatch(r"\d+\.\d+", row[0])

    @staticmethod
    def _is_new_page(row: list[str]) -> bool:
        return "ИД" in row