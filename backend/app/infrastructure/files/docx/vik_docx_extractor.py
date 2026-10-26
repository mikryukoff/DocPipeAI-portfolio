"""Извлечение данных ВИК из DOCX по правилам раздела «ЗАКЛЮЧЕНИЕ» и таблицы «Конструкция, узел»."""

from __future__ import annotations

import re

from docx import Document
from loguru import logger

from backend.app.infrastructure.files.docx.docx_logical_pages import LogicalPage, iter_logical_pages

_STATEMENT_MARK = "ЗАКЛЮЧЕНИЕ"
_STATEMENT_TOKEN_RE = re.compile(r"([A-Za-zА-Яа-я0-9][A-Za-zА-Яа-я0-9./-]*)")
_CONSTRUCTION_RE = re.compile(
    r"Конструкция\s*,\s*узел\s*:?",
    re.IGNORECASE | re.UNICODE,
)


def _statement_after_heading(line: str) -> str | None:
    upper = line.upper()
    mark = _STATEMENT_MARK
    pos = upper.find(mark)
    if pos < 0:
        return None
    rest = line[pos + len(mark) :].strip()
    if not rest:
        return None
    match = _STATEMENT_TOKEN_RE.search(rest)
    if not match:
        return None
    return match.group(1).strip()


def _find_pipe_num_in_tables(tables) -> str | None:
    for table in tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            for i, cell_text in enumerate(cells):
                if _CONSTRUCTION_RE.search(cell_text):
                    # В merged-таблицах Word соседняя ячейка может дублировать заголовок.
                    # Берём первую следующую непустую ячейку, которая не совпадает с ключом.
                    for nxt in cells[i + 1 :]:
                        candidate = nxt.strip()
                        if not candidate:
                            continue
                        if _CONSTRUCTION_RE.search(candidate):
                            continue
                        return candidate
    return None


def extract_vik_from_logical_page(page: LogicalPage) -> dict[str, str] | None:
    """Одна логическая страница: «ЗАКЛЮЧЕНИЕ» + строка таблицы «Конструкция, узел» или None."""
    statement_text: str | None = None
    for line in page.paragraph_lines:
        st = _statement_after_heading(line)
        if st is not None:
            statement_text = st
            break

    if not statement_text:
        return None

    pipe_num = _find_pipe_num_in_tables(page.tables)
    if not pipe_num:
        return None

    if len(statement_text) > 255:
        logger.warning(
            "VIK DOCX: statement_text truncated to 255 chars (was {} chars)",
            len(statement_text),
        )
        statement_text = statement_text[:255]

    return {"statement_text": statement_text, "pipe_num": pipe_num}


def extract_vik_rows_from_document(doc: Document, *, pages_limit: int = 0) -> list[dict[str, str]]:
    """
    Для каждой логической страницы: текст после «ЗАКЛЮЧЕНИЕ» и номер из таблицы.
    pages_limit > 0 — не более N первых логических страниц.
    """
    pages = iter_logical_pages(doc)
    if pages_limit > 0:
        pages = pages[:pages_limit]

    rows: list[dict[str, str]] = []
    for page in pages:
        row = extract_vik_from_logical_page(page)
        if row is not None:
            rows.append(row)

    return rows
