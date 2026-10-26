from pathlib import Path
from types import SimpleNamespace

from backend.app.shared import job_workspace_cleanup as cleanup_module


def _cfg(*, base_path: Path, enabled: bool):
    return SimpleNamespace(
        user_data=SimpleNamespace(
            base_path=str(base_path),
            delete_job_uploads_after_completion=enabled,
        )
    )


def test_maybe_delete_job_workspace_removes_valid_workspace(monkeypatch, tmp_path: Path):
    users_root = tmp_path / "data" / "users"
    workspace = users_root / "user_1" / "jobs" / "55"
    (workspace / "uploads").mkdir(parents=True, exist_ok=True)
    (workspace / "uploads" / "file.pdf").write_text("x", encoding="utf-8")

    monkeypatch.setattr(cleanup_module, "load_config", lambda: _cfg(base_path=tmp_path / "data", enabled=True))
    cleanup_module.maybe_delete_job_workspace(job_workspace=workspace, job_id=55)
    assert not workspace.exists()


def test_maybe_delete_job_workspace_ignores_outside_paths(monkeypatch, tmp_path: Path):
    workspace = tmp_path / "outside" / "jobs" / "55"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "file.pdf").write_text("x", encoding="utf-8")

    monkeypatch.setattr(cleanup_module, "load_config", lambda: _cfg(base_path=tmp_path / "data", enabled=True))
    cleanup_module.maybe_delete_job_workspace(job_workspace=workspace, job_id=55)
    assert workspace.exists()


def test_maybe_delete_job_workspace_respects_job_id(monkeypatch, tmp_path: Path):
    users_root = tmp_path / "data" / "users"
    workspace = users_root / "user_1" / "jobs" / "99"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "file.pdf").write_text("x", encoding="utf-8")

    monkeypatch.setattr(cleanup_module, "load_config", lambda: _cfg(base_path=tmp_path / "data", enabled=True))
    cleanup_module.maybe_delete_job_workspace(job_workspace=workspace, job_id=77)
    assert workspace.exists()
