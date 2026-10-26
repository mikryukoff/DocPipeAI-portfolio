"""Детекция таблиц/заголовков на PDF (YOLO). Требует optional-зависимости [ocr]."""

from pathlib import Path

from loguru import logger


class ExtractionTable:
    def __init__(self, is_visualitation: bool = False, poppler_path: str | None = None):
        from huggingface_hub import hf_hub_download
        from ultralytics import YOLO

        logger.info("Загрузка весов YOLOv8 (Table Detection)...")
        model_path = hf_hub_download(
            repo_id="foduucom/table-detection-and-extraction", filename="best.pt"
        )
        self.model = YOLO(model_path)
        self.is_visualitation = is_visualitation
        self.poppler_path = poppler_path

    def extract_bboxes(self, pdf_bytes: bytes, page_number: int = 0, conf=0.3) -> list:
        """
        Принимает байты PDF-файла, ищет таблицы на указанной странице и возвращает их координаты.
        """
        from pdf2image import convert_from_bytes
        import cv2

        try:
            logger.info(f"Конвертация страницы {page_number + 1} в изображение...")
            convert_kwargs = {
                "first_page": page_number + 1,
                "last_page": page_number + 1,
            }
            if self.poppler_path:
                convert_kwargs["poppler_path"] = self.poppler_path
            pages = convert_from_bytes(pdf_bytes, **convert_kwargs)

            if not pages:
                logger.error("Не удалось конвертировать страницу.")
                return []

            img = pages[0].convert("RGB")

            # Запускаем поиск таблиц
            results = self.model(img, conf=conf)
            result = results[0]

            # Достаем координаты
            found_bboxes = []
            logger.info(f"Найдено таблиц: {len(result.boxes)}")

            for box in result.boxes:
                coords = [round(i, 2) for i in box.xyxy[0].tolist()]
                # confidence = box.conf[0].item() * 100

                found_bboxes.append(coords)
            logger.success(
                f"Таблицы спарсились."
            )

            if self.is_visualitation:
                plotted_img_array = result.plot()
                output_dir = Path("data/ocr/crop_page")
                output_dir.mkdir(parents=True, exist_ok=True)
                output_image = output_dir / f"yolo_debug_page_{page_number + 1}.jpg"
                cv2.imwrite(str(output_image), plotted_img_array)
                logger.success(f"Визуализация сохранена в {output_image}")

            # Возвращаем список координат найденных таблиц
            return found_bboxes

        except Exception as e:
            logger.error(f"Ошибка YOLO: {e}")
            return []


class ExtractionText:
    def __init__(self, is_visualitation=False):
        from huggingface_hub import hf_hub_download
        from ultralytics import YOLO

        logger.info("Загрузка весов YOLOv8 (Document Layout Analysis)...")
        model_path = hf_hub_download(
            repo_id="DILHTWD/documentlayoutsegmentation_YOLOv8_ondoclaynet",
            filename="yolov8x-doclaynet-epoch64-imgsz640-initiallr1e-4-finallr1e-5.pt"
        )
        self.model = YOLO(model_path)
        self.is_visualitation = is_visualitation

        # Оставляем ТОЛЬКО заголовки секций
        self.target_classes = ["Section-header"]

    def extract_bboxes(self, pdf_bytes: bytes, page_number: int = 0, conf=0.3) -> list:
        import numpy as np
        from pdf2image import convert_from_bytes
        import cv2

        try:
            logger.info(f"Конвертация страницы {page_number + 1} в изображение...")
            pages = convert_from_bytes(
                pdf_bytes,
                first_page=page_number + 1,
                last_page=page_number + 1,
            )

            if not pages:
                logger.error("Не удалось конвертировать страницу.")
                return []

            img_pil = pages[0].convert("RGB")

            # Запускаем поиск структуры документа
            results = self.model(img_pil, conf=conf)
            result = results[0]

            found_bboxes = []
            names = self.model.names

            # Фильтруем результаты
            for box in result.boxes:
                class_id = int(box.cls[0].item())
                class_name = names[class_id]

                if class_name in self.target_classes:
                    coords = [round(i, 2) for i in box.xyxy[0].tolist()]
                    found_bboxes.append(coords)

            # Сортируем блоки сверху вниз
            found_bboxes = sorted(found_bboxes, key=lambda box: box[1])

            logger.success(f"Найдено Section-header: {len(found_bboxes)}")

            # Ручная визуализация ТОЛЬКО нужных классов
            if self.is_visualitation:
                # Конвертируем картинку из PIL в формат OpenCV (BGR)
                img_cv = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)

                # Рисуем каждую найденную рамку
                for box in found_bboxes:
                    x1, y1, x2, y2 = map(int, box)  # Координаты должны быть целыми числами для отрисовки

                    # Рисуем прямоугольник (зеленый цвет, толщина линии 2)
                    cv2.rectangle(img_cv, (x1, y1), (x2, y2), (0, 255, 0), 2)

                    # Пишем название класса над рамкой
                    cv2.putText(img_cv, "Section-header", (x1, y1 - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

                output_image = f"crop_page/yolo_headers_only_page_{page_number + 1}.jpg"
                cv2.imwrite(output_image, img_cv)
                logger.success(f"Визуализация сохранена в {output_image}")

            return found_bboxes

        except Exception as e:
            logger.error(f"Ошибка YOLO при поиске текста: {e}")
            return []
