"""
One-off скрипт для нормализации `parameters.strength_test_duration` в БД.

Приводит значения к каноничному виду:
    X ч. (Y мин.)

Примеры:
    30            -> 0 ч. (30 мин.)
    1 ч 30 мин    -> 1 ч. (90 мин.)

Запуск (dry-run по умолчанию):
    uv run python -m backend.scripts.normalize_strength_test_duration

Применить изменения:
    uv run python -m backend.scripts.normalize_strength_test_duration --apply
"""

from __future__ import annotations

import argparse
import asyncio

from loguru import logger
from sqlalchemy import select

from backend.app.infrastructure.db.database import AsyncSessionLocal, engine
from backend.app.infrastructure.db.models.pipeline import PipelineORM
from backend.app.shared.strength_test_duration import format_strength_test_duration


async def normalize_strength_test_duration(*, apply: bool, limit: int | None) -> dict[str, int]:
    scanned = 0
    with_duration = 0
    changed = 0
    unchanged = 0

    try:
        async with AsyncSessionLocal() as session:
            stmt = select(PipelineORM).order_by(PipelineORM.id)
            if isinstance(limit, int) and limit > 0:
                stmt = stmt.limit(limit)
            result = await session.execute(stmt)
            pipelines = list(result.scalars().all())

            for pipeline in pipelines:
                scanned += 1
                params = dict(pipeline.parameters or {})
                raw_value = params.get("strength_test_duration")
                if not isinstance(raw_value, str):
                    continue
                raw_value = raw_value.strip()
                if not raw_value:
                    continue

                with_duration += 1
                normalized = format_strength_test_duration(raw_value)
                if not normalized or normalized == raw_value:
                    unchanged += 1
                    continue

                changed += 1
                logger.info(
                    "Normalize duration. pipeline_id={} pipeline_name={} old={} new={}",
                    pipeline.id,
                    pipeline.name,
                    raw_value,
                    normalized,
                )
                if apply:
                    params["strength_test_duration"] = normalized
                    pipeline.parameters = params

            if apply:
                await session.commit()
    finally:
        await engine.dispose()

    return {
        "scanned": scanned,
        "with_duration": with_duration,
        "changed": changed,
        "unchanged": unchanged,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Normalize pipeline.parameters.strength_test_duration in DB.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Записать изменения в БД (без флага выполняется dry-run).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Ограничить количество обрабатываемых pipeline (0 = без лимита).",
    )
    args = parser.parse_args()

    summary = asyncio.run(
        normalize_strength_test_duration(
            apply=args.apply,
            limit=args.limit if args.limit > 0 else None,
        )
    )
    logger.info(
        "Duration normalization done. mode={} scanned={} with_duration={} changed={} unchanged={}",
        "apply" if args.apply else "dry-run",
        summary["scanned"],
        summary["with_duration"],
        summary["changed"],
        summary["unchanged"],
    )


if __name__ == "__main__":
    main()
