"""
One-off: убрать ведущий № из имён трубопроводов в БД (канонический вид без №).

Запуск (dry-run):
    uv run python -m backend.scripts.normalize_pipeline_names_number_sign

Применить:
    uv run python -m backend.scripts.normalize_pipeline_names_number_sign --apply
"""

from __future__ import annotations

import argparse
import asyncio

from loguru import logger
from sqlalchemy import select

from backend.app.infrastructure.db.database import AsyncSessionLocal, engine
from backend.app.infrastructure.db.models.pipeline import PipelineORM
from backend.app.infrastructure.db.models.vik import VikORM
from backend.app.shared.pipeline_number_format import normalize_pipeline_name


async def normalize_pipeline_names_number_sign(
    *,
    apply: bool,
    limit: int | None,
) -> dict[str, int]:
    scanned = 0
    renamed = 0
    skipped_conflict = 0
    vik_updated = 0

    try:
        async with AsyncSessionLocal() as session:
            stmt = select(PipelineORM).order_by(PipelineORM.id)
            if isinstance(limit, int) and limit > 0:
                stmt = stmt.limit(limit)
            pipelines = list((await session.execute(stmt)).scalars().all())
            names_in_db = {p.name for p in pipelines}

            for pipeline in pipelines:
                scanned += 1
                canonical = normalize_pipeline_name(pipeline.name)
                if canonical == pipeline.name:
                    continue
                if canonical in names_in_db and canonical != pipeline.name:
                    logger.warning(
                        "Skip rename due to conflict. old={} canonical={} existing_id_conflict",
                        pipeline.name,
                        canonical,
                    )
                    skipped_conflict += 1
                    continue

                logger.info(
                    "Rename pipeline. old={} new={} apply={}",
                    pipeline.name,
                    canonical,
                    apply,
                )
                if apply:
                    old_name = pipeline.name
                    pipeline.name = canonical
                    names_in_db.discard(old_name)
                    names_in_db.add(canonical)

                    vik_rows = list(
                        (
                            await session.execute(
                                select(VikORM).where(VikORM.pipe_num == old_name)
                            )
                        ).scalars().all()
                    )
                    for row in vik_rows:
                        row.pipe_num = canonical
                        vik_updated += 1

                renamed += 1

            if apply:
                await session.commit()
            else:
                await session.rollback()
    finally:
        await engine.dispose()

    return {
        "scanned": scanned,
        "renamed": renamed,
        "skipped_conflict": skipped_conflict,
        "vik_updated": vik_updated,
        "applied": int(apply),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Normalize pipeline names: strip leading № in DB"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes (default: dry-run)",
    )
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    stats = asyncio.run(
        normalize_pipeline_names_number_sign(apply=args.apply, limit=args.limit)
    )
    logger.info("Done. stats={}", stats)


if __name__ == "__main__":
    main()
