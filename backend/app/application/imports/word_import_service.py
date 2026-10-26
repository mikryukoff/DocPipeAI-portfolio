"""Импорт данных из Word (.docx): ВИК и протоколы испытаний — отдельно от OCR/PDF."""

from __future__ import annotations

import io
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from docx import Document

from backend.app.application.imports.vik_tests_persistence import (
    upsert_vik_entries,
    update_strength_test_duration_rows,
)
from backend.app.infrastructure.db.database import AsyncSessionLocal
from backend.app.infrastructure.files.docx.docx_logical_pages import iter_logical_pages
from backend.app.infrastructure.files.docx.pipelines_tests_docx_extractor import (
    extract_pipelines_tests_from_logical_page,
)
from backend.app.infrastructure.files.docx.vik_docx_extractor import extract_vik_from_logical_page
from backend.app.shared.parsing_audit_logger import log_parsing_event


class WordDocumentImportService:
    def __init__(self, *, session_factory=AsyncSessionLocal):
        self.session_factory = session_factory

    @staticmethod
    def safe_stem(filename: str | None) -> str:
        name = (filename or "").strip()
        stem = Path(name).stem
        return stem or "uploaded_file"

    @staticmethod
    async def _emit_progress(
        on_progress: Callable[[int, dict[str, Any] | None], Awaitable[None]] | None,
        progress: int,
        extra: dict[str, Any] | None = None,
    ) -> None:
        if on_progress is None:
            return
        await on_progress(progress, extra or {})

    async def import_passport_vik(
        self,
        *,
        file_name: str | None,
        docx_bytes: bytes,
        pages_limit: int,
        job_id: int | None = None,
        user_log_key: str | None = None,
        on_progress: Callable[[int, dict[str, Any] | None], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        filename = self.safe_stem(file_name)
        doc = Document(io.BytesIO(docx_bytes))
        logical_pages = iter_logical_pages(doc)
        if pages_limit > 0:
            logical_pages = logical_pages[:pages_limit]
        pages_result: list[dict[str, str]] = []
        db_update = {
            "processed_total": 0,
            "pipelines_found": 0,
            "inserted_total": 0,
            "duplicates_total": 0,
            "not_found_total": 0,
        }
        total_pages = len(logical_pages) if logical_pages else 1
        await self._emit_progress(
            on_progress,
            5,
            {"stage": "word_vik", "processed_pages": 0, "total_pages": total_pages},
        )
        for num_page, page in enumerate(logical_pages):
            row = extract_vik_from_logical_page(page)
            if not row:
                log_parsing_event(
                    job_id=job_id,
                    user_log_key=user_log_key,
                    source_type="word",
                    source_file=file_name or filename,
                    parser="WordDocumentImportService",
                    entity="vik",
                    entity_id=None,
                    field="page_skip",
                    value=f"page_{num_page + 1}",
                    origin={"page_index": num_page + 1},
                    status="warning",
                    note="vik_data_not_found_on_page",
                )
                processed_pages = num_page + 1
                progress = min(95, 5 + int((processed_pages / max(total_pages, 1)) * 80))
                await self._emit_progress(
                    on_progress,
                    progress,
                    {
                        "stage": "word_vik",
                        "processed_pages": processed_pages,
                        "total_pages": total_pages,
                    },
                )
                continue
            pages_result.append(
                {
                    "statement_text": row["statement_text"],
                    "pipe_num": row["pipe_num"],
                    "type": "ВИК",
                }
            )
            log_parsing_event(
                job_id=job_id,
                user_log_key=user_log_key,
                source_type="word",
                source_file=file_name or filename,
                parser="WordDocumentImportService",
                entity="vik",
                entity_id=row["pipe_num"],
                field="statement_text",
                value=row["statement_text"],
                origin={"page_index": num_page + 1},
            )
            processed_pages = num_page + 1
            progress = min(95, 5 + int((processed_pages / max(total_pages, 1)) * 80))
            await self._emit_progress(
                on_progress,
                progress,
                {
                    "stage": "word_vik",
                    "processed_pages": processed_pages,
                    "total_pages": total_pages,
                },
            )

        if pages_result:
            db_update_result = await upsert_vik_entries(
                self.session_factory,
                pages_result,
                replace_existing_for_pipe_type=True,
            )
            for key in db_update:
                db_update[key] = int(db_update_result.get(key, db_update[key]))

        log_parsing_event(
            job_id=job_id,
            user_log_key=user_log_key,
            source_type="word",
            source_file=file_name or filename,
            parser="WordDocumentImportService",
            entity="vik",
            entity_id=None,
            field="db_update",
            value=str(db_update),
            origin={"pages_total": total_pages, "rows_total": len(pages_result)},
        )
        await self._emit_progress(on_progress, 100, {"stage": "word_vik_done"})
        return {
            "message": "Данные успешно считаны",
            "filename": filename,
            "data": pages_result,
            "db_update": db_update,
        }

    async def import_pipelines_tests(
        self,
        *,
        file_name: str | None,
        docx_bytes: bytes,
        pages_limit: int,
        job_id: int | None = None,
        user_log_key: str | None = None,
        on_progress: Callable[[int, dict[str, Any] | None], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        filename = self.safe_stem(file_name)
        doc = Document(io.BytesIO(docx_bytes))
        logical_pages = iter_logical_pages(doc)
        if pages_limit > 0:
            logical_pages = logical_pages[:pages_limit]
        pages_result: list[dict[str, str]] = []
        db_update = {
            "processed_total": 0,
            "pipelines_found": 0,
            "updated_total": 0,
            "not_found_total": 0,
        }
        total_pages = len(logical_pages) if logical_pages else 1
        await self._emit_progress(
            on_progress,
            5,
            {
                "stage": "word_pipelines_tests",
                "processed_pages": 0,
                "total_pages": total_pages,
            },
        )
        for num_page, page in enumerate(logical_pages):
            row = extract_pipelines_tests_from_logical_page(page)
            if not row:
                log_parsing_event(
                    job_id=job_id,
                    user_log_key=user_log_key,
                    source_type="word",
                    source_file=file_name or filename,
                    parser="WordDocumentImportService",
                    entity="pipelines_tests",
                    entity_id=None,
                    field="page_skip",
                    value=f"page_{num_page + 1}",
                    origin={"page_index": num_page + 1},
                    status="warning",
                    note="tests_data_not_found_on_page",
                )
                processed_pages = num_page + 1
                progress = min(95, 5 + int((processed_pages / max(total_pages, 1)) * 80))
                await self._emit_progress(
                    on_progress,
                    progress,
                    {
                        "stage": "word_pipelines_tests",
                        "processed_pages": processed_pages,
                        "total_pages": total_pages,
                    },
                )
                continue
            pages_result.append(
                {
                    "pipeline": row["pipeline"],
                    "test_time": row["test_time"],
                }
            )
            log_parsing_event(
                job_id=job_id,
                user_log_key=user_log_key,
                source_type="word",
                source_file=file_name or filename,
                parser="WordDocumentImportService",
                entity="pipeline_parameters",
                entity_id=row["pipeline"],
                field="strength_test_duration",
                value=row["test_time"],
                origin={"page_index": num_page + 1},
            )
            processed_pages = num_page + 1
            progress = min(95, 5 + int((processed_pages / max(total_pages, 1)) * 80))
            await self._emit_progress(
                on_progress,
                progress,
                {
                    "stage": "word_pipelines_tests",
                    "processed_pages": processed_pages,
                    "total_pages": total_pages,
                },
            )

        if pages_result:
            db_update_result = await update_strength_test_duration_rows(
                self.session_factory, pages_result
            )
            for key in db_update:
                db_update[key] = int(db_update_result.get(key, db_update[key]))

        log_parsing_event(
            job_id=job_id,
            user_log_key=user_log_key,
            source_type="word",
            source_file=file_name or filename,
            parser="WordDocumentImportService",
            entity="pipelines_tests",
            entity_id=None,
            field="db_update",
            value=str(db_update),
            origin={"pages_total": total_pages, "rows_total": len(pages_result)},
        )
        await self._emit_progress(on_progress, 100, {"stage": "word_pipelines_tests_done"})
        return {
            "message": "Данные успешно считаны",
            "filename": filename,
            "data": pages_result,
            "db_update": db_update,
        }
