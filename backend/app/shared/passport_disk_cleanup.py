"""Удаление сгенерированных файлов паспортов на диске после отдачи клиенту."""

from __future__ import annotations

from pathlib import Path


def unlink_generated_passport_files(output_dir: Path, pipeline_names: list[str]) -> None:
    for raw in pipeline_names:
        name = Path(raw).name
        if not name:
            continue
        (output_dir / f"{name}.docx").unlink(missing_ok=True)
        (output_dir / f"{name}.docx.enc").unlink(missing_ok=True)
