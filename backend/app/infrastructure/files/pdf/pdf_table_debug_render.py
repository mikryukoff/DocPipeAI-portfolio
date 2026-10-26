"""Рендер PNG: обрезка областей страницы и debug_tablefinder (pdfplumber)."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pdfplumber

from backend.app.infrastructure.files.pdf.pdf_table_extractor import (
    PARAMS_TABLE_CROP_BOX,
    SPEC_TABLE_CROP_BOX,
)

_DEFAULT_TABLE_SETTINGS: dict[str, Any] = {
    "snap_x_tolerance": 1,
    "snap_y_tolerance": 1,
}


def render_pdf_crop_region_png(
    pdf_path: str | Path,
    *,
    page_num: int = 1,
    crop_box: tuple[float, float, float, float],
    resolution: int = 150,
) -> bytes:
    """Растровый снимок прямоугольной области страницы (без debug_tablefinder)."""
    path = Path(pdf_path)
    if not path.is_file():
        raise FileNotFoundError(str(path))

    with pdfplumber.open(path) as pdf:
        if page_num < 1 or page_num > len(pdf.pages):
            raise ValueError(f"page_num out of range: {page_num}")
        page = pdf.pages[page_num - 1]
        cropped = page.crop(crop_box)
        img = cropped.to_image(resolution=resolution)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()


def render_pdf_crop_tablefinder_debug_png(
    pdf_path: str | Path,
    *,
    page_num: int = 1,
    crop_box: tuple[float, float, float, float],
    resolution: int = 150,
    table_settings: dict[str, Any] | None = None,
) -> bytes:
    """
    Обрезка области + ``PageImage.debug_tablefinder`` — как ``pdfplumber_table_debug`` (snap1).
    Красные линии и узлы сетки таблиц поверх растра.
    """
    path = Path(pdf_path)
    if not path.is_file():
        raise FileNotFoundError(str(path))

    settings = dict(_DEFAULT_TABLE_SETTINGS)
    if table_settings:
        settings.update(table_settings)

    with pdfplumber.open(path) as pdf:
        if page_num < 1 or page_num > len(pdf.pages):
            raise ValueError(f"page_num out of range: {page_num}")
        page = pdf.pages[page_num - 1]
        cropped = page.crop(crop_box)
        img = cropped.to_image(resolution=resolution)
        img.debug_tablefinder(table_settings=settings)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()


def render_drawing_check_table_snapshots(
    pdf_path: str | Path,
    *,
    page_num: int = 1,
    resolution: int = 150,
) -> tuple[bytes, bytes]:
    """Два PNG с визуализацией границ таблиц: области параметров и спецификации."""
    params_png = render_pdf_crop_tablefinder_debug_png(
        pdf_path,
        page_num=page_num,
        crop_box=PARAMS_TABLE_CROP_BOX,
        resolution=resolution,
    )
    spec_png = render_pdf_crop_tablefinder_debug_png(
        pdf_path,
        page_num=page_num,
        crop_box=SPEC_TABLE_CROP_BOX,
        resolution=resolution,
    )
    return params_png, spec_png


def render_pdf_table_debug_png(
    pdf_path: str | Path,
    *,
    page_num: int = 1,
    crop: str = "spec",
    resolution: int = 150,
    table_settings: dict[str, Any] | None = None,
) -> bytes:
    """
    Страница ``page_num`` (1-based), обрезка ``spec`` — как в ``pdfplumber_table_debug`` / импорте спецификации,
    ``full`` — вся страница без crop.
    """
    path = Path(pdf_path)
    if not path.is_file():
        raise FileNotFoundError(str(path))

    crop_key = (crop or "spec").strip().lower()
    if crop_key not in {"spec", "full"}:
        raise ValueError(f"unsupported crop: {crop!r}")

    settings = dict(_DEFAULT_TABLE_SETTINGS)
    if table_settings:
        settings.update(table_settings)

    with pdfplumber.open(path) as pdf:
        if page_num < 1 or page_num > len(pdf.pages):
            raise ValueError(f"page_num out of range: {page_num}")
        page = pdf.pages[page_num - 1]
        work = page.crop(SPEC_TABLE_CROP_BOX) if crop_key == "spec" else page

        img = work.to_image(resolution=resolution)
        img.debug_tablefinder(table_settings=settings)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
