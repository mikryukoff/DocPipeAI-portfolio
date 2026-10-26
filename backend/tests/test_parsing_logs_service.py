import json

from backend.app.application.parsing_logs_service import ParsingLogsQuery, ParsingLogsService


class _Cfg:
    class _UD:
        base_path = ""

    user_data = _UD()


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_parsing_logs_service_merges_and_filters(tmp_path):
    cfg = _Cfg()
    cfg.user_data.base_path = str(tmp_path)
    logs_dir = tmp_path / "users" / "admin" / "logs"
    _write_jsonl(
        logs_dir / "parsing_audit.jsonl",
        [
            {
                "ts": "2026-04-15T10:00:00+00:00",
                "user_log_key": "admin",
                "source_type": "excel",
                "source_file": "act.xlsx",
                "entity_id": "41041",
                "field": "strength_test_pressure",
                "value": "1,17 МПа",
            }
        ],
    )
    _write_jsonl(
        logs_dir / "pipeline_rows.jsonl",
        [
            {
                "ts": "2026-04-15T09:00:00+00:00",
                "user_log_key": "admin",
                "source": "doc.pdf",
                "pipeline": "41041",
                "row_type": "line",
                "row": ["a", "b"],
            }
        ],
    )
    _write_jsonl(
        logs_dir / "invalid_pipelines.jsonl",
        [
            {
                "ts": "2026-04-15T08:00:00+00:00",
                "user_log_key": "admin",
                "source": "bad.pdf",
                "pipeline": "99999",
                "section": "specification",
                "error": "no_specifications_in_file",
            }
        ],
    )
    svc = ParsingLogsService(config=cfg)

    rows = svc.list_events(
        ParsingLogsQuery(
            login="admin",
            pipeline="41041",
            date_from="2026-04-15",
            date_to="2026-04-15",
            file_type="excel",
            limit=50,
            offset=0,
        )
    )
    assert len(rows) == 1
    assert rows[0]["source_stream"] == "parsing_audit"
    assert rows[0]["pipeline"] == "41041"


def test_parsing_logs_service_clear_logs(tmp_path):
    cfg = _Cfg()
    cfg.user_data.base_path = str(tmp_path)
    logs_dir = tmp_path / "users" / "admin" / "logs"
    _write_jsonl(logs_dir / "parsing_audit.jsonl", [{"x": 1}])
    _write_jsonl(logs_dir / "pipeline_rows.jsonl", [{"x": 2}])
    _write_jsonl(logs_dir / "invalid_pipelines.jsonl", [{"x": 3}])

    svc = ParsingLogsService(config=cfg)
    removed = svc.clear_logs(login="admin")

    assert removed == 3
    assert not (logs_dir / "parsing_audit.jsonl").exists()
    assert not (logs_dir / "pipeline_rows.jsonl").exists()
    assert not (logs_dir / "invalid_pipelines.jsonl").exists()

