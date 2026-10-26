from io import BytesIO
from pathlib import Path
import zipfile

import pytest
from fastapi import UploadFile

from backend.app.api.file_utils import extract_archive
from backend.app.application.exceptions import ValidationError


def _zip_upload(name: str, files: dict[str, bytes], content_type: str = "application/zip") -> UploadFile:
    payload = BytesIO()
    with zipfile.ZipFile(payload, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for inner_name, data in files.items():
            zf.writestr(inner_name, data)
    payload.seek(0)
    return UploadFile(file=payload, filename=name, headers={"content-type": content_type})


def test_extract_archive_skips_traversal_entries(tmp_path: Path):
    archive = _zip_upload(
        "docs.zip",
        {
            "../outside.pdf": b"nope",
            "/absolute.pdf": b"nope",
            "safe.pdf": b"ok",
            "nested/inner.pdf": b"ok2",
        },
    )

    extracted = extract_archive(
        archive,
        tmp_path,
        {".pdf"},
        allowed_mime_types={"application/zip"},
    )
    names = sorted(path.name for path in extracted)
    assert names == ["inner.pdf", "safe.pdf"]
    assert not (tmp_path / "outside.pdf").exists()


def test_extract_archive_avoids_name_collision_overwrite(tmp_path: Path):
    archive = _zip_upload(
        "docs.zip",
        {
            "safe.pdf": b"first",
            "nested/safe.pdf": b"second",
        },
    )
    extracted = extract_archive(archive, tmp_path, {".pdf"})
    names = sorted(path.name for path in extracted)
    assert names == ["safe.pdf", "safe_1.pdf"]
    assert (tmp_path / "safe.pdf").read_bytes() == b"first"
    assert (tmp_path / "safe_1.pdf").read_bytes() == b"second"


def test_extract_archive_rejects_wrong_mime(tmp_path: Path):
    archive = _zip_upload(
        "docs.zip",
        {"safe.pdf": b"ok"},
        content_type="text/plain",
    )
    with pytest.raises(ValidationError) as exc_info:
        extract_archive(
            archive,
            tmp_path,
            {".pdf"},
            allowed_mime_types={"application/zip"},
        )
    assert exc_info.value.details.get("reason") == "unsupported_archive_mime"
