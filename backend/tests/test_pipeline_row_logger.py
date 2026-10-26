import json
from datetime import datetime

from backend.app.shared import pipeline_row_logger


def test_log_pipeline_row_writes_ts(monkeypatch, tmp_path):
    log_path = tmp_path / "pipeline_rows.jsonl"
    monkeypatch.setattr(pipeline_row_logger, "_get_log_path", lambda _=None: log_path)

    pipeline_row_logger.log_pipeline_row(
        job_id=1,
        user_log_key="admin",
        source="demo.pdf",
        pipeline="41041",
        page="1",
        row_type="line",
        row=["a", "b"],
    )

    payload = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert "ts" in payload
    assert datetime.fromisoformat(payload["ts"].replace("Z", "+00:00"))

