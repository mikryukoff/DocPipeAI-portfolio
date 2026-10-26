"""Форматирование номера линии/трубопровода с единственным ведущим знаком №."""

from __future__ import annotations

import re

_LEADING_NUMBER_SIGN_RE = re.compile(r"^(?:№\s*)+")


def strip_leading_number_sign(value: str) -> str:
    """Убирает один или несколько ведущих знаков № (и пробелы сразу после них)."""
    return _LEADING_NUMBER_SIGN_RE.sub("", (value or "").strip())


def normalize_pipeline_name(value: str) -> str:
    """Каноническое имя линии для БД и сопоставления: без ведущего №."""
    return strip_leading_number_sign(value)


def format_with_number_sign(value: str) -> str:
    """Возвращает значение с ровно одним ведущим №."""
    body = strip_leading_number_sign(value)
    return f"№{body}" if body else ""
