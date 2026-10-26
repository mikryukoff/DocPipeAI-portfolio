from __future__ import annotations

from pathlib import Path


def safe_filename_stem(raw_name: str, *, max_len: int = 120) -> str | None:
    raw = (raw_name or "").strip().replace("\\", "/")
    if not raw:
        return None
    if "/" in raw:
        return None

    base = Path(raw).name.strip()
    stem = Path(base).stem.strip()
    if not stem:
        return None
    if stem in {".", ".."} or ".." in stem:
        return None
    if "\x00" in stem or "/" in stem or "\\" in stem:
        return None
    return stem[:max_len]


def resolve_safe_file(
    *,
    output_dir: Path,
    filename_stem: str,
    suffix: str,
) -> Path | None:
    if not suffix.startswith("."):
        return None
    root = output_dir.resolve()
    candidate = (root / f"{filename_stem}{suffix}").resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate
