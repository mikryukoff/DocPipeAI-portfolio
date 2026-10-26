import json
from datetime import UTC, datetime

from backend.app.api.routers.admin import (
    _invalid_pipeline_events_as_error_rows,
    _list_invalid_pipeline_events_for_admin_errors,
    _merge_error_rows,
)
from backend.app.api.schemas.auth import AppErrorLogResponse, JobErrorLogResponse
from backend.app.application.parsing_logs_service import ParsingLogsService


class _Cfg:
    class _UD:
        base_path = ""

    user_data = _UD()


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_list_invalid_pipeline_events_for_admin_errors_respects_text_filter(tmp_path):
    cfg = _Cfg()
    cfg.user_data.base_path = str(tmp_path)
    logs_dir = tmp_path / "users" / "admin" / "logs"
    _write_jsonl(
        logs_dir / "invalid_pipelines.jsonl",
        [
            {
                "ts": "2026-04-15T12:00:00+00:00",
                "user_log_key": "admin",
                "source": "a.pdf",
                "pipeline": "111",
                "section": "spec",
                "error": "boom_a",
            },
            {
                "ts": "2026-04-15T11:00:00+00:00",
                "user_log_key": "admin",
                "source": "b.pdf",
                "pipeline": "222",
                "section": "spec",
                "error": "boom_b",
            },
        ],
    )
    svc = ParsingLogsService(config=cfg)
    rows_all = _list_invalid_pipeline_events_for_admin_errors(
        svc,
        log_login="admin",
        date_from="2026-04-15",
        date_to="2026-04-15",
        file_type=None,
        text=None,
        cap=500,
    )
    assert len(rows_all) == 2
    rows_f = _list_invalid_pipeline_events_for_admin_errors(
        svc,
        log_login="admin",
        date_from="2026-04-15",
        date_to="2026-04-15",
        file_type=None,
        text="boom_b",
        cap=500,
    )
    assert len(rows_f) == 1
    assert rows_f[0].get("pipeline") == "222"


def test_merge_error_rows_sorts_invalid_pipeline_with_jobs():
    job = JobErrorLogResponse(
        id=1,
        user_id=5,
        filename="f.pdf",
        status="failed",
        error="job_err",
        extra=None,
        created_at=datetime(2026, 4, 15, 10, 0, 0, tzinfo=UTC),
    )
    app = AppErrorLogResponse(
        ts="2026-04-15T09:00:00+00:00",
        level="error",
        message="app_err",
        request_id=None,
        user_log_key="admin",
        path="/x",
        status_code=500,
        error_type="E",
        error_message="app_err",
        source_stream="app",
        raw={},
    )
    inv_ev = [
        {
            "ts": "2026-04-15T08:00:00+00:00",
            "pipeline": "999",
            "source_file": "bad.pdf",
            "field": "spec",
            "value": "no_spec",
            "source_stream": "invalid_pipelines",
            "raw": {},
        }
    ]
    inv_rows = _invalid_pipeline_events_as_error_rows(inv_ev, resolved_user_id=5)
    merged = _merge_error_rows(job_rows=[job], app_rows=[app], invalid_pipeline_rows=inv_rows)
    kinds = [m["source_kind"] for m in merged]
    assert kinds == ["job_error", "app_error", "invalid_pipeline"]
    assert merged[0]["ts"].startswith("2026-04-15T10")
    assert merged[2]["message"] == "no_spec"
    assert merged[2]["source_stream"] == "invalid_pipelines"
