"""Разбиение DOCX на логические страницы по явным разрывам страницы (w:br w:type=\"page\")."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from docx import Document
from docx.table import Table
from docx.oxml.ns import qn


_WS_RE = re.compile(r"\s+")


def _normalize_spaces(text: str) -> str:
    return _WS_RE.sub(" ", (text or "").strip())


def _iter_paragraph_events(p_element):
    """
    События внутри w:p: ('text', str) — фрагмент текста, ('page',) — разрыв страницы после него.
    """
    buf: list[str] = []
    for run in p_element.findall(qn("w:r")):
        for el in run:
            if el.tag == qn("w:t"):
                buf.append(el.text or "")
            elif el.tag == qn("w:br"):
                if el.get(qn("w:type")) == "page":
                    chunk = "".join(buf)
                    buf = []
                    if chunk.strip():
                        yield ("text", _normalize_spaces(chunk))
                    yield ("page",)
    tail = "".join(buf)
    if tail.strip():
        yield ("text", _normalize_spaces(tail))


@dataclass
class LogicalPage:
    """Один логический лист: строки абзацев (по порядку) и таблицы (по порядку в теле)."""

    paragraph_lines: list[str] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)


def iter_logical_pages(doc: Document) -> list[LogicalPage]:
    """
    Обходит document.element.body в порядке Word: абзацы и таблицы чередуются.
    Разрыв страницы внутри абзаца или отдельным абзацем начинает новый LogicalPage.
    Если разрывов нет — один элемент в списке.
    """
    pages: list[LogicalPage] = [LogicalPage()]
    body = doc.element.body
    table_idx = 0

    for child in body:
        if child.tag == qn("w:p"):
            for ev in _iter_paragraph_events(child):
                if ev[0] == "text":
                    pages[-1].paragraph_lines.append(ev[1])
                else:
                    pages.append(LogicalPage())
        elif child.tag == qn("w:tbl"):
            if table_idx >= len(doc.tables):
                break
            pages[-1].tables.append(doc.tables[table_idx])
            table_idx += 1

    return pages
