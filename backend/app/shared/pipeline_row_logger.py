from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from backend.app.config import load_config
from backend.app.shared.log_redaction import basename_only, redact_pipeline_row_cells
from backend.app.shared.user_data_paths import user_logs_dir_from_segment
from backend.app.shared.user_log_key import sanitize_path_segment


def _get_log_path(user_log_key: Optional[str] = None) -> Path:
    cfg = load_config()
    return user_logs_dir_from_segment(cfg, user_log_key or "anonymous") / "pipeline_rows.jsonl"


def log_pipeline_row(
    *,
    job_id: Optional[int],
    user_log_key: str | None = None,
    source: str | None,
    pipeline: str,
    page: str | None,
    row_type: str,
    row: Iterable[str],
) -> None:
    path = _get_log_path(user_log_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    row_list = list(row)
    payload = {
        "ts": datetime.now().astimezone().isoformat(),
        "job_id": job_id,
        "user_log_key": sanitize_path_segment(user_log_key) if user_log_key else None,
        "source": basename_only(source) if source else None,
        "pipeline": redact_pipeline_row_cells([pipeline], cell_max=80, max_cells=1)[0],
        "page": page,
        "row_type": row_type,
        "row": redact_pipeline_row_cells(row_list),
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
