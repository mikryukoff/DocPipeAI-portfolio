"""Извлечение номера линии и продолжительности испытания из DOCX (протокол испытаний)."""

from __future__ import annotations

import re

from docx import Document

from backend.app.infrastructure.files.docx.docx_logical_pages import LogicalPage, iter_logical_pages
from backend.app.shared.pipeline_code_confusables import normalize_pipeline_code_confusable_o_to_zero
from backend.app.shared.pipeline_name_extract import (
    extract_line_pipeline_name,
    is_cyrillic_line_number,
)

_ANCHOR = "участков трубопровода"
_DURATION = "Продолжительность испытания"
_INT_RE = re.compile(r"\d+")


def _flatten_page_lines(page: LogicalPage) -> list[str]:
    lines: list[str] = list(page.paragraph_lines)
    for table in page.tables:
        for row in table.rows:
            parts = [c.text.strip() for c in row.cells if c.text.strip()]
            if parts:
                lines.append(" ".join(parts))
    return lines


def _find_line_after_anchor(lines: list[str]) -> int | None:
    for i, line in enumerate(lines):
        if _ANCHOR in line.lower():
            return i
    return None


def _find_pipeline_line(lines: list[str], start_index: int) -> str | None:
    for line in lines[start_index + 1 :]:
        s = line.strip()
        if not s:
            continue
        label = extract_line_pipeline_name(s)
        if label:
            return label
    return None


def _find_test_duration_minutes(lines: list[str]) -> str | None:
    for i, line in enumerate(lines):
        if _DURATION.lower() not in line.lower():
            continue
        m = _INT_RE.search(line)
        if m:
            return m.group(0)
        for nxt in lines[i + 1 : i + 3]:
            m2 = _INT_RE.search(nxt)
            if m2:
                return m2.group(0)
    return None


def extract_pipelines_tests_from_logical_page(page: LogicalPage) -> dict[str, str] | None:
    lines = _flatten_page_lines(page)
    anchor_i = _find_line_after_anchor(lines)
    if anchor_i is None:
        return None
    pipeline = _find_pipeline_line(lines, anchor_i)
    test_time = _find_test_duration_minutes(lines)
    if not pipeline or not test_time:
        return None
    if is_cyrillic_line_number(pipeline):
        pipeline_name = pipeline
    else:
        pipeline_name = normalize_pipeline_code_confusable_o_to_zero(pipeline)
    return {
        "pipeline": pipeline_name,
        "test_time": test_time,
    }


def extract_pipelines_tests_rows_from_document(
    doc: Document,
    *,
    pages_limit: int = 0,
) -> list[dict[str, str]]:
    pages = iter_logical_pages(doc)
    if pages_limit > 0:
        pages = pages[:pages_limit]

    rows: list[dict[str, str]] = []
    for page in pages:
        row = extract_pipelines_tests_from_logical_page(page)
        if row is not None:
            rows.append(row)

    return rows
