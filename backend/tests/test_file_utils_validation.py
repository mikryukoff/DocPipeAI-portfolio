from io import BytesIO
from pathlib import Path

import pytest
from fastapi import UploadFile

from backend.app.api.file_utils import save_upload_files
from backend.app.application.exceptions import ValidationError


def _upload(name: str, data: bytes, content_type: str) -> UploadFile:
    return UploadFile(file=BytesIO(data), filename=name, headers={"content-type": content_type})


def test_save_upload_files_validates_mime_and_size(tmp_path: Path):
    file = _upload("test.pdf", b"x" * 10, "application/pdf")
    result = save_upload_files(
        [file],
        tmp_path,
        {".pdf"},
        allowed_mime_types={"application/pdf"},
        max_size_bytes=20,
    )
    assert len(result) == 1
    assert result[0].exists()

    file_too_large = _upload("big.pdf", b"x" * 25, "application/pdf")
    with pytest.raises(ValidationError) as exc_info:
        save_upload_files(
            [file_too_large],
            tmp_path,
            {".pdf"},
            allowed_mime_types={"application/pdf"},
            max_size_bytes=20,
        )
    assert exc_info.value.details.get("reason") == "file_too_large"
    assert exc_info.value.details.get("filename") == "big.pdf"
    assert exc_info.value.details.get("max_size_bytes") == 20


def test_save_upload_files_rejects_invalid_mime(tmp_path: Path):
    file = _upload("test.pdf", b"x" * 10, "text/plain")
    with pytest.raises(ValidationError) as exc_info:
        save_upload_files(
            [file],
            tmp_path,
            {".pdf"},
            allowed_mime_types={"application/pdf"},
            max_size_bytes=20,
        )
    assert exc_info.value.details.get("reason") == "unsupported_mime"
    assert exc_info.value.details.get("filename") == "test.pdf"


def test_save_upload_files_rejects_invalid_extension(tmp_path: Path):
    file = _upload("test.txt", b"x" * 10, "text/plain")
    with pytest.raises(ValidationError) as exc_info:
        save_upload_files([file], tmp_path, {".pdf"})
    assert exc_info.value.details.get("reason") == "unsupported_extension"
    assert exc_info.value.details.get("filename") == "test.txt"
