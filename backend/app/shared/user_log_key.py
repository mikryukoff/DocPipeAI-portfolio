"""Идентификатор пользователя для имён файлов логов (безопасные символы)."""

from __future__ import annotations

import re


def sanitize_path_segment(key: str) -> str:
    s = (key or "anonymous").strip()
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", s)[:80] or "anonymous"


def format_user_log_key(*, user_id: int | None, username: str | None = None) -> str:
    if user_id is None:
        return "anonymous"
    if username and username.strip():
        safe = sanitize_path_segment(username.strip())[:48].strip("._-") or ""
        if safe:
            return safe
    return f"id{user_id}"
