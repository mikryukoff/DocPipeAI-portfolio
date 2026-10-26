from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from backend.app.domain.models.spec_section import SpecSection
from backend.app.domain.parsing.drawing_tag_normalize import instrument_tag_dedup_key
from backend.app.infrastructure.db.models.spec_item import SpecItemORM

_MAX_EMBEDMENT_ELEMENT_ROWS = 20


def _normalize_embedment_element_row(el: dict) -> dict:
    return {
        "name": (str(el.get("name") or "").strip() or "---"),
        "location": (str(el.get("location") or "").strip() or "---"),
        "dn": (str(el.get("dn") or "").strip() or "---"),
        "pn": (str(el.get("pn") or "").strip() or "---"),
        "material_grade": (str(el.get("material_grade") or "").strip() or "---"),
        "gost": (str(el.get("gost") or "").strip() or "---"),
    }


class SpecItemRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def find_armatures_by_name_prefix(self, prefix: str) -> list[SpecItemORM]:
        stmt = (
            select(SpecItemORM)
            .where(
                SpecItemORM.section == "pipeline_armature",
                SpecItemORM.name.like(f"{prefix}%"),
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_armatures_by_running_number(self, running_number: str) -> list[SpecItemORM]:
        if not running_number:
            return []
        stmt = (
            select(SpecItemORM)
            .where(
                SpecItemORM.section == "pipeline_armature",
                SpecItemORM.name.like(f"%V{running_number}%"),
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def apply_armature_excel_update(
        self,
        *,
        source_prefix: str,
        normalized_name: str,
        dn: str,
        pn: str,
        material_grade: str,
        gost: str,
        source_raw: str,
    ) -> int:
        items = await self.find_armatures_by_name_prefix(source_prefix)
        if not items:
            return 0

        for item in items:
            extra = dict(item.extra or {})
            extra["dn"] = dn
            extra["pn"] = pn
            extra["material_grade"] = material_grade
            extra["source_excel_armature"] = source_raw
            if gost:
                extra["gost"] = gost

            item.name = normalized_name
            item.extra = extra

        await self.session.flush()
        return len(items)

    async def apply_armature_excel_update_by_running_number(
        self,
        *,
        running_number: str,
        normalized_name: str,
        dn: str,
        pn: str,
        material_grade: str,
        gost: str,
        source_raw: str,
    ) -> int:
        items = await self.find_armatures_by_running_number(running_number)
        if not items:
            return 0

        for item in items:
            extra = dict(item.extra or {})
            extra["dn"] = dn
            extra["pn"] = pn
            extra["material_grade"] = material_grade
            extra["source_excel_armature"] = source_raw
            if gost:
                extra["gost"] = gost

            item.name = normalized_name
            item.extra = extra

        await self.session.flush()
        return len(items)

    async def list_instrument_embedments(self, pipeline_id: int) -> list[SpecItemORM]:
        stmt = (
            select(SpecItemORM)
            .where(
                SpecItemORM.pipeline_id == pipeline_id,
                SpecItemORM.section == SpecSection.INSTRUMENT_EMBEDMENT.value,
            )
            .order_by(SpecItemORM.page, SpecItemORM.position)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_instrument_embedment_group(
        self,
        *,
        pipeline_id: int,
        embedment_group_key: str,
        peer_tags: set[str],
        location: str,
        dn: str,
        pn: str,
        material_grade: str,
        gost: str,
        elements: list[dict] | None = None,
        drawing_image_path: str | None = None,
    ) -> int:
        items = await self.list_instrument_embedments(pipeline_id)
        gk = (embedment_group_key or "").strip()
        peers = {p.strip() for p in peer_tags if p and str(p).strip()}
        peer_cf = {instrument_tag_dedup_key(p) for p in peers}
        peer_cf.discard("")
        gk_cf = instrument_tag_dedup_key(gk) if gk else ""
        updated = 0
        normalized_rows: list[dict] | None = None
        if elements is not None:
            normalized_rows = [
                _normalize_embedment_element_row(e)
                for e in elements[:_MAX_EMBEDMENT_ELEMENT_ROWS]
                if isinstance(e, dict)
            ]
        for item in items:
            ex = dict(item.extra or {})
            tag = (ex.get("instrument_tag") or "").strip()
            row_gk = (ex.get("embedment_group_key") or "").strip()
            match = False
            if gk_cf and row_gk and instrument_tag_dedup_key(row_gk) == gk_cf:
                match = True
            elif tag:
                tag_cf = instrument_tag_dedup_key(tag)
                if tag_cf and tag_cf in peer_cf:
                    match = True
            if not match:
                continue
            if normalized_rows is not None:
                rows = normalized_rows
                if not rows:
                    rows = [
                        _normalize_embedment_element_row(
                            {
                                "name": "---",
                                "location": location,
                                "dn": dn,
                                "pn": pn,
                                "material_grade": material_grade,
                                "gost": gost,
                            }
                        )
                    ]
                ex["embedment_elements"] = rows
                first = rows[0]
                ex["location"] = first["location"]
                ex["dn"] = first["dn"]
                ex["pn"] = first["pn"]
                ex["material_grade"] = first["material_grade"]
                ex["gost"] = first["gost"]
            else:
                ex["location"] = location
                ex["dn"] = dn
                ex["pn"] = pn
                ex["material_grade"] = material_grade
                ex["gost"] = gost
            if gk:
                ex["embedment_group_key"] = gk
            ex["source_manual_embedment"] = True
            dp = (drawing_image_path or "").strip() if drawing_image_path is not None else ""
            if dp:
                ex["drawing_image_path"] = dp.replace("\\", "/")
            item.extra = ex
            flag_modified(item, "extra")
            updated += 1
        await self.session.flush()
        return updated

    async def sync_instrument_embedment_drawing_paths_from_store(
        self,
        *,
        only_missing: bool = True,
    ) -> int:
        """
        Проставляет extra.drawing_image_path (и при необходимости embedment_group_key) из
        Drawing4Store (merged.json / parsed_texts) для всех строк закладных в БД.

        Перед чтением сбрасывает кэш store, чтобы подхватить свежие файлы без перезапуска процесса.

        only_missing=True — не трогать строки, у которых путь к скрину уже задан.
        only_missing=False — перезаписать путь из JSON, если для тега есть запись в каталоге.
        """
        from backend.app.domain.parsing.drawing_4_store import get_drawing_4_store, reset_drawing_4_store

        reset_drawing_4_store()
        store = get_drawing_4_store()

        stmt = select(SpecItemORM).where(
            SpecItemORM.section == SpecSection.INSTRUMENT_EMBEDMENT.value,
        )
        result = await self.session.execute(stmt)
        rows = list(result.scalars().all())
        updated = 0
        for item in rows:
            ex = dict(item.extra or {})
            tag = (ex.get("instrument_tag") or "").strip()
            entry = store.resolve(tag) if tag else None
            if entry is None:
                gk = (ex.get("embedment_group_key") or "").strip()
                if gk:
                    entry = store.resolve(gk)
            if entry is None:
                continue
            rel = (entry.path or "").strip().replace("\\", "/")
            if not rel:
                continue
            cur = (ex.get("drawing_image_path") or "").strip().replace("\\", "/")
            if only_missing and cur:
                continue
            gk_new = (entry.group_key or "").strip()
            gk_cur = (ex.get("embedment_group_key") or "").strip()
            changed = False
            if cur != rel:
                ex["drawing_image_path"] = rel
                changed = True
            if gk_new and not gk_cur:
                ex["embedment_group_key"] = gk_new
                changed = True
            if not changed:
                continue
            item.extra = ex
            flag_modified(item, "extra")
            updated += 1
        if updated:
            await self.session.flush()
        return updated
