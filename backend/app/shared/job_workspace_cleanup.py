"""Безопасное удаление каталога задачи data/users/.../jobs/{job_id}/."""

from __future__ import annotations

import shutil
from pathlib import Path

from backend.app.config import load_config


def maybe_delete_job_workspace(*, job_workspace: str | Path | None, job_id: int) -> None:
    if not job_workspace:
        return
    cfg = load_config()
    if not cfg.user_data.delete_job_uploads_after_completion:
        return
    p = Path(job_workspace).resolve()
    users_root = (Path(cfg.user_data.base_path) / "users").resolve()
    try:
        p.relative_to(users_root)
    except ValueError:
        return
    parts = p.parts
    if "jobs" not in parts:
        return
    ji = parts.index("jobs")
    if ji + 1 >= len(parts) or parts[ji + 1] != str(job_id):
        return
    shutil.rmtree(p, ignore_errors=True)
