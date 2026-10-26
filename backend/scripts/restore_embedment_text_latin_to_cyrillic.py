"""
Восстановление в текстах закладных строчной кириллицы вместо «омоглифной» латиницы
(обратно к cyrillic_to_latin_for_instrument_tag: a→а, b→в, …).

**Не трогает** номера: `instrument_tag`, `embedment_group_key`, `peer_tags`, `dedup_key`,
колонки `spec_items.name` / `unit` / `quantity` / `page` / `position`.

Обрабатывает строки в `extra` (location, dn, pn, material_grade, gost, embedment_elements[*]),
аналогично `instrument_embedment_saved.extra` и `embedment_group_drafts.payload` (кроме теговых ключей).

Заглавная латиница (например G в G1/2) не меняется.

Примеры:
  uv run python -m backend.scripts.restore_embedment_text_latin_to_cyrillic --dry-run
  uv run python -m backend.scripts.restore_embedment_text_latin_to_cyrillic
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from backend.app.domain.models.spec_section import SpecSection
from backend.app.domain.parsing.drawing_tag_normalize import latin_homoglyph_lowercase_to_cyrillic
from backend.app.infrastructure.db.database import AsyncSessionLocal, engine
from backend.app.infrastructure.db.models.embedment_group_draft import EmbedmentGroupDraftORM
from backend.app.infrastructure.db.models.instrument_embedment_saved import InstrumentEmbedmentSavedORM
from backend.app.infrastructure.db.models.spec_item import SpecItemORM

_DATA_STR_KEYS = frozenset({"location", "dn", "pn", "material_grade", "gost"})
_ELEM_KEYS = frozenset({"name", "location", "dn", "pn", "material_grade", "gost"})


def _restore_str(s: str) -> tuple[str, bool]:
    new = latin_homoglyph_lowercase_to_cyrillic(s)
    return new, new != s


def _patch_embedment_data_extra(ex: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Возвращает (новый extra, число изменённых полей)."""
    n = dict(ex or {})
    n_changed = 0
    for key in _DATA_STR_KEYS:
        if key not in n:
            continue
        val = n[key]
        if not isinstance(val, str):
            continue
        new, ch = _restore_str(val)
        if ch:
            n[key] = new
            n_changed += 1
    raw_el = n.get("embedment_elements")
    if isinstance(raw_el, list):
        new_rows: list[Any] = []
        for item in raw_el:
            if not isinstance(item, dict):
                new_rows.append(item)
                continue
            d = dict(item)
            for k in _ELEM_KEYS:
                if k not in d:
                    continue
                v = d[k]
                if not isinstance(v, str):
                    continue
                new, ch = _restore_str(v)
                if ch:
                    d[k] = new
                    n_changed += 1
            new_rows.append(d)
        n["embedment_elements"] = new_rows
    return n, n_changed


def _patch_draft_payload_data(payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    p = dict(payload or {})
    n_changed = 0
    for key in _DATA_STR_KEYS:
        if key not in p:
            continue
        val = p[key]
        if not isinstance(val, str):
            continue
        new, ch = _restore_str(val)
        if ch:
            p[key] = new
            n_changed += 1
    raw_el = p.get("embedment_elements")
    if isinstance(raw_el, list):
        new_rows: list[Any] = []
        for item in raw_el:
            if not isinstance(item, dict):
                new_rows.append(item)
                continue
            d = dict(item)
            for k in _ELEM_KEYS:
                if k not in d:
                    continue
                v = d[k]
                if not isinstance(v, str):
                    continue
                new, ch = _restore_str(v)
                if ch:
                    d[k] = new
                    n_changed += 1
            new_rows.append(d)
        p["embedment_elements"] = new_rows
    return p, n_changed


async def _run(*, dry_run: bool) -> dict[str, int]:
    stats = {
        "spec_items_updated": 0,
        "spec_fields_changed": 0,
        "saved_embedments_updated": 0,
        "saved_fields_changed": 0,
        "drafts_updated": 0,
        "draft_fields_changed": 0,
    }
    async with AsyncSessionLocal() as session:
        r = await session.execute(
            select(SpecItemORM).where(SpecItemORM.section == SpecSection.INSTRUMENT_EMBEDMENT.value)
        )
        for row in r.scalars().all():
            ex = dict(row.extra or {})
            new_ex, nch = _patch_embedment_data_extra(ex)
            if nch:
                row.extra = new_ex
                flag_modified(row, "extra")
                stats["spec_items_updated"] += 1
                stats["spec_fields_changed"] += nch

        r2 = await session.execute(select(InstrumentEmbedmentSavedORM))
        for row in r2.scalars().all():
            ex = dict(row.extra or {})
            new_ex, nch = _patch_embedment_data_extra(ex)
            if nch:
                row.extra = new_ex
                flag_modified(row, "extra")
                stats["saved_embedments_updated"] += 1
                stats["saved_fields_changed"] += nch

        r3 = await session.execute(select(EmbedmentGroupDraftORM))
        for row in r3.scalars().all():
            pl = row.payload if isinstance(row.payload, dict) else {}
            new_pl, nch = _patch_draft_payload_data(pl)
            if nch:
                row.payload = new_pl
                flag_modified(row, "payload")
                stats["drafts_updated"] += 1
                stats["draft_fields_changed"] += nch

        if dry_run:
            await session.rollback()
        else:
            await session.commit()

    await engine.dispose()
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="Откат без записи в БД")
    args = ap.parse_args()
    stats = asyncio.run(_run(dry_run=args.dry_run))
    mode = "dry-run" if args.dry_run else "committed"
    logger.info("restore_embedment_text_latin_to_cyrillic {} stats={}", mode, stats)
    print(f"{mode}: {stats}")


if __name__ == "__main__":
    main()
