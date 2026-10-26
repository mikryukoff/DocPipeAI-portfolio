"""
Проставить в БД пути к скриншотам закладных из Drawing4Store (merged.json / parsed_texts).

По умолчанию обновляет только строки без drawing_image_path. С --overwrite перезаписывает путь
из JSON и при необходимости дописывает пустой embedment_group_key.

Примеры:
  uv run python -m backend.scripts.sync_embedment_drawing_paths
  uv run python -m backend.scripts.sync_embedment_drawing_paths --overwrite
"""

from __future__ import annotations

import argparse
import asyncio

from loguru import logger

from backend.app.infrastructure.db.database import AsyncSessionLocal, engine
from backend.app.infrastructure.repositories.spec_item_repository import SpecItemRepository


async def run_sync(*, only_missing: bool) -> int:
    try:
        async with AsyncSessionLocal() as session:
            repo = SpecItemRepository(session)
            n = await repo.sync_instrument_embedment_drawing_paths_from_store(only_missing=only_missing)
            await session.commit()
            return n
    finally:
        await engine.dispose()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--overwrite",
        action="store_true",
        help="Перезаписать drawing_image_path даже если он уже задан",
    )
    args = ap.parse_args()
    only_missing = not args.overwrite
    n = asyncio.run(run_sync(only_missing=only_missing))
    logger.info("sync_embedment_drawing_paths done. updated={} only_missing={}", n, only_missing)
    print(f"Обновлено строк: {n} (only_missing={only_missing})")


if __name__ == "__main__":
    main()
