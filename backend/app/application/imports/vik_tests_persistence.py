"""Общая запись в БД для записей ВИК и длительности испытаний (PDF/OCR и импорт Word)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import select

from backend.app.infrastructure.db.models.pipeline import PipelineORM
from backend.app.infrastructure.db.models.vik import VikORM
from backend.app.shared.pipeline_code_confusables import normalize_pipeline_code_confusable_o_to_zero
from backend.app.shared.pipeline_number_format import normalize_pipeline_name
from backend.app.shared.strength_test_duration import format_strength_test_duration


def normalize_import_db_value(raw_value: Any) -> str | None:
    if not isinstance(raw_value, str):
        return None
    value = raw_value.strip()
    if not value:
        return None
    if value.startswith("[НЕОПОЗНАН"):
        return None
    return value


def normalize_vik_type(raw_value: Any) -> str:
    if not isinstance(raw_value, str):
        return "ВИК"
    value = raw_value.strip().upper()
    if value in {"ВИК", "УЗК", "ПВК", "СТИЛОСКОПИРОВАНИЕ"}:
        return value
    return "ВИК"


def vik_pipeline_name_lookup_variants(pipe_num: str) -> list[str]:
    """
    Варианты имени линии для поиска в БД (OCR/Excel иногда дают «_» вместо «-» в коде).
    Порядок: каноническое имя без ведущего №, затем как в источнике, legacy с №.
    """
    s = (pipe_num or "").strip()
    if not s:
        return []
    canonical = normalize_pipeline_name(s)
    alt = s.replace("_", "-")
    variants: list[str] = []
    for item in (canonical, s, alt, f"№{canonical}" if canonical else ""):
        if item and item not in variants:
            variants.append(item)
    return variants


def _resolve_pipeline_orm(
    pipeline_by_name: dict[str, PipelineORM],
    pipe_num: str,
) -> PipelineORM | None:
    for key in vik_pipeline_name_lookup_variants(pipe_num):
        p = pipeline_by_name.get(key)
        if p is not None:
            return p
    return None


async def upsert_vik_entries(
    session_factory: Callable[..., Any],
    rows: list[dict[str, str]],
    *,
    replace_existing_for_pipe_type: bool = False,
) -> dict[str, Any]:
    if not rows:
        return {
            "processed_total": 0,
            "pipelines_found": 0,
            "inserted_total": 0,
            "duplicates_total": 0,
            "not_found_total": 0,
        }

    normalized_rows: list[dict[str, str]] = []
    for row in rows:
        pipe_num = normalize_import_db_value(row.get("pipe_num"))
        if pipe_num:
            pipe_num = normalize_pipeline_code_confusable_o_to_zero(pipe_num)
            pipe_num = normalize_pipeline_name(pipe_num)
        statement_text = normalize_import_db_value(row.get("statement_text"))
        vik_type = normalize_vik_type(row.get("type"))
        if not pipe_num or not statement_text:
            continue
        normalized_rows.append(
            {"pipe_num": pipe_num, "statement_text": statement_text, "type": vik_type}
        )

    if not normalized_rows:
        return {
            "processed_total": 0,
            "pipelines_found": 0,
            "inserted_total": 0,
            "duplicates_total": 0,
            "not_found_total": 0,
        }

    inserted_total = 0
    updated_total = 0
    duplicates_total = 0
    not_found_total = 0
    pipelines_found: set[int] = set()

    async with session_factory() as session:
        lookup_names: set[str] = set()
        for row in normalized_rows:
            for v in vik_pipeline_name_lookup_variants(row["pipe_num"]):
                lookup_names.add(v)
        pipelines = (
            await session.execute(
                select(PipelineORM).where(PipelineORM.name.in_(sorted(lookup_names)))
            )
        ).scalars().all()
        pipeline_by_name = {str(p.name): p for p in pipelines}

        pipeline_ids = [int(p.id) for p in pipelines]
        types = sorted({row["type"] for row in normalized_rows})
        existing_rows: list[VikORM] = []
        if pipeline_ids and types:
            existing_rows = list(
                (
                    await session.execute(
                        select(VikORM).where(
                            VikORM.pipeline_id.in_(pipeline_ids),
                            VikORM.type.in_(types),
                        )
                    )
                ).scalars().all()
            )

        existing_by_pipe_type: dict[tuple[int, str], list[VikORM]] = {}
        existing_statement_keys: set[tuple[int, str, str]] = set()
        for item in existing_rows:
            key = (int(item.pipeline_id), str(item.type or "ВИК"))
            existing_by_pipe_type.setdefault(key, []).append(item)
            existing_statement_keys.add(
                (
                    int(item.pipeline_id),
                    str(getattr(item, "statement_text", "") or ""),
                    str(item.type or "ВИК"),
                )
            )

        for row in normalized_rows:
            pipe_num_raw = row["pipe_num"]
            statement_text = row["statement_text"]
            vik_type = row["type"]

            pipeline = _resolve_pipeline_orm(pipeline_by_name, pipe_num_raw)
            if pipeline is None:
                not_found_total += 1
                continue

            pipeline_name = str(pipeline.name)
            pipelines_found.add(int(pipeline.id))
            row_key = (int(pipeline.id), statement_text, vik_type)
            if replace_existing_for_pipe_type:
                pipe_type_key = (int(pipeline.id), vik_type)
                pipe_type_rows = existing_by_pipe_type.get(pipe_type_key, [])
                if pipe_type_rows:
                    same_statement = any(
                        (getattr(item, "statement_text", "") or "") == statement_text
                        for item in pipe_type_rows
                    )
                    if same_statement:
                        duplicates_total += 1
                        continue
                    # При повторной загрузке НК-файла обновляем актуальной записью,
                    # чтобы исправления парсинга (например даты) перезаписывали старое значение.
                    previous_statement = str(
                        getattr(pipe_type_rows[0], "statement_text", "") or ""
                    )
                    existing_statement_keys.discard(
                        (int(pipeline.id), previous_statement, vik_type)
                    )
                    pipe_type_rows[0].pipe_num = pipeline_name
                    pipe_type_rows[0].statement_text = statement_text
                    existing_statement_keys.add(row_key)
                    for stale in pipe_type_rows[1:]:
                        stale_key = (
                            int(pipeline.id),
                            str(getattr(stale, "statement_text", "") or ""),
                            vik_type,
                        )
                        existing_statement_keys.discard(stale_key)
                        await session.delete(stale)
                    existing_by_pipe_type[pipe_type_key] = [pipe_type_rows[0]]
                    updated_total += 1
                    continue

            if row_key in existing_statement_keys:
                duplicates_total += 1
                continue

            session.add(
                VikORM(
                    pipeline_id=pipeline.id,
                    pipe_num=pipeline_name,
                    statement_text=statement_text,
                    type=vik_type,
                )
            )
            existing_statement_keys.add(row_key)
            inserted_total += 1

        await session.flush()
        await session.commit()

    return {
        "processed_total": len(normalized_rows),
        "pipelines_found": len(pipelines_found),
        "inserted_total": inserted_total,
        "updated_total": updated_total,
        "duplicates_total": duplicates_total,
        "not_found_total": not_found_total,
    }


async def update_strength_test_duration_rows(
    session_factory: Callable[..., Any],
    rows: list[dict[str, str]],
) -> dict[str, Any]:
    if not rows:
        return {
            "processed_total": 0,
            "pipelines_found": 0,
            "updated_total": 0,
            "not_found_total": 0,
        }

    normalized_rows: list[dict[str, str]] = []
    for row in rows:
        pipeline_name = normalize_import_db_value(row.get("pipeline"))
        if pipeline_name:
            pipeline_name = normalize_pipeline_code_confusable_o_to_zero(pipeline_name)
            pipeline_name = normalize_pipeline_name(pipeline_name)
        raw_test_time = normalize_import_db_value(row.get("test_time"))
        test_time = format_strength_test_duration(raw_test_time) if raw_test_time else None
        if not pipeline_name or not test_time:
            continue
        normalized_rows.append({"pipeline": pipeline_name, "test_time": test_time})

    if not normalized_rows:
        return {
            "processed_total": 0,
            "pipelines_found": 0,
            "updated_total": 0,
            "not_found_total": 0,
        }

    pipelines_found: set[int] = set()
    updated_total = 0
    not_found_total = 0

    async with session_factory() as session:
        lookup_names: set[str] = set()
        for row in normalized_rows:
            for v in vik_pipeline_name_lookup_variants(row["pipeline"]):
                lookup_names.add(v)
        pipelines = (
            await session.execute(
                select(PipelineORM).where(PipelineORM.name.in_(sorted(lookup_names)))
            )
        ).scalars().all()
        pipeline_by_name = {str(p.name): p for p in pipelines}

        for row in normalized_rows:
            pipeline_name_raw = row["pipeline"]
            test_time = row["test_time"]
            pipeline = _resolve_pipeline_orm(pipeline_by_name, pipeline_name_raw)
            if pipeline is None:
                not_found_total += 1
                continue

            pipelines_found.add(int(pipeline.id))
            params = dict(pipeline.parameters or {})
            if params.get("strength_test_duration") != test_time:
                params["strength_test_duration"] = test_time
                pipeline.parameters = params
                updated_total += 1

        await session.flush()
        await session.commit()

    return {
        "processed_total": len(normalized_rows),
        "pipelines_found": len(pipelines_found),
        "updated_total": updated_total,
        "not_found_total": not_found_total,
    }
