from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.app.config import load_config
from backend.app.shared.log_redaction import basename_only, redact_origin, redact_value
from backend.app.shared.user_data_paths import user_logs_dir_from_segment
from backend.app.shared.user_log_key import sanitize_path_segment


def _get_log_path(user_log_key: str | None = None) -> Path:
    cfg = load_config()
    return user_logs_dir_from_segment(cfg, user_log_key or "anonymous") / "parsing_audit.jsonl"


def log_parsing_event(
    *,
    job_id: int | None,
    user_log_key: str | None = None,
    source_type: str,
    source_file: str,
    parser: str,
    entity: str,
    entity_id: str | None,
    field: str,
    value: Any,
    origin: dict[str, Any] | None = None,
    status: str = "parsed",
    note: str | None = None,
) -> None:
    """
    Компактная трассировка парсинга. Файл: data/users/<user>/logs/parsing_audit.jsonl
    """
    payload = {
        "ts": datetime.now().astimezone().isoformat(),
        "job_id": job_id,
        "user_log_key": sanitize_path_segment(user_log_key) if user_log_key else None,
        "status": status,
        "source_type": source_type,
        "source_file": basename_only(source_file),
        "parser": parser,
        "entity": entity,
        "entity_id": entity_id,
        "field": field,
        "value": redact_value(value, max_len=400),
        "origin": redact_origin(origin),
        "note": redact_value(note, 300) if note else None,
    }
    path = _get_log_path(user_log_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
