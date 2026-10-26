"""
Пройти по БД и заменить в **номерах приборов** (поля тега) кириллицу, визуально совпадающую с латиницей
(`instrument_tag`, `embedment_group_key` в extra; в черновиках — теговые поля, peer_tags, суффикс `gk:` в dedup_key).
Тексты в `embedment_elements`, описания и прочие русские поля **не меняются**.

Для spec_items (закладные): если есть строка с «грязным» номером и **где-то в БД** есть чистая с тем же
номером после нормализации, в грязную **копируются** extra и поля name/unit/quantity с одной чистой
(выбирается самая заполненная), номер в extra становится как у чистой — грязные **не удаляются**.
Если в группе по dedup-ключу **только** грязные строки — **все** они удаляются (для повторного парсинга).

Затрагивает:
  - spec_items с section=instrument_embedments (только теговые ключи в extra + логика merge/delete);
  - instrument_embedment_saved.extra (только теговые ключи);
  - embedment_group_drafts (dedup_key с учётом path:/gk:, embedment_group_key, peer_tags, payload теговые поля).

Уже испорченные описания в БД этот скрипт **не восстанавливает** — нужен бэкап до прогона или ручное исправление.
После правки кода повторный запуск не трогает не-теговые строки.

Без --dry-run выполняет commit. При коллизии uq_embedment_draft_pipeline_dedup строка черновика
пропускается с предупреждением в лог.

Примеры:
  uv run python -m backend.scripts.normalize_embedment_cyrillic_tags --dry-run
  uv run python -m backend.scripts.normalize_embedment_cyrillic_tags
"""

from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from copy import deepcopy
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.attributes import flag_modified

from backend.app.domain.models.spec_section import SpecSection
from backend.app.domain.parsing.drawing_tag_normalize import (
    cyrillic_to_latin_for_instrument_tag,
    instrument_tag_dedup_key,
    normalize_embedment_auxiliary_text,
    normalize_instrument_tag_label,
)
from backend.app.infrastructure.db.database import AsyncSessionLocal, engine
from backend.app.infrastructure.db.models.embedment_group_draft import EmbedmentGroupDraftORM
from backend.app.infrastructure.db.models.instrument_embedment_saved import InstrumentEmbedmentSavedORM
from backend.app.infrastructure.db.models.spec_item import SpecItemORM


def _norm_instrument_tag_field(raw: object) -> str:
    """Только для номера/ключа прибора (омоглифы кириллицы → латиница)."""
    return normalize_instrument_tag_label("" if raw is None else str(raw))


def _norm_dedup_key(raw: object) -> str:
    """dedup_key: path: — без омоглифов; gk: — нормализация тега; иначе как тег."""
    s = "" if raw is None else str(raw)
    s = s.strip()
    if s.startswith("path:"):
        return "path:" + normalize_embedment_auxiliary_text(s[5:])
    if s.startswith("gk:"):
        return "gk:" + normalize_instrument_tag_label(s[3:])
    return normalize_instrument_tag_label(s)


def _patch_embedment_extra(ex: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    n = dict(ex or {})
    changed = False
    for key in ("instrument_tag", "embedment_group_key"):
        if key not in n:
            continue
        old = n[key]
        old_s = "" if old is None else str(old)
        new = _norm_instrument_tag_field(old_s)
        if new != old_s:
            n[key] = new
            changed = True
    return n, changed


def _patch_draft_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    p = dict(payload or {})
    changed = False
    for key in ("instrument_tag", "embedment_group_key"):
        if key not in p:
            continue
        old_s = "" if p[key] is None else str(p[key])
        new = _norm_instrument_tag_field(old_s)
        if new != old_s:
            p[key] = new
            changed = True
    return p, changed


def _instrument_tag_had_homoglyph_cyrillic(raw: object) -> bool:
    s = "" if raw is None else str(raw)
    return cyrillic_to_latin_for_instrument_tag(s) != s


def _embedment_plan_dirty(row: Any) -> bool:
    return _instrument_tag_had_homoglyph_cyrillic(dict(row.extra or {}).get("instrument_tag"))


def _embedment_template_score(new_ex: dict[str, Any]) -> int:
    sc = 0
    if str(new_ex.get("drawing_image_path") or "").strip():
        sc += 500
    el = new_ex.get("embedment_elements")
    if isinstance(el, list):
        sc += min(len(el), 50) * 5
    for k in ("location", "dn", "pn", "material_grade", "gost"):
        v = str(new_ex.get(k) or "").strip()
        if v and v != "---":
            sc += 3
    return sc


def _pick_clean_template(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Среди чистых планов — самый «богатый» extra, при равенстве — меньший id."""
    return sorted(
        entries,
        key=lambda e: (-_embedment_template_score(e["new_ex"]), int(e["row"].id)),
    )[0]


def _merge_clean_template_into_dirty_plans(plans: list[dict[str, Any]]) -> int:
    """
    По группам instrument_tag_dedup_key(new_it): грязные строки получают deepcopy(extra) и
    name/unit/quantity с лучшей чистой строки группы. Возвращает число выполненных слияний.
    """
    by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in plans:
        it = (e["new_it"] or "").strip()
        if not it:
            continue
        by_key[instrument_tag_dedup_key(it)].append(e)

    merged = 0
    for _key, group in by_key.items():
        if len(group) < 2:
            continue
        cleaners = [e for e in group if not _embedment_plan_dirty(e["row"])]
        dirtiers = [e for e in group if _embedment_plan_dirty(e["row"])]
        if not cleaners or not dirtiers:
            continue
        tpl = _pick_clean_template(cleaners)
        tex = deepcopy(tpl["new_ex"])
        r0 = tpl["row"]
        for d in dirtiers:
            d["new_ex"] = deepcopy(tex)
            d["new_it"] = str(tex.get("instrument_tag") or "")
            d["ch"] = True
            d["merged_from_clean"] = True
            d["tpl_name"] = r0.name
            d["tpl_unit"] = r0.unit
            d["tpl_qty"] = r0.quantity
            merged += 1
    return merged


def _plan_spec_embedment_deletions(plans: list[dict[str, Any]]) -> set[int]:
    """
    Только группы, где **все** строки с омоглифной кириллицей в instrument_tag — удалить все id группы.
    """
    by_key: dict[str, list[tuple[Any, bool]]] = defaultdict(list)
    for e in plans:
        row = e["row"]
        new_it = e["new_it"]
        it = (new_it or "").strip()
        if not it:
            continue
        key = instrument_tag_dedup_key(it)
        dirty = _embedment_plan_dirty(row)
        by_key[key].append((row, dirty))

    out: set[int] = set()
    for _key, members in by_key.items():
        if len(members) < 2:
            continue
        if any(not d for _r, d in members):
            continue
        for r, _ in members:
            out.add(int(r.id))
    return out


async def _run(*, dry_run: bool) -> dict[str, int]:
    stats = {
        "spec_items_updated": 0,
        "spec_items_deleted": 0,
        "spec_items_merged_from_clean": 0,
        "saved_embedments_updated": 0,
        "drafts_updated": 0,
        "drafts_skipped_integrity": 0,
    }
    async with AsyncSessionLocal() as session:
        # --- spec_items: нормализация + слияние грязных с чистыми по всей БД + удаление только all-dirty ---
        r = await session.execute(
            select(SpecItemORM).where(SpecItemORM.section == SpecSection.INSTRUMENT_EMBEDMENT.value)
        )
        embed_rows = list(r.scalars().all())
        plans: list[dict[str, Any]] = []
        for row in embed_rows:
            ex = dict(row.extra or {})
            new_ex, ch = _patch_embedment_extra(ex)
            new_it = str(new_ex.get("instrument_tag") or "")
            plans.append(
                {
                    "row": row,
                    "new_ex": new_ex,
                    "ch": ch,
                    "new_it": new_it,
                    "merged_from_clean": False,
                }
            )

        stats["spec_items_merged_from_clean"] = _merge_clean_template_into_dirty_plans(plans)

        ids_del = _plan_spec_embedment_deletions(plans)
        for row in embed_rows:
            if int(row.id) in ids_del:
                await session.delete(row)
        if ids_del:
            await session.flush()
            stats["spec_items_deleted"] = len(ids_del)

        for e in plans:
            row = e["row"]
            if int(row.id) in ids_del:
                continue
            if not e["ch"] and not e.get("merged_from_clean"):
                continue
            row.extra = e["new_ex"]
            flag_modified(row, "extra")
            if e.get("merged_from_clean"):
                row.name = e["tpl_name"]
                row.unit = e["tpl_unit"]
                row.quantity = e["tpl_qty"]
            stats["spec_items_updated"] += 1

        # --- instrument_embedment_saved ---
        r2 = await session.execute(select(InstrumentEmbedmentSavedORM))
        for row in r2.scalars().all():
            ex = dict(row.extra or {})
            new_ex, ch = _patch_embedment_extra(ex)
            if ch:
                row.extra = new_ex
                flag_modified(row, "extra")
                stats["saved_embedments_updated"] += 1

        # --- embedment_group_drafts ---
        r3 = await session.execute(select(EmbedmentGroupDraftORM))
        for row in r3.scalars().all():
            old_dedup = row.dedup_key or ""
            new_dedup = _norm_dedup_key(old_dedup)
            new_gk = _norm_instrument_tag_field(row.embedment_group_key or "")
            peers = row.peer_tags if isinstance(row.peer_tags, list) else []
            new_peers = [_norm_instrument_tag_field(str(p)) for p in peers]
            new_payload, p_ch = _patch_draft_payload(row.payload if isinstance(row.payload, dict) else {})

            gk_ch = new_gk != (row.embedment_group_key or "")
            dedup_ch = new_dedup != old_dedup
            old_peer_repr = [str(p) for p in peers]
            peers_ch = new_peers != old_peer_repr
            if not (gk_ch or dedup_ch or peers_ch or p_ch):
                continue

            async with session.begin_nested():
                try:
                    row.embedment_group_key = new_gk
                    row.peer_tags = new_peers
                    row.payload = new_payload
                    if dedup_ch:
                        row.dedup_key = new_dedup
                    await session.flush()
                    stats["drafts_updated"] += 1
                except IntegrityError:
                    stats["drafts_skipped_integrity"] += 1
                    logger.warning(
                        "embedment_group_drafts id={}: коллизия dedup_key после нормализации, пропуск",
                        row.id,
                    )

        if dry_run:
            await session.rollback()
        else:
            await session.commit()

    await engine.dispose()
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Не коммитить, только посчитать изменения",
    )
    args = ap.parse_args()
    stats = asyncio.run(_run(dry_run=args.dry_run))
    mode = "dry-run" if args.dry_run else "committed"
    logger.info("normalize_embedment_cyrillic_tags {} stats={}", mode, stats)
    print(f"{mode}: {stats}")


if __name__ == "__main__":
    main()
