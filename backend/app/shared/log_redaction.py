"""Сокращение и обезличивание полей для файловых логов."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def basename_only(path_or_name: str | None) -> str:
    if not path_or_name:
        return ""
    try:
        return Path(str(path_or_name)).name
    except Exception:
        return str(path_or_name)[:120]


def truncate_str(s: str, max_len: int = 400) -> str:
    t = (s or "").strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 20] + "… [truncated]"


def redact_value(value: Any, max_len: int = 400) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        return truncate_str(value, max_len)
    if isinstance(value, (int, float, bool)):
        return value
    try:
        raw = json.dumps(value, ensure_ascii=False)
    except TypeError:
        raw = str(value)
    return truncate_str(raw, max(200, max_len))


def redact_origin(origin: dict[str, Any] | None, *, row_text_max: int = 200) -> dict[str, Any]:
    if not origin:
        return {}
    out: dict[str, Any] = {}
    for k, v in origin.items():
        if k in ("row_text", "row", "full_name", "item_name", "note"):
            if isinstance(v, str):
                out[k] = truncate_str(v, row_text_max)
            elif isinstance(v, list):
                out[k] = [truncate_str(str(x), 80) for x in v[:20]]
            else:
                out[k] = redact_value(v, 200)
        elif k in ("source", "source_file", "current_file"):
            out[k] = basename_only(str(v)) if v else v
        else:
            out[k] = redact_value(v, 300) if not isinstance(v, (int, float, bool)) else v
    return out


def redact_pipeline_row_cells(row: list[str], *, cell_max: int = 100, max_cells: int = 16) -> list[str]:
    out: list[str] = []
    for i, cell in enumerate(row[:max_cells]):
        s = truncate_str(str(cell), cell_max)
        out.append(s)
    if len(row) > max_cells:
        out.append(f"… +{len(row) - max_cells} cols")
    return out
