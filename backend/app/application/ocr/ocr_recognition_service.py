import gc
import io
import json
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pdfplumber

from fastapi import HTTPException

from backend.app.application.imports.vik_tests_persistence import (
    normalize_import_db_value,
    upsert_vik_entries,
    update_strength_test_duration_rows,
)
from backend.app.config import load_config
from backend.app.infrastructure.db.database import AsyncSessionLocal
from backend.app.infrastructure.repositories.spec_item_repository import SpecItemRepository
from backend.app.ocr.process_data import (
    ProcessCompensators,
    ProcessDrawing,
    ProcessPassport,
    ProcessPassportVIK,
    Pipelines,
)


class OcrRecognitionService:
    def __init__(self, *, session_factory=AsyncSessionLocal):
        self.session_factory = session_factory

    @staticmethod
    def safe_stem(filename: str | None) -> str:
        name = (filename or "").strip()
        stem = Path(name).stem
        return stem or "uploaded_file"

    @staticmethod
    def _normalize_db_value(raw_value: Any) -> str | None:
        return normalize_import_db_value(raw_value)

    @classmethod
    def _extract_material_grade(cls, case_brands: Any) -> str | None:
        if isinstance(case_brands, list):
            return cls._normalize_db_value(case_brands[0]) if case_brands else None
        if isinstance(case_brands, dict):
            values = case_brands.get("values")
            if isinstance(values, list) and values:
                return cls._normalize_db_value(values[0])
        return None

    async def _update_armature_rows(
        self,
        *,
        name_prefix: str,
        gost: str | None,
        material_grade: str | None,
        source: str,
    ) -> dict[str, Any]:
        cleaned_prefix = (name_prefix or "").strip()
        if not cleaned_prefix:
            return {
                "name_prefix": cleaned_prefix,
                "found": 0,
                "updated": 0,
                "status": "skipped_empty_name",
            }

        async with self.session_factory() as session:
            repo = SpecItemRepository(session)
            items = await repo.find_armatures_by_name_prefix(cleaned_prefix)
            if not items:
                return {
                    "name_prefix": cleaned_prefix,
                    "found": 0,
                    "updated": 0,
                    "status": "not_found",
                }

            updated = 0
            normalized_gost = self._normalize_db_value(gost)
            normalized_material = self._normalize_db_value(material_grade)
            for item in items:
                extra = dict(item.extra or {})
                changed = False
                if normalized_gost is not None:
                    extra["gost"] = normalized_gost
                    changed = True
                if normalized_material is not None:
                    extra["material_grade"] = normalized_material
                    changed = True
                if changed:
                    extra["source_ocr_armature"] = source
                    item.extra = extra
                    updated += 1

            await session.flush()
            await session.commit()
            return {
                "name_prefix": cleaned_prefix,
                "found": len(items),
                "updated": updated,
                "status": "updated" if updated else "no_data_to_update",
            }

    @staticmethod
    def _build_db_update_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "found_total": sum(int(row["found"]) for row in rows),
            "updated_total": sum(int(row["updated"]) for row in rows),
            "not_found_total": sum(1 for row in rows if row["status"] == "not_found"),
            "rows": rows,
        }

    @staticmethod
    async def _emit_progress(
        on_progress: Callable[[int, dict[str, Any] | None], Awaitable[None]] | None,
        progress: int,
        extra: dict[str, Any] | None = None,
    ) -> None:
        if on_progress is None:
            return
        await on_progress(progress, extra or {})

    @staticmethod
    def _parsed_texts_dir() -> Path:
        return Path(load_config().ocr.parsed_output_dir)

    @classmethod
    def _save_json_result(cls, filename: str, payload: Any) -> None:
        parsed_texts_dir = cls._parsed_texts_dir()
        parsed_texts_dir.mkdir(parents=True, exist_ok=True)
        with (parsed_texts_dir / f"{filename}.json").open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=4)

    async def recognize_passport_rngs(
        self,
        *,
        file_name: str | None,
        pdf_bytes: bytes,
        pages_limit: int,
        on_progress: Callable[[int, dict[str, Any] | None], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        pages_result: dict[str, dict[str, Any]] = {}
        db_updates: list[dict[str, Any]] = []

        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            total_pages = len(pdf.pages)
            if pages_limit == 0:
                pages_to_process = pdf.pages
                if total_pages % 2 != 0:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "При pages_limit=0 обрабатывается весь файл. "
                            f"В документе {total_pages} страниц (нечетное число). "
                            "Для этого эндпоинта требуется четное число страниц."
                        ),
                    )
            else:
                if pages_limit < 0:
                    raise HTTPException(
                        status_code=400,
                        detail="Количество страниц для обработки не может быть отрицательным.",
                    )
                pages_to_process = pdf.pages[:pages_limit]

            if len(pages_to_process) % 2 != 0:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Для обработки нужно четное число страниц, получено: {len(pages_to_process)}. "
                        "Установите pages_limit как четное число или используйте pages_limit=0 "
                        "для чтения всего файла с четным количеством страниц."
                    ),
                )

            total_pairs = len(pages_to_process) // 2
            await self._emit_progress(
                on_progress,
                5,
                {"stage": "rngs", "processed_pairs": 0, "total_pairs": total_pairs},
            )
            for num_page in range(0, len(pages_to_process), 2):
                first_page = pages_to_process[num_page]
                second_page = pages_to_process[num_page + 1]

                diameter_uuid = str(uuid.uuid4())
                gost_uuid = str(uuid.uuid4())
                case_brands_uuid = str(uuid.uuid4())

                name = await ProcessPassport.process_passport_diameter(
                    first_page, pdf_bytes, num_page, diameter_uuid
                )
                gost = await ProcessPassport.process_passport_text_page(first_page, gost_uuid)
                case_brands = await ProcessPassport.process_passport_table(
                    second_page, pdf_bytes, num_page + 1, case_brands_uuid
                )

                pages_result[name] = {"gost": gost, "case_brands": case_brands}
                db_updates.append(
                    await self._update_armature_rows(
                        name_prefix=name,
                        gost=gost,
                        material_grade=self._extract_material_grade(case_brands),
                        source="ocr_passport_rngs",
                    )
                )
                gc.collect()
                processed_pairs = (num_page // 2) + 1
                progress = min(95, 5 + int((processed_pairs / max(total_pairs, 1)) * 90))
                await self._emit_progress(
                    on_progress,
                    progress,
                    {
                        "stage": "rngs",
                        "processed_pairs": processed_pairs,
                        "total_pairs": total_pairs,
                    },
                )

        await self._emit_progress(on_progress, 100, {"stage": "rngs_done"})
        return {
            "message": "Данные успешно считаны",
            "filename": self.safe_stem(file_name),
            "data": pages_result,
            "db_update": self._build_db_update_summary(db_updates),
        }

    async def recognize_drawing(
        self,
        *,
        file_name: str | None,
        pdf_bytes: bytes,
        pages_limit: int,
        on_progress: Callable[[int, dict[str, Any] | None], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        filename = self.safe_stem(file_name)
        pages_result: dict[str, Any] = {}
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages_to_process = pdf.pages[:pages_limit] if pages_limit > 0 else pdf.pages
            total_pages = len(pages_to_process)
            await self._emit_progress(
                on_progress,
                5,
                {"stage": "drawing", "processed_pages": 0, "total_pages": total_pages},
            )
            for num_page, page in enumerate(pages_to_process):
                page_data = await ProcessDrawing.process_drawing_page(page, pdf_bytes, num_page)
                pages_result.update(page_data)
                gc.collect()
                processed_pages = num_page + 1
                progress = min(95, 5 + int((processed_pages / max(total_pages, 1)) * 90))
                await self._emit_progress(
                    on_progress,
                    progress,
                    {
                        "stage": "drawing",
                        "processed_pages": processed_pages,
                        "total_pages": total_pages,
                    },
                )

        parsed_texts_dir = self._parsed_texts_dir()
        parsed_texts_dir.mkdir(parents=True, exist_ok=True)
        with (parsed_texts_dir / f"{filename}.json").open("w", encoding="utf-8") as f:
            json.dump(pages_result, f, ensure_ascii=False, indent=4)

        await self._emit_progress(on_progress, 100, {"stage": "drawing_done"})
        return {"message": "Данные успешно считаны", "filename": filename}

    async def recognize_passport_compensators(
        self,
        *,
        diameter_file_name: str | None,
        diameter_pdf_bytes: bytes,
        gost_materials_file_name: str | None,
        gost_materials_pdf_bytes: bytes,
        on_progress: Callable[[int, dict[str, Any] | None], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        await self._emit_progress(on_progress, 10, {"stage": "compensators_open"})

        def _pick_target_page(pdf: pdfplumber.pdf.PDF):
            return pdf.pages[1] if len(pdf.pages) > 1 else pdf.pages[0]

        with pdfplumber.open(io.BytesIO(diameter_pdf_bytes)) as diameter_pdf, pdfplumber.open(
            io.BytesIO(gost_materials_pdf_bytes)
        ) as gost_materials_pdf:
            diameter_page = _pick_target_page(diameter_pdf)
            gost_materials_page = _pick_target_page(gost_materials_pdf)

            diameter_uuid = str(uuid.uuid4())
            diameter_text = await ProcessCompensators.process_compensators_diameter_page(
                diameter_page, diameter_uuid
            )
            pages_result_gost_materials = await ProcessCompensators.process_compensators_page(
                gost_materials_page
            )
            await self._emit_progress(
                on_progress,
                70,
                {"stage": "compensators_recognized", "diameter_text": diameter_text},
            )
            dict_result = {diameter_text: pages_result_gost_materials}

            if isinstance(pages_result_gost_materials.get("uuid_page"), list):
                pages_result_gost_materials["uuid_page"] = [
                    diameter_uuid,
                    *pages_result_gost_materials["uuid_page"],
                ]
            gc.collect()

        db_row = await self._update_armature_rows(
            name_prefix=f"Компенсатор {diameter_text}",
            gost=pages_result_gost_materials.get("gost"),
            material_grade=pages_result_gost_materials.get("materials"),
            source="ocr_passport_compensators",
        )
        result_filename = (
            f"{self.safe_stem(diameter_file_name)}__"
            f"{self.safe_stem(gost_materials_file_name)}"
        )
        await self._emit_progress(on_progress, 100, {"stage": "compensators_done"})
        return {
            "message": "Данные успешно считаны",
            "filename": result_filename,
            "data": dict_result,
            "db_update": self._build_db_update_summary([db_row]),
        }

    async def _upsert_vik_entries(
        self,
        rows: list[dict[str, str]],
    ) -> dict[str, Any]:
        return await upsert_vik_entries(
            self.session_factory,
            rows,
            replace_existing_for_pipe_type=True,
        )

    async def _update_strength_test_duration_rows(
        self,
        rows: list[dict[str, str]],
    ) -> dict[str, Any]:
        return await update_strength_test_duration_rows(self.session_factory, rows)

    async def recognize_passport_vik(
        self,
        *,
        file_name: str | None,
        pdf_bytes: bytes,
        pages_limit: int,
        on_progress: Callable[[int, dict[str, Any] | None], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        filename = self.safe_stem(file_name)
        pages_result: list[dict[str, str]] = []
        db_update = {
            "processed_total": 0,
            "pipelines_found": 0,
            "inserted_total": 0,
            "duplicates_total": 0,
            "not_found_total": 0,
        }
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages_to_process = pdf.pages[:pages_limit] if pages_limit > 0 else pdf.pages
            total_pages = len(pages_to_process)
            await self._emit_progress(
                on_progress,
                5,
                {"stage": "vik", "processed_pages": 0, "total_pages": total_pages},
            )
            for num_page, page in enumerate(pages_to_process):
                uuid_page = str(uuid.uuid4())
                statement_text = await ProcessPassportVIK.get_statement_text(
                    page, pdf_bytes, num_page, uuid_page
                )
                if not statement_text:
                    continue

                pipe_num = await ProcessPassportVIK.get_pipe_num(
                    page, pdf_bytes, num_page, uuid_page
                )
                pages_result.append(
                    {
                        "statement_text": statement_text,
                        "pipe_num": pipe_num,
                    }
                )
                gc.collect()
                processed_pages = num_page + 1
                progress = min(95, 5 + int((processed_pages / max(total_pages, 1)) * 80))
                await self._emit_progress(
                    on_progress,
                    progress,
                    {
                        "stage": "vik",
                        "processed_pages": processed_pages,
                        "total_pages": total_pages,
                    },
                )

        if pages_result:
            db_update_result = await self._upsert_vik_entries(pages_result)
            for key in db_update:
                db_update[key] = int(db_update_result.get(key, db_update[key]))

        self._save_json_result(filename, {"rows": pages_result, "db_update": db_update})
        await self._emit_progress(on_progress, 100, {"stage": "vik_done"})
        return {
            "message": "Данные успешно считаны",
            "filename": filename,
            "data": pages_result,
            "db_update": db_update,
        }

    async def recognize_pipelines_tests(
        self,
        *,
        file_name: str | None,
        pdf_bytes: bytes,
        pages_limit: int,
        on_progress: Callable[[int, dict[str, Any] | None], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        filename = self.safe_stem(file_name)
        pages_result: list[dict[str, str]] = []
        db_update = {
            "processed_total": 0,
            "pipelines_found": 0,
            "updated_total": 0,
            "not_found_total": 0,
        }
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages_to_process = pdf.pages[:pages_limit] if pages_limit > 0 else pdf.pages
            total_pages = len(pages_to_process)
            await self._emit_progress(
                on_progress,
                5,
                {"stage": "pipelines_tests", "processed_pages": 0, "total_pages": total_pages},
            )
            for num_page, page in enumerate(pages_to_process):
                uuid_page = str(uuid.uuid4())
                pipeline_text = await Pipelines.get_pipeline_text(page, num_page, uuid_page)
                test_time = await Pipelines.get_test_time_duration(page, num_page, uuid_page)
                if not pipeline_text or not test_time:
                    continue
                pages_result.append(
                    {
                        "pipeline": pipeline_text,
                        "test_time": test_time,
                    }
                )
                gc.collect()
                processed_pages = num_page + 1
                progress = min(95, 5 + int((processed_pages / max(total_pages, 1)) * 80))
                await self._emit_progress(
                    on_progress,
                    progress,
                    {
                        "stage": "pipelines_tests",
                        "processed_pages": processed_pages,
                        "total_pages": total_pages,
                    },
                )

        if pages_result:
            db_update_result = await self._update_strength_test_duration_rows(pages_result)
            for key in db_update:
                db_update[key] = int(db_update_result.get(key, db_update[key]))

        self._save_json_result(filename, {"rows": pages_result, "db_update": db_update})
        await self._emit_progress(on_progress, 100, {"stage": "pipelines_tests_done"})
        return {
            "message": "Данные успешно считаны",
            "filename": filename,
            "data": pages_result,
            "db_update": db_update,
        }
