from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.app.config import load_config
from backend.app.shared.log_redaction import basename_only, truncate_str
from backend.app.shared.user_data_paths import user_logs_dir_from_segment
from backend.app.shared.user_log_key import sanitize_path_segment


def _get_log_path(user_log_key: str | None = None) -> Path:
    cfg = load_config()
    return user_logs_dir_from_segment(cfg, user_log_key or "anonymous") / "invalid_pipelines.jsonl"


def _sanitize_event(event: dict[str, Any]) -> dict[str, Any]:
    out = dict(event)
    if "source" in out and out["source"]:
        out["source"] = basename_only(str(out["source"]))
    row = out.get("row")
    if isinstance(row, list):
        out["row"] = [truncate_str(str(x), 100) for x in row[:20]]
        if len(row) > 20:
            out["row"].append(f"… +{len(row) - 20} cells")
    if "error" in out and out["error"]:
        out["error"] = truncate_str(str(out["error"]), 500)
    if "full_name" in out:
        out["full_name"] = truncate_str(str(out.get("full_name", "")), 200)
    if "item_name" in out:
        out["item_name"] = truncate_str(str(out.get("item_name", "")), 200)
    return out


def log_invalid_pipeline_event(
    event: dict[str, Any],
    *,
    user_log_key: str | None = None,
) -> None:
    path = _get_log_path(user_log_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _sanitize_event(event)
    payload["user_log_key"] = sanitize_path_segment(user_log_key) if user_log_key else None
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
