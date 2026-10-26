import uuid
import re
import json
import os
import asyncio
from enum import Enum
from typing import AsyncIterator, Iterable
from loguru import logger

import pdfplumber

from backend.app.ocr.crop import CropPage
from backend.app.ocr.ocr_service import process_text
from backend.app.ocr.parse import parse_table_texts, parse_diameter
from backend.app.config.config import load_config

config = load_config()
is_test = config.ocr.mode == "TEST"

_extraction_table_instance = None
_extraction_text_instance = None
_EXTRACT_BBOXES_TO_THREAD = os.getenv("OCR_EXTRACT_BBOXES_TO_THREAD", "0").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
_raw_bbox_concurrency = os.getenv("OCR_EXTRACT_BBOXES_MAX_CONCURRENCY", "1").strip()
try:
    _EXTRACT_BBOXES_MAX_CONCURRENCY = max(int(_raw_bbox_concurrency), 1)
except ValueError:
    _EXTRACT_BBOXES_MAX_CONCURRENCY = 1
_EXTRACT_BBOXES_SEMAPHORE = asyncio.Semaphore(_EXTRACT_BBOXES_MAX_CONCURRENCY)


async def _extract_bboxes_guarded(extractor, pdf_bytes: bytes, *, page_number: int, conf: float | None = None):
    kwargs = {"page_number": page_number}
    if conf is not None:
        kwargs["conf"] = conf
    if not _EXTRACT_BBOXES_TO_THREAD:
        return extractor.extract_bboxes(pdf_bytes, **kwargs)
    async with _EXTRACT_BBOXES_SEMAPHORE:
        return await asyncio.to_thread(extractor.extract_bboxes, pdf_bytes, **kwargs)


def get_extraction_table():
    """Ленивая инициализация: загрузит модель только при первом обращении"""
    global _extraction_table_instance
    if _extraction_table_instance is None:
        from backend.app.ocr.table_detection import ExtractionTable

        _extraction_table_instance = ExtractionTable(is_visualitation=is_test)
    return _extraction_table_instance


def get_extraction_text():
    global _extraction_text_instance
    if _extraction_text_instance is None:
        from backend.app.ocr.table_detection import ExtractionText

        _extraction_text_instance = ExtractionText(is_visualitation=is_test)
    return _extraction_text_instance


class BBOXCoordsPassports(Enum):
    TEXT = [(19, 225, 404, 328), (11, 189, 385, 251)]


class BBOXCoordsCompensators(Enum):
    TEXT_1 = [(9, 47, 333, 173), (8, 77, 354, 208)]
    TEXT_2 = [(4, 347, 431, 513)]
    DIAMETER = [
        (448, 139, 802, 170),
        (421, 90, 767, 138),
        (426, 91, 763, 138),
        (452, 124, 784, 150),
    ]


class BBOXCoordsPipesTests(Enum):
    LINE_TEXT = (203, 380, 500, 428) #(223, 379, 483, 422)
    TEST_TIME_DURATION = (299, 482, 378, 526) # (304, 493, 370, 525)


class ProcessPassport:
    @staticmethod
    def _calculate_adjusted_bbox_diameter(
        bbox: list, page_width: float, page_height: float
    ) -> list:
        """Вычисляет новые координаты рамки с учетом отступов и масштаба."""
        x1, y1, x2, y2 = bbox
        scale = 72 / 200

        return [
            max(0.0, (x1 - 8) * scale),
            max(0.0, (y1 - 8) * scale),
            min(float(page_width), x2 * scale),
            min(float(page_height), (y1 + 100) * scale),
        ]

    @staticmethod
    def _calculate_adjusted_bbox_table(
        bbox: list, page_width: float, page_height: float
    ) -> list:
        """Вычисляет новые координаты рамки с учетом отступов и масштаба."""
        x1, y1, x2, y2 = bbox
        scale = 72 / 200

        width = x2 - x1
        margin = 20

        # Определяем модификатор X в зависимости от ширины таблицы
        mod_x = -250 if width < 800 else -380

        return [
            max(0.0, (x1 + 240) * scale),
            max(0.0, (y1 + 40) * scale),
            min(float(page_width), (x2 + mod_x) * scale),
            min(float(page_height), (y2 + margin) * scale),
        ]

    @staticmethod
    async def process_passport_text_page(
        page: pdfplumber.page.Page, uuid_page: str
    ) -> str:
        """Обработка четных страниц (Поиск ТУ регулярными выражениями)."""
        for bbox in BBOXCoordsPassports.TEXT.value:
            zoomed_img_bytes = await CropPage.crop_passport_pdf(
                page,
                table=False,
                is_visualitaion=is_test,
                uuid_page=uuid_page,
                bbox=bbox,
                zoom_factor=2,
            )
            text = await process_text(zoomed_img_bytes)
            match = re.search(r"ТУ\s*\d+(?:-\d+)+", text or "")

            if match:
                return match.group(0)

            logger.warning(
                "Неудачное распознавание текста. Пробую распознать другую область."
            )

        logger.error(f"Неудачное распознавание текста: {uuid_page}")
        return "[НЕОПОЗНАННЫЙ ТЕКСТ]"

    @staticmethod
    async def process_passport_diameter(
        page: pdfplumber.page.Page, pdf_bytes: bytes, num_page: int, uuid_page: str
    ) -> dict:
        """Обработка первой страницы паспорта (Поиск и извлечение таблицы YOLO)."""
        bboxes = await _extract_bboxes_guarded(
            get_extraction_table(), pdf_bytes, page_number=num_page, conf=0.6
        )

        if not bboxes:
            logger.error(f"Диаметр не найден на странице {num_page + 1}: {uuid_page}")
            return "[НЕОПОЗНАННЫЙ ДИАМЕТР]"

        sorted_bboxes = sorted(bboxes, key=lambda box: (box[1], -box[0]))
        pdf_bbox = ProcessPassport._calculate_adjusted_bbox_diameter(
            sorted_bboxes[0], page.width, page.height
        )

        zoomed_img_bytes = await CropPage.crop_passport_pdf(
            page,
            table=True,
            is_visualitaion=is_test,
            uuid_page=uuid_page,
            bbox=pdf_bbox,
            zoom_factor=2,
        )
        text = await process_text(zoomed_img_bytes)
        diameter = await parse_diameter(text)
        if diameter:
            return diameter

        logger.error(
            f"Неудачное распознавание диаметра на первой странице: {uuid_page}"
        )
        # return "[НЕОПОЗНАННЫЙ ДИАМЕТР]"
        return text

    @staticmethod
    async def process_passport_table(
        page: pdfplumber.page.Page, pdf_bytes: bytes, num_page: int, uuid_page: str
    ) -> dict:
        """Обработка второй страницы паспорта (Поиск и извлечение таблицы YOLO)."""
        bboxes = await _extract_bboxes_guarded(
            get_extraction_table(), pdf_bytes, page_number=num_page, conf=0.8
        )

        # ЗАЩИТА: Если YOLO ничего не нашел, возвращаем пустой результат, чтобы код не упал с IndexError
        if not bboxes:
            logger.error(f"Таблицы не найдены на странице {num_page + 1}")
            if is_test:
                return {"values": [], "uuid": uuid_page, "text": ""}
            return values if values else []

        sorted_bboxes = sorted(bboxes, key=lambda box: (box[1], -box[0]))
        pdf_bbox = ProcessPassport._calculate_adjusted_bbox_table(
            sorted_bboxes[0], page.width, page.height
        )

        zoomed_img_bytes = await CropPage.crop_passport_pdf(
            page,
            table=True,
            is_visualitaion=is_test,
            uuid_page=uuid_page,
            bbox=pdf_bbox,
            zoom_factor=2,
        )
        table_html = await process_text(zoomed_img_bytes)
        values = await parse_table_texts(table_html)

        if is_test:
            return {
                "values": values if values else [],
                "text_table": table_html,
            }
        return values if values else []


class ProcessDrawing:
    @staticmethod
    def _calculate_drawing_bbox(
        bbox: list, page_width: float, page_height: float, is_odd: bool
    ) -> list:
        """Вычисляет новые координаты рамки для чертежей."""
        x1, y1, x2, y2 = bbox
        scale = 72 / 200
        margin = 20

        # Тернарные операторы для расчета смещений
        mod_y = (110 - margin) if not is_odd else -margin
        mod_x = (x1 + 205 - x2) if not is_odd else margin

        return [
            max(0.0, (x1 - margin) * scale),
            max(0.0, (y1 + mod_y) * scale),
            min(float(page_width), (x2 + mod_x) * scale),
            min(float(page_height), (y2 + margin) * scale),
        ]

    @staticmethod
    async def process_drawing_page(
        page: pdfplumber.page.Page, pdf_bytes: bytes, num_page: int
    ) -> dict:
        """Обрабатывает одну страницу чертежа и возвращает словарь {values: save_path}."""
        bboxes = await _extract_bboxes_guarded(
            get_extraction_table(), pdf_bytes, page_number=num_page
        )
        sorted_bboxes = sorted(bboxes, key=lambda box: box[1])[:2][::-1]

        current_values = []
        odd_save_path = None
        dict_values = {}

        uuid_pages = []

        for i, bbox in enumerate(sorted_bboxes, 1):
            is_odd = i % 2 != 0

            pdf_bbox = ProcessDrawing._calculate_drawing_bbox(
                bbox, page.width, page.height, is_odd
            )
            uuid_page = str(uuid.uuid4())
            uuid_pages.append(uuid_page)

            zoomed_img_bytes, save_path = await CropPage.crop_drawning_pdf(
                page,
                uuid_page=uuid_page,
                bbox=pdf_bbox,
                save_image=is_test or is_odd,
                zoom_factor=1 if is_odd else 2,
            )

            if is_odd:
                # Нечетная таблица - просто запоминаем путь сохранения картинки
                odd_save_path = save_path
            else:
                # Четная таблица - извлекаем текст и сохраняем values
                table_html = await process_text(zoomed_img_bytes)
                extracted = await parse_table_texts(table_html)
                current_values = extracted if extracted else []

                base_meta = {"path": odd_save_path}
                if is_test:
                    base_meta.update({"text": table_html, "uuid_pages": uuid_pages})

                if not current_values:
                    dict_values.update({"None": current_values, **base_meta})
                    continue

                for value in current_values:
                    aliases = [v for v in current_values if v != value]
                    dict_values.update({value: {"alias": aliases, **base_meta}})

        return dict_values


class ProcessCompensators:
    @staticmethod
    async def _iter_compensator_texts(
        page: pdfplumber.page.Page, uuid_page: str, bboxes: Iterable[tuple]
    ) -> AsyncIterator[str]:
        """Итерирует OCR-тексты по всем bbox и масштабам в фиксированном порядке."""
        for bbox in bboxes:
            for zoom_factor in (1, 2):
                zoomed_img_bytes = await CropPage.crop_passport_pdf(
                    page,
                    table=False,
                    is_visualitaion=is_test,
                    uuid_page=uuid_page,
                    bbox=bbox,
                    zoom_factor=zoom_factor,
                )
                text = await process_text(zoomed_img_bytes)
                yield (text or "").strip()

    @staticmethod
    async def _process_compensators_diameter(
        page: pdfplumber.page.Page, uuid_page: str
    ) -> str:
        async for text in ProcessCompensators._iter_compensator_texts(
            page, uuid_page, BBOXCoordsCompensators.DIAMETER.value
        ):
            match = re.search(r"DN\D*(\d+)", text)
            diameter = f"DN{match.group(1)}" if match else None
            if diameter:
                return diameter

            logger.warning(
                "Неудачное распознавание текста в паспорте компенсаторов. Пробую распознать другую область."
            )
        logger.error(
            f"Неудачное распознавание текста в паспорте компенсаторов: {uuid_page}"
        )
        return "[НЕОПОЗНАННЫЙ ДИАМЕТР]"

    @staticmethod
    async def _process_compensators_gost(
        page: pdfplumber.page.Page, uuid_page: str
    ) -> tuple[str, str]:
        """Обработка текста в паспорте компенсаторов (Поиск ТУ регулярными выражениями)."""
        last_text = ""
        
        async for text in ProcessCompensators._iter_compensator_texts(
            page, uuid_page, BBOXCoordsCompensators.TEXT_1.value
        ):
            last_text = text
            match = re.search(
                r"[Тт][Уу]\s*\d{2}\.\d{2}\.\d{2}-\d{3}-\d{8}-\d{4}",
                text or "",
            )

            if match:
                return match.group(0).upper().strip(), text

            logger.warning(
                "Неудачное распознавание текста в паспорте компенсаторов. Пробую распознать другую область."
            )

        logger.error(
            f"Неудачное распознавание текста в паспорте компенсаторов: {uuid_page}"
        )
        return "[НЕОПОЗНАННЫЙ ТЕКСТ]", last_text

    @staticmethod
    async def _process_compensators_materials(
        page: pdfplumber.page.Page, uuid_page: str
    ) -> str:
        async for text in ProcessCompensators._iter_compensator_texts(
            page, uuid_page, BBOXCoordsCompensators.TEXT_2.value
        ):
            if text:
                return re.sub(r"МАТЕРИАЛ[Ыы]", "", text).strip()

            logger.warning(
                "Неудачное распознавание информации о материалах в паспорте компенсаторов. "
                "Пробую распознать другую область."
            )

        return "[НЕОПОЗНАННЫЕ МАТЕРИАЛЫ]"

    @staticmethod
    async def process_compensators_diameter_page(
        page: pdfplumber.page.Page, uuid_page: str
    ) -> str:
        text = await ProcessCompensators._process_compensators_diameter(page, uuid_page)
        return text.strip()

    @staticmethod
    async def process_compensators_page(page: pdfplumber.page.Page) -> dict:
        """Обработка страниц паспорта компенсаторов (Поиск ТУ регулярными выражениями)."""

        uuid_pages = [str(uuid.uuid4()) for _ in range(2)]
        gost_text, gost_raw_text = await ProcessCompensators._process_compensators_gost(
            page, uuid_pages[0]
        )
        materials_text = await ProcessCompensators._process_compensators_materials(
            page, uuid_pages[1]
        )

        result = {"gost": gost_text, "materials": materials_text}
        if is_test:
            result.update({"uuid_page": uuid_pages, "text_gost": gost_raw_text})
        return result


class ProcessPassportVIK:
    _BBOX_CONFIGS = {
        "pipe_num": {
            "left": (0, 300),
            "top": (1, 323),
            "right": (0, 803),
            "bottom": (1, 430),
        },
        "statement": {
            "left": (0, -10),
            "top": (1, -10),
            "right": (2, 10),
            "bottom": (3, 10),
        },
    }

    @staticmethod
    def _calculate_adjusted_bbox_by_config(
        bbox: list, page_width: float, page_height: float, config_name: str
    ) -> list:
        """Вычисляет новые координаты рамки на основе конфигурации смещений."""
        scale = 72 / 200
        x1, y1, x2, y2 = bbox
        coords = [x1, y1, x2, y2]
        config = ProcessPassportVIK._BBOX_CONFIGS[config_name]

        left_idx, left_offset = config["left"]
        top_idx, top_offset = config["top"]
        right_idx, right_offset = config["right"]
        bottom_idx, bottom_offset = config["bottom"]

        return [
            max(0.0, (coords[left_idx] + left_offset) * scale),
            max(0.0, (coords[top_idx] + top_offset) * scale),
            min(float(page_width), (coords[right_idx] + right_offset) * scale),
            min(float(page_height), (coords[bottom_idx] + bottom_offset) * scale),
        ]

    @staticmethod
    def _calculate_adjusted_bbox_pipe_num(
        bbox: list, page_width: float, page_height: float
    ) -> list:
        return ProcessPassportVIK._calculate_adjusted_bbox_by_config(
            bbox, page_width, page_height, "pipe_num"
        )

    @staticmethod
    def _calculate_adjusted_bbox_statement(
        bbox: list, page_width: float, page_height: float
    ) -> list:
        return ProcessPassportVIK._calculate_adjusted_bbox_by_config(
            bbox, page_width, page_height, "statement"
        )

    @staticmethod
    async def _get_primary_bbox(
        pdf_bytes: bytes,
        num_page: int,
        conf: float,
        error_message: str,
        extractor,
        sort_key,
        bbox_filter=None,
    ):
        bboxes = await _extract_bboxes_guarded(
            extractor(), pdf_bytes, page_number=num_page, conf=conf
        )
        if not bboxes:
            logger.error(error_message)
            return None

        if bbox_filter is not None:
            bboxes = list(filter(bbox_filter, bboxes))
            if not bboxes:
                logger.error(error_message)
                return None

        return sorted(bboxes, key=sort_key)[0]

    @staticmethod
    async def _extract_text_by_bbox(
        page: pdfplumber.page.Page,
        uuid_page: str,
        bbox: list,
        bbox_adjuster,
        table: bool,
    ) -> str:
        pdf_bbox = bbox_adjuster(bbox, page.width, page.height)
        zoomed_img_bytes = await CropPage.crop_passport_pdf(
            page,
            table=table,
            is_visualitaion=is_test,
            uuid_page=uuid_page,
            bbox=pdf_bbox,
            zoom_factor=1,
        )
        return await process_text(zoomed_img_bytes)

    @staticmethod
    async def get_pipe_num(
        page: pdfplumber.page.Page, pdf_bytes: bytes, num_page: int, uuid_page: str
    ) -> str:
        fallback = "[НЕОПОЗНАН ТЕКСТ НОМЕРА ТРУБОПРОВОДА]"
        error_message = f"Таблицы не найдены на странице {num_page + 1}: {uuid_page}"
        primary_bbox = await ProcessPassportVIK._get_primary_bbox(
            pdf_bytes=pdf_bytes,
            num_page=num_page,
            conf=0.55,
            error_message=error_message,
            extractor=get_extraction_table,
            sort_key=lambda bbox: bbox[1],
        )
        if primary_bbox is None:
            return fallback

        table_html = await ProcessPassportVIK._extract_text_by_bbox(
            page=page,
            uuid_page=uuid_page,
            bbox=primary_bbox,
            bbox_adjuster=ProcessPassportVIK._calculate_adjusted_bbox_pipe_num,
            table=True,
        )
        values = await parse_table_texts(table_html)

        if is_test:
            return {
                "value": values,
                "text_table": table_html,
                "uuid_page": uuid_page,
            }

        if len(values) > 2:
            return "".join(values[1:])
        elif len(values) == 2:
            if len(values[1]) <= 12:
                return "".join(values)
            return values[1]
        return values[0] if values else fallback

    @staticmethod
    async def get_statement_text(
        page: pdfplumber.page.Page, pdf_bytes: bytes, num_page: int, uuid_page: str
    ) -> str:
        error_message = f"Заявление не найдено на странице {num_page + 1}: {uuid_page}"
        primary_bbox = await ProcessPassportVIK._get_primary_bbox(
            pdf_bytes=pdf_bytes,
            num_page=num_page,
            conf=0.35,
            error_message=error_message,
            extractor=get_extraction_text,
            sort_key=lambda box: (box[1], -box[0]),
            bbox_filter=lambda box: box[1] > 200,
        )
        if primary_bbox is None:
            return None

        text = await ProcessPassportVIK._extract_text_by_bbox(
            page=page,
            uuid_page=uuid_page,
            bbox=primary_bbox,
            bbox_adjuster=ProcessPassportVIK._calculate_adjusted_bbox_statement,
            table=False,
        )
        match = re.search(r"\d+-\d{2}\.\d{2}\.\d{2}", text)

        if not text or not match:
            logger.warning(
                f"Неудачное распознавание текста на странице {num_page + 1}: {uuid_page}"
            )
            return None

        return match.group(0)

class Pipelines:
    @staticmethod
    async def _extract_value_by_bbox(
        page: pdfplumber.page.Page,
        num_page: int,
        uuid_page: str,
        bbox: tuple[int, int, int, int],
        pattern: str,
    ):
        zoomed_img_bytes = await CropPage.crop_passport_pdf(
            page,
            table=False,
            is_visualitaion=is_test,
            uuid_page=uuid_page,
            bbox=bbox,
            zoom_factor=1,
        )
        text = await process_text(zoomed_img_bytes)

        if not text:
            logger.warning(
                f"Неудачное распознавание текста на странице {num_page + 1}: {uuid_page}"
            )
            return None

        match = re.search(pattern, text)
        value = match.group(0) if match else None

        if is_test:
            return {"value": value, "text": text, "uuid_page": uuid_page}

        if not value:
            logger.error(
                f"Текст распознан, но нет значений на странице {num_page + 1}: {uuid_page}"
            )
            return None
        return value

    @staticmethod
    async def get_pipeline_text(
        page: pdfplumber.page.Page, num_page: int, uuid_page: str
    ) -> str:
        """Обработка четных страниц (Поиск ТУ регулярными выражениями)."""
        return await Pipelines._extract_value_by_bbox(
            page,
            num_page=num_page,
            uuid_page=uuid_page,
            bbox=BBOXCoordsPipesTests.LINE_TEXT.value,
            pattern=(
                r"\b[A-Za-z][A-Za-z0-9]*(?:\.[A-Za-z0-9]+)*"
                r"(?:-[A-Za-z0-9]+(?:\.[A-Za-z0-9]+)*)+"
            ),
        )

    @staticmethod
    async def get_test_time_duration(
        page: pdfplumber.page.Page, num_page: int, uuid_page: str
    ) -> str:
        """Обработка четных страниц (Поиск ТУ регулярными выражениями)."""
        return await Pipelines._extract_value_by_bbox(
            page,
            num_page=num_page,
            uuid_page=uuid_page,
            bbox=BBOXCoordsPipesTests.TEST_TIME_DURATION.value,
            pattern=r"\d+",
        )