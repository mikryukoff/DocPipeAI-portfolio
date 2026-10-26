import pdfplumber
import io
import os
from enum import Enum
from typing import Sequence

from loguru import logger


class FormatPage(Enum):
    TEXT = "text"
    TABLE = "table"


class CropPage:
    @staticmethod
    def _validate_bbox(bbox: Sequence[float] | None) -> None:
        if bbox is None:
            raise ValueError("bbox не может быть None")
        if len(bbox) != 4:
            raise ValueError("bbox должен содержать 4 координаты: x1, y1, x2, y2")
        if not all(isinstance(value, (int, float)) for value in bbox):
            raise ValueError("bbox должен содержать только числа")

    @staticmethod
    def _process_cropped_image(
        page: pdfplumber.page.Page, bbox: Sequence[float], zoom_factor: int = 2
    ):
        """Выполняет обрезку, зумирование, фильтрацию и конвертацию в байты."""
        if zoom_factor <= 0:
            raise ValueError("zoom_factor должен быть > 0")
        CropPage._validate_bbox(bbox)

        from PIL import ImageFilter

        cropped_page = page.crop(bbox)
        zoomed_img = cropped_page.to_image(resolution=300 * zoom_factor, antialias=True)

        pil_img = zoomed_img.original
        pil_img = pil_img.filter(ImageFilter.MedianFilter(size=3))
        pil_img = pil_img.filter(ImageFilter.SMOOTH_MORE)

        img_byte_arr = io.BytesIO()
        pil_img.save(img_byte_arr, format="PNG")

        # Возвращаем и объект PIL (для сохранения на диск), и готовые байты
        return pil_img, img_byte_arr.getvalue()

    @staticmethod
    def _save_image(pil_img, save_path: str, zoom_factor: int) -> None:
        pil_img.save(save_path)
        logger.info(f"Сохранена увеличенная обрезка (zoom x{zoom_factor}): {save_path}")

    @staticmethod
    async def crop_passport_pdf(
        page: pdfplumber.page.Page,
        table: bool = False,
        is_visualitaion: bool = False,
        uuid_page: str | None = None,
        bbox: Sequence[float] | None = None,
        zoom_factor: int = 2,
    ):
        img_format = FormatPage.TABLE.value if table else FormatPage.TEXT.value

        # Вызываем общее ядро
        pil_img, img_byte_arr = CropPage._process_cropped_image(page, bbox, zoom_factor)

        uid = uuid_page or "unknown"
        logger.success(f"Успешный crop {img_format}: {uid}")

        if is_visualitaion:
            save_path = f"data/ocr/crop_page/{img_format}_{uid}.png"
            CropPage._save_image(pil_img, save_path, zoom_factor)

        return img_byte_arr

    @staticmethod
    async def crop_drawning_pdf(
        page: pdfplumber.page.Page,
        uuid_page: str | None = None,
        bbox: Sequence[float] | None = None,
        save_image: bool = False,
        zoom_factor: int = 2,
    ):
        # Вызываем общее ядро
        pil_img, img_byte_arr = CropPage._process_cropped_image(page, bbox, zoom_factor)

        uid = uuid_page or "unknown"
        logger.success(f"Успешный crop drawing: {uid}")

        save_path = f"data/ocr/crop_page/drawing_{uid}.png"
        if save_image:
            CropPage._save_image(pil_img, save_path, zoom_factor=zoom_factor)

        return img_byte_arr, save_path
