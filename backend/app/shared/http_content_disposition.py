"""HTTP Content-Disposition с поддержкой UTF-8 имён файлов (RFC 5987)."""

from __future__ import annotations

from urllib.parse import quote


def attachment_content_disposition(filename: str) -> dict[str, str]:
    """
    Заголовок для скачивания файла. ASCII fallback + filename* для кириллицы.
    Starlette кодирует заголовки в latin-1 — сырой Unicode в filename= ломает ответ.
    """
    name = (filename or "download").replace("\r", "").replace("\n", "")
    ascii_fallback = "".join(
        ch if ord(ch) < 128 and ch not in {'"', "\\"} else "_"
        for ch in name
    ).strip() or "download"
    encoded = quote(name, safe="")
    value = (
        f"attachment; filename=\"{ascii_fallback}\"; "
        f"filename*=UTF-8''{encoded}"
    )
    return {"Content-Disposition": value}
