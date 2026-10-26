"""Безопасное разрешение путей к crop-изображениям закладных (parsed_texts / crop_page)."""

from __future__ import annotations

from pathlib import Path


def resolve_safe_crop_file(
    relative_path: str,
    *,
    project_root: Path,
    allowed_crop_root: Path,
) -> Path | None:
    raw = (relative_path or "").strip().replace("\\", "/")
    if not raw or raw.startswith("..") or Path(raw).is_absolute():
        return None
    rel = Path(raw)
    full = (project_root / rel).resolve()
    crop = allowed_crop_root.resolve()
    try:
        full.relative_to(crop)
    except ValueError:
        return None
    if full.is_file():
        return full
    return None
