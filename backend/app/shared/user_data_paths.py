"""Пути вида data/users/{логин}/jobs/{job_id}/... под загрузки и логи пользователя."""

from __future__ import annotations

from pathlib import Path

from backend.app.config import Config
from backend.app.shared.user_log_key import format_user_log_key, sanitize_path_segment


def user_segment(*, user_id: int | None, username: str | None = None) -> str:
    return format_user_log_key(user_id=user_id, username=username)


def user_root(cfg: Config, *, user_id: int | None, username: str | None = None) -> Path:
    return Path(cfg.user_data.base_path) / "users" / user_segment(user_id=user_id, username=username)


def user_logs_dir(cfg: Config, *, user_id: int | None, username: str | None = None) -> Path:
    return user_root(cfg, user_id=user_id, username=username) / "logs"


def job_dir(cfg: Config, *, user_id: int | None, username: str | None, job_id: int) -> Path:
    return user_root(cfg, user_id=user_id, username=username) / "jobs" / str(job_id)


def job_uploads_dir(cfg: Config, *, user_id: int | None, username: str | None, job_id: int) -> Path:
    return job_dir(cfg, user_id=user_id, username=username, job_id=job_id) / "uploads"


def job_inspect_dir(cfg: Config, *, user_id: int | None, username: str | None, job_id: int) -> Path:
    return job_dir(cfg, user_id=user_id, username=username, job_id=job_id) / "inspect"


def user_passports_dir(cfg: Config, *, user_id: int | None, username: str | None = None) -> Path:
    return user_root(cfg, user_id=user_id, username=username) / "passports"


def security_audit_dir(cfg: Config) -> Path:
    """Общий каталог для security_audit_*.jsonl (не персональные логи)."""
    return Path(cfg.logger.logs_path)


def config_store_json_path(filename: str) -> Path:
    """Путь к JSON в общем каталоге конфигов (`CONFIG_DATA_PATH`)."""
    from backend.app.config import load_config

    cfg = load_config()
    base = Path(cfg.user_data.config_path)
    base.mkdir(parents=True, exist_ok=True)
    return base / filename


def user_logs_dir_from_segment(cfg: Config, segment: str) -> Path:
    """Каталог логов по уже вычисленному сегменту (как в user_log_key / ContextVar)."""
    seg = sanitize_path_segment(segment or "anonymous")
    d = Path(cfg.user_data.base_path) / "users" / seg / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d
