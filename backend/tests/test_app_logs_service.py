import json

from backend.app.application.app_logs_service import AppLogsQuery, AppLogsService


class _Cfg:
    class _UD:
        base_path = ""

    user_data = _UD()


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_app_logs_service_filters_error_rows(tmp_path):
    cfg = _Cfg()
    cfg.user_data.base_path = str(tmp_path)
    logs_dir = tmp_path / "users" / "admin" / "logs"
    _write_jsonl(
        logs_dir / "app_2026-04-27.jsonl",
        [
            {
                "timestamp": "2026-04-27 09:00:00.000",
                "level": "INFO",
                "message": "Request handled",
                "path": "/health",
            },
            {
                "timestamp": "2026-04-27 09:01:00.000",
                "level": "ERROR",
                "message": "Request failed",
                "path": "/pipelines/from-pdf",
                "error_message": "File validation failed",
                "request_id": "req-1",
            },
        ],
    )
    svc = AppLogsService(config=cfg)
    rows = svc.list_events(
        AppLogsQuery(
            user_log_key="admin",
            level="error",
            limit=50,
            offset=0,
        )
    )
    assert len(rows) == 1
    assert rows[0]["message"] == "Request failed"
    assert rows[0]["request_id"] == "req-1"


def test_app_logs_service_filters_by_text_and_date(tmp_path):
    cfg = _Cfg()
    cfg.user_data.base_path = str(tmp_path)
    logs_dir = tmp_path / "users" / "admin" / "logs"
    _write_jsonl(
        logs_dir / "app_2026-04-27.jsonl",
        [
            {
                "timestamp": "2026-04-26 23:59:59.000",
                "level": "ERROR",
                "message": "Request failed",
                "path": "/old",
                "error_message": "old error",
            },
            {
                "timestamp": "2026-04-27 10:00:00.000",
                "level": "ERROR",
                "message": "Request failed",
                "path": "/pipelines/from-word",
                "error_message": "word error",
            },
        ],
    )
    svc = AppLogsService(config=cfg)
    rows = svc.list_events(
        AppLogsQuery(
            user_log_key="admin",
            date_from="2026-04-27",
            date_to="2026-04-27",
            text="word",
            level="error",
            limit=50,
            offset=0,
        )
    )
    assert len(rows) == 1
    assert rows[0]["path"] == "/pipelines/from-word"


def test_app_logs_service_clear_logs_removes_only_app_jsonl(tmp_path):
    cfg = _Cfg()
    cfg.user_data.base_path = str(tmp_path)
    logs_dir = tmp_path / "users" / "admin" / "logs"
    _write_jsonl(
        logs_dir / "app_2026-04-27.jsonl",
        [{"timestamp": "2026-04-27 10:00:00.000", "level": "ERROR", "message": "Request failed"}],
    )
    _write_jsonl(
        logs_dir / "parsing_audit.jsonl",
        [{"ts": "2026-04-27T10:00:00Z", "field": "x"}],
    )

    svc = AppLogsService(config=cfg)
    removed = svc.clear_logs(user_log_key="admin")

    assert removed == 1
    assert not (logs_dir / "app_2026-04-27.jsonl").exists()
    assert (logs_dir / "parsing_audit.jsonl").exists()
