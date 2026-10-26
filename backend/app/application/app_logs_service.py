from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any

from backend.app.config import Config
from backend.app.shared.user_data_paths import user_logs_dir_from_segment
from backend.app.shared.user_log_key import sanitize_path_segment


@dataclass
class AppLogsQuery:
    user_log_key: str
    date_from: str | None = None
    date_to: str | None = None
    limit: int = 200
    offset: int = 0
    level: str = "error"
    text: str | None = None


class AppLogsService:
    @staticmethod
    def _local_tz():
        return datetime.now().astimezone().tzinfo or timezone.utc

    def __init__(self, config: Config):
        self.config = config

    def list_events(self, query: AppLogsQuery) -> list[dict[str, Any]]:
        rows = self._load_events(query.user_log_key)
        filtered = [row for row in rows if self._match(row, query)]
        filtered.sort(key=self._sort_key, reverse=True)
        if query.offset > 0:
            filtered = filtered[query.offset:]
        return filtered[: max(1, min(query.limit, 1000))]

    def clear_logs(self, *, user_log_key: str) -> int:
        logs_dir = user_logs_dir_from_segment(
            self.config, sanitize_path_segment(user_log_key or "anonymous")
        )
        removed = 0
        for path in logs_dir.glob("app_*.jsonl"):
            if not path.is_file():
                continue
            path.unlink(missing_ok=True)
            removed += 1
        return removed

    def _load_events(self, user_log_key: str) -> list[dict[str, Any]]:
        logs_dir = user_logs_dir_from_segment(self.config, sanitize_path_segment(user_log_key))
        rows: list[dict[str, Any]] = []
        for path in sorted(logs_dir.glob("app_*.jsonl")):
            if not path.is_file():
                continue
            rows.extend(self._read_app_jsonl(path))
        return rows

    def _read_app_jsonl(self, path: Path) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                item = self._parse_json_line(line)
                if not item:
                    continue
                rows.append(
                    {
                        "ts": self._to_local_iso(item.get("timestamp")),
                        "level": item.get("level"),
                        "message": item.get("message"),
                        "request_id": item.get("request_id"),
                        "user_log_key": item.get("user_log_key"),
                        "path": item.get("path"),
                        "status_code": item.get("status_code"),
                        "error_type": item.get("error_type"),
                        "error_message": item.get("error_message"),
                        "source_stream": "app_errors",
                        "raw": item,
                    }
                )
        return rows

    @staticmethod
    def _parse_json_line(line: str) -> dict[str, Any] | None:
        text = (line or "").strip()
        if not text:
            return None
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    def _match(self, event: dict[str, Any], query: AppLogsQuery) -> bool:
        if not self._match_level(event, query.level):
            return False
        if not self._match_date(event, query):
            return False
        needle = (query.text or "").strip().lower()
        if needle:
            haystack = " ".join(
                [
                    str(event.get("message") or ""),
                    str(event.get("path") or ""),
                    str(event.get("error_message") or ""),
                    str(event.get("request_id") or ""),
                ]
            ).lower()
            if needle not in haystack:
                return False
        return True

    @staticmethod
    def _match_level(event: dict[str, Any], level_filter: str) -> bool:
        level_name = str(event.get("level") or "").upper()
        message = str(event.get("message") or "")
        mode = (level_filter or "error").strip().lower()
        if mode == "all":
            return True
        if mode == "warn":
            return level_name in {"WARNING", "ERROR", "CRITICAL"} or message == "Request failed"
        # default: error only
        return level_name in {"ERROR", "CRITICAL"} or message == "Request failed"

    def _match_date(self, event: dict[str, Any], query: AppLogsQuery) -> bool:
        dt = self._parse_ts(event.get("ts"))
        dt_from = self._parse_date_boundary(query.date_from, end=False)
        dt_to = self._parse_date_boundary(query.date_to, end=True)
        if dt_from or dt_to:
            if dt is None:
                return False
            if dt_from and dt < dt_from:
                return False
            if dt_to and dt > dt_to:
                return False
        return True

    @staticmethod
    def _parse_ts(value: Any) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            try:
                dt = datetime.strptime(text, "%Y-%m-%d %H:%M:%S.%f")
            except ValueError:
                return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=AppLogsService._local_tz())
        return dt.astimezone(AppLogsService._local_tz())

    @staticmethod
    def _to_local_iso(value: Any) -> str | None:
        dt = AppLogsService._parse_ts(value)
        if dt is None:
            text = str(value or "").strip()
            return text or None
        return dt.isoformat()

    @staticmethod
    def _parse_date_boundary(value: str | None, *, end: bool) -> datetime | None:
        text = (value or "").strip()
        if not text:
            return None
        try:
            day = datetime.fromisoformat(text).date()
        except ValueError:
            return None
        bound = time.max if end else time.min
        return datetime.combine(day, bound, tzinfo=AppLogsService._local_tz())

    @staticmethod
    def _sort_key(event: dict[str, Any]) -> datetime:
        dt = AppLogsService._parse_ts(event.get("ts"))
        if dt is None:
            return datetime.min.replace(tzinfo=AppLogsService._local_tz())
        return dt
