from pathlib import Path
from typing import Iterable, Set
import shutil
import subprocess
import tempfile
import zipfile

import rarfile
from fastapi import UploadFile
from loguru import logger

from backend.app.application.exceptions import EmptyUploadError, ValidationError


def _to_mb(size_bytes: int | None) -> float | None:
    if size_bytes is None:
        return None
    return round(size_bytes / (1024 * 1024), 2)


def _validation_details(
    *,
    filename: str,
    reason: str,
    stage: str,
    content_type: str | None = None,
    allowed_exts: set[str] | None = None,
    allowed_mime_types: set[str] | None = None,
    max_size_bytes: int | None = None,
    actual_size_bytes: int | None = None,
    extra: dict | None = None,
) -> dict:
    details: dict = {
        "reason": reason,
        "stage": stage,
        "filename": filename,
        "files": [filename],
    }
    if content_type:
        details["content_type"] = content_type
    if allowed_exts:
        details["allowed_extensions"] = sorted(allowed_exts)
    if allowed_mime_types:
        details["allowed_mime_types"] = sorted(allowed_mime_types)
    if max_size_bytes is not None:
        details["max_size_bytes"] = int(max_size_bytes)
        details["max_size_mb"] = _to_mb(max_size_bytes)
    if actual_size_bytes is not None:
        details["actual_size_bytes"] = int(actual_size_bytes)
        details["actual_size_mb"] = _to_mb(actual_size_bytes)
    if extra:
        details.update(extra)
    return details


def _unique_dest_path(target_dir: Path, filename: str) -> Path:
    candidate = target_dir / filename
    if not candidate.exists():
        return candidate
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    index = 1
    while True:
        probe = target_dir / f"{stem}_{index}{suffix}"
        if not probe.exists():
            return probe
        index += 1


def _is_unsafe_archive_entry(name: str, inner_path: Path) -> bool:
    if not name.strip():
        return True
    if name.startswith(("/", "\\")):
        return True
    if inner_path.is_absolute():
        return True
    if ".." in inner_path.parts:
        return True
    return False


def _validate_upload(
    upload: UploadFile,
    *,
    allowed_exts: Set[str],
    allowed_mime_types: set[str] | None,
    max_size_bytes: int | None,
) -> tuple[str, bytes]:
    filename = Path(upload.filename).name if upload.filename else "uploaded"
    suffix = Path(filename).suffix.lower()
    if suffix not in allowed_exts:
        raise ValidationError(
            "File validation failed",
            details=_validation_details(
                filename=filename,
                reason="unsupported_extension",
                stage="upload_validation",
                allowed_exts=allowed_exts,
            ),
        )

    content_type = (upload.content_type or "").lower()
    if allowed_mime_types and content_type and content_type not in allowed_mime_types:
        raise ValidationError(
            "File validation failed",
            details=_validation_details(
                filename=filename,
                reason="unsupported_mime",
                stage="upload_validation",
                content_type=content_type,
                allowed_mime_types=allowed_mime_types,
            ),
        )

    payload = upload.file.read()
    if not payload:
        raise EmptyUploadError()
    if max_size_bytes is not None and len(payload) > max_size_bytes:
        raise ValidationError(
            "File validation failed",
            details=_validation_details(
                filename=filename,
                reason="file_too_large",
                stage="upload_validation",
                max_size_bytes=max_size_bytes,
                actual_size_bytes=len(payload),
            ),
        )
    return filename, payload


def save_upload_files(
    upload_files: Iterable[UploadFile],
    target_dir: Path,
    allowed_exts: Set[str],
    *,
    allowed_mime_types: set[str] | None = None,
    max_size_bytes: int | None = None,
) -> list[Path]:
    target_dir.mkdir(parents=True, exist_ok=True)
    result: list[Path] = []
    for f in upload_files:
        filename, payload = _validate_upload(
            f,
            allowed_exts=allowed_exts,
            allowed_mime_types=allowed_mime_types,
            max_size_bytes=max_size_bytes,
        )
        path = target_dir / filename
        path.write_bytes(payload)
        result.append(path)
    return result


def _extract_zip(
    tmp_path: Path,
    target_dir: Path,
    allowed_exts: Set[str],
) -> list[Path]:
    extracted: list[Path] = []
    with zipfile.ZipFile(tmp_path, "r") as zf:
        for info in zf.infolist():
            name = info.filename
            inner_path = Path(name)
            if _is_unsafe_archive_entry(name, inner_path):
                continue
            if info.is_dir():
                continue
            if inner_path.suffix.lower() not in allowed_exts:
                continue
            dest = _unique_dest_path(target_dir, inner_path.name)
            with zf.open(info) as src, dest.open("wb") as dst:
                dst.write(src.read())
            extracted.append(dest)
    return extracted


def _extract_rar(
    tmp_path: Path,
    target_dir: Path,
    allowed_exts: Set[str],
) -> list[Path]:
    extracted: list[Path] = []
    archive_name = tmp_path.name
    try:
        with rarfile.RarFile(tmp_path, "r") as rf:
            for info in rf.infolist():
                name = info.filename
                inner_path = Path(name)
                if _is_unsafe_archive_entry(name, inner_path):
                    continue
                if info.is_dir():
                    continue
                if inner_path.suffix.lower() not in allowed_exts:
                    continue
                dest = _unique_dest_path(target_dir, inner_path.name)
                dest.write_bytes(rf.read(info))
                extracted.append(dest)
    except rarfile.NeedFirstVolume:
        raise ValidationError(
            "Multi-volume RAR is not supported. Upload a single .rar file.",
            details=_validation_details(
                filename=archive_name,
                reason="rar_multivolume_not_supported",
                stage="archive_extract",
            ),
        )
    except rarfile.RarCannotExec as e:
        try:
            return _extract_rar_with_bsdtar(tmp_path, target_dir, allowed_exts)
        except RuntimeError:
            try:
                return _extract_rar_with_7z(tmp_path, target_dir, allowed_exts)
            except RuntimeError:
                pass
        raise ValidationError(
            "RAR extraction is unavailable on server: no supported unpack tool found. "
            "Install one of: unrar, 7z (p7zip), or bsdtar.",
            details=_validation_details(
                filename=archive_name,
                reason="rar_extraction_tool_unavailable",
                stage="archive_extract",
            ),
        ) from e
    except rarfile.Error as e:
        try:
            return _extract_rar_with_bsdtar(tmp_path, target_dir, allowed_exts)
        except RuntimeError:
            try:
                return _extract_rar_with_7z(tmp_path, target_dir, allowed_exts)
            except RuntimeError:
                pass
        raise ValidationError(
            f"Invalid or unsupported RAR archive: {e}",
            details=_validation_details(
                filename=archive_name,
                reason="archive_corrupted",
                stage="archive_extract",
            ),
        ) from e
    except Exception as e:
        if "unrar" in str(e).lower():
            raise ValidationError(
                "RAR extraction requires UnRAR. Install: Windows — install WinRAR/UnRAR; Linux — unrar; macOS — unar.",
                details=_validation_details(
                    filename=archive_name,
                    reason="rar_unrar_required",
                    stage="archive_extract",
                ),
            ) from e
        raise
    return extracted


def _extract_rar_with_7z(
    tmp_path: Path,
    target_dir: Path,
    allowed_exts: Set[str],
) -> list[Path]:
    with tempfile.TemporaryDirectory(prefix="rar_extract_") as tmp_extract_dir:
        cmd = ["7z", "e", "-y", f"-o{tmp_extract_dir}", str(tmp_path)]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("7z not found") from exc

        if proc.returncode != 0:
            details = (proc.stderr or proc.stdout or "unknown error").strip()
            raise RuntimeError(f"7z extraction failed: {details}")

        extracted: list[Path] = []
        for src in Path(tmp_extract_dir).iterdir():
            if not src.is_file():
                continue
            if src.suffix.lower() not in allowed_exts:
                continue
            dest = _unique_dest_path(target_dir, src.name)
            dest.write_bytes(src.read_bytes())
            extracted.append(dest)
        return extracted


def _extract_rar_with_bsdtar(
    tmp_path: Path,
    target_dir: Path,
    allowed_exts: Set[str],
) -> list[Path]:
    with tempfile.TemporaryDirectory(prefix="rar_extract_") as tmp_extract_dir:
        cmd = ["bsdtar", "-xf", str(tmp_path), "-C", tmp_extract_dir]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("bsdtar not found") from exc

        if proc.returncode != 0:
            details = (proc.stderr or proc.stdout or "unknown error").strip()
            raise RuntimeError(f"bsdtar extraction failed: {details}")

        extracted: list[Path] = []
        for src in Path(tmp_extract_dir).rglob("*"):
            if not src.is_file():
                continue
            if src.suffix.lower() not in allowed_exts:
                continue
            dest = _unique_dest_path(target_dir, src.name)
            dest.write_bytes(src.read_bytes())
            extracted.append(dest)
        return extracted


def extract_archive(
    archive: UploadFile,
    target_dir: Path,
    allowed_exts: Set[str],
    *,
    allowed_mime_types: set[str] | None = None,
    max_size_bytes: int | None = None,
) -> list[Path]:
    target_dir.mkdir(parents=True, exist_ok=True)
    archive_name = Path(archive.filename or "archive").name
    filename = archive_name.lower()
    archive_mime = (archive.content_type or "").lower()
    if allowed_mime_types and archive_mime and archive_mime not in allowed_mime_types:
        raise ValidationError(
            "File validation failed",
            details=_validation_details(
                filename=archive_name,
                reason="unsupported_archive_mime",
                stage="archive_validation",
                content_type=archive_mime,
                allowed_mime_types=allowed_mime_types,
            ),
        )
    is_rar = filename.endswith(".rar")
    suffix = ".rar" if is_rar else ".zip"

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        archive.file.seek(0)
        shutil.copyfileobj(archive.file, tmp, length=1024 * 1024)
        tmp_path = Path(tmp.name)

    try:
        archive_size = tmp_path.stat().st_size
        if archive_size == 0:
            raise EmptyUploadError()
        if max_size_bytes is not None and archive_size > max_size_bytes:
            raise ValidationError(
                "File validation failed",
                details=_validation_details(
                    filename=archive_name,
                    reason="archive_too_large",
                    stage="archive_validation",
                    max_size_bytes=max_size_bytes,
                    actual_size_bytes=archive_size,
                ),
            )
        if archive.size is not None and tmp_path.stat().st_size != archive.size:
            raise ValidationError(
                "File validation failed",
                details=_validation_details(
                    filename=archive_name,
                    reason="archive_size_mismatch",
                    stage="archive_validation",
                    actual_size_bytes=archive_size,
                    extra={"expected_size_bytes": int(archive.size)},
                ),
            )
        logger.info(
            "Archive accepted. stage=archive_extract filename={} size_bytes={} mime={}",
            archive_name,
            archive_size,
            archive_mime or "N/A",
        )
        if is_rar:
            return _extract_rar(tmp_path, target_dir, allowed_exts)
        return _extract_zip(tmp_path, target_dir, allowed_exts)
    finally:
        tmp_path.unlink(missing_ok=True)

