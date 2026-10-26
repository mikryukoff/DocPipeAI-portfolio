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
class ParsingLogsQuery:
    login: str
    pipeline: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    file_type: str | None = None
    limit: int = 200
    offset: int = 0


class ParsingLogsService:
    @staticmethod
    def _local_tz():
        return datetime.now().astimezone().tzinfo or timezone.utc

    _ALLOWED_FILES = (
        "parsing_audit.jsonl",
        "pipeline_rows.jsonl",
        "parsing_rows.jsonl",  # backward compatibility alias
        "invalid_pipelines.jsonl",
    )

    def __init__(self, config: Config):
        self.config = config

    def list_events(self, query: ParsingLogsQuery) -> list[dict[str, Any]]:
        events = self._load_events(query.login)
        filtered = [e for e in events if self._match(e, query)]
        filtered.sort(key=self._sort_key, reverse=True)
        if query.offset > 0:
            filtered = filtered[query.offset :]
        return filtered[: max(1, min(query.limit, 1000))]

    def stream_events_jsonl(self, query: ParsingLogsQuery):
        events = self.list_events(ParsingLogsQuery(**{**query.__dict__, "limit": 100000, "offset": 0}))
        for event in events:
            yield (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8")

    def clear_logs(self, *, login: str) -> int:
        removed = 0
        logs_dir = self._logs_dir(login)
        for name in self._ALLOWED_FILES:
            p = (logs_dir / name).resolve()
            try:
                p.relative_to(logs_dir.resolve())
            except ValueError:
                continue
            if p.exists():
                p.unlink()
                removed += 1
        return removed

    def _load_events(self, login: str) -> list[dict[str, Any]]:
        logs_dir = self._logs_dir(login)
        out: list[dict[str, Any]] = []
        for name in self._ALLOWED_FILES:
            path = (logs_dir / name).resolve()
            try:
                path.relative_to(logs_dir.resolve())
            except ValueError:
                continue
            if not path.exists() or not path.is_file():
                continue
            if path.name == "parsing_audit.jsonl":
                out.extend(self._load_parsing_audit(path))
            elif path.name == "invalid_pipelines.jsonl":
                out.extend(self._load_invalid_pipeline_rows(path))
            else:
                out.extend(self._load_pipeline_rows(path))
        return out

    def _load_parsing_audit(self, path: Path) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                item = self._parse_json_line(line)
                if not item:
                    continue
                rows.append(
                    {
                        "ts": self._to_local_iso(item.get("ts")),
                        "user_log_key": item.get("user_log_key"),
                        "pipeline": item.get("entity_id"),
                        "source_type": item.get("source_type"),
                        "source_file": item.get("source_file"),
                        "field": item.get("field"),
                        "value": item.get("value"),
                        "source_stream": "parsing_audit",
                        "raw": item,
                    }
                )
        return rows

    def _load_pipeline_rows(self, path: Path) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                item = self._parse_json_line(line)
                if not item:
                    continue
                rows.append(
                    {
                        "ts": self._to_local_iso(item.get("ts")),
                        "user_log_key": item.get("user_log_key"),
                        "pipeline": item.get("pipeline"),
                        "source_type": self._infer_file_type(item),
                        "source_file": item.get("source"),
                        "field": item.get("row_type"),
                        "value": item.get("row"),
                        "source_stream": "pipeline_rows",
                        "raw": item,
                    }
                )
        return rows

    def _load_invalid_pipeline_rows(self, path: Path) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                item = self._parse_json_line(line)
                if not item:
                    continue
                rows.append(
                    {
                        "ts": self._to_local_iso(item.get("ts")),
                        "user_log_key": item.get("user_log_key"),
                        "pipeline": item.get("pipeline"),
                        "source_type": self._infer_file_type(item),
                        "source_file": item.get("source"),
                        "field": item.get("section") or item.get("kind"),
                        "value": item.get("error"),
                        "source_stream": "invalid_pipelines",
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

    def _logs_dir(self, login: str) -> Path:
        return user_logs_dir_from_segment(self.config, sanitize_path_segment(login or "anonymous"))

    def _match(self, event: dict[str, Any], query: ParsingLogsQuery) -> bool:
        pipeline = (query.pipeline or "").strip().lower()
        if pipeline:
            candidates = [
                str(event.get("pipeline") or "").lower(),
                str(event.get("source_file") or "").lower(),
            ]
            if not any(pipeline in c for c in candidates):
                return False

        file_type = (query.file_type or "").strip().lower()
        if file_type:
            evt_type = str(event.get("source_type") or "").lower()
            if evt_type != file_type:
                return False

        dt = self._parse_ts(event.get("ts"))
        dt_from = self._parse_date_boundary(query.date_from, end=False)
        dt_to = self._parse_date_boundary(query.date_to, end=True)
        if dt_from or dt_to:
            # Старые pipeline_rows без ts не проходят date-фильтр.
            if dt is None:
                return False
            if dt_from and dt < dt_from:
                return False
            if dt_to and dt > dt_to:
                return False

        return True

    @staticmethod
    def _sort_key(event: dict[str, Any]) -> datetime:
        dt = ParsingLogsService._parse_ts(event.get("ts"))
        if dt is None:
            return datetime.min.replace(tzinfo=ParsingLogsService._local_tz())
        return dt

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
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ParsingLogsService._local_tz())
        return dt.astimezone(ParsingLogsService._local_tz())

    @staticmethod
    def _to_local_iso(value: Any) -> str | None:
        dt = ParsingLogsService._parse_ts(value)
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
        return datetime.combine(day, bound, tzinfo=ParsingLogsService._local_tz())

    @staticmethod
    def _infer_file_type(item: dict[str, Any]) -> str:
        source = str(item.get("source") or "").lower()
        if source.endswith(".pdf"):
            return "pdf"
        if source.endswith(".docx"):
            return "word"
        if source.endswith(".xlsx") or source.endswith(".xls") or source.endswith(".xlsm"):
            return "excel"
        return "unknown"
