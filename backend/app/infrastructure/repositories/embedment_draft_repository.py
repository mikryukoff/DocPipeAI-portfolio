from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from backend.app.domain.models.spec_section import SpecSection
from backend.app.infrastructure.db.models.embedment_group_draft import EmbedmentGroupDraftORM
from backend.app.infrastructure.db.models.spec_item import SpecItemORM
from backend.app.infrastructure.embedment_extra import (
    embedment_draft_dedup_key,
    instrument_embedment_extra_enriched,
)


def _norm_path(path: str | None) -> str:
    return (path or "").strip().replace("\\", "/")


class EmbedmentDraftRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def compute_dedup_key(drawing_path: str, use_key: str) -> str:
        return embedment_draft_dedup_key(drawing_path, use_key)

    async def upsert(
        self,
        *,
        pipeline_id: int,
        dedup_key: str,
        embedment_group_key: str,
        drawing_image_path: str,
        peer_tags: list[str],
        payload: dict,
    ) -> None:
        stmt = select(EmbedmentGroupDraftORM).where(
            EmbedmentGroupDraftORM.pipeline_id == pipeline_id,
            EmbedmentGroupDraftORM.dedup_key == dedup_key,
        )
        row = await self.session.scalar(stmt)
        path_val = (drawing_image_path or "").strip() or None
        if row is not None:
            row.embedment_group_key = (embedment_group_key or "").strip()
            row.drawing_image_path = path_val
            row.peer_tags = list(peer_tags)
            row.payload = dict(payload)
        else:
            self.session.add(
                EmbedmentGroupDraftORM(
                    pipeline_id=pipeline_id,
                    dedup_key=dedup_key,
                    embedment_group_key=(embedment_group_key or "").strip(),
                    drawing_image_path=path_val,
                    peer_tags=list(peer_tags),
                    payload=dict(payload),
                )
            )
        await self.session.flush()

    def _matches_draft(self, draft: EmbedmentGroupDraftORM, ex: dict) -> bool:
        path_norm = _norm_path(draft.drawing_image_path)
        row_path = _norm_path(ex.get("drawing_image_path"))
        tag = (ex.get("instrument_tag") or "").strip()
        row_gk = (ex.get("embedment_group_key") or "").strip()
        gk = (draft.embedment_group_key or "").strip()
        peers = draft.peer_tags if isinstance(draft.peer_tags, list) else []
        peer_set = {str(p).strip() for p in peers if p and str(p).strip()}

        if path_norm and row_path == path_norm:
            return True
        if tag and tag in peer_set:
            return True
        if gk and row_gk == gk:
            return True
        return False

    def _apply_payload(self, ex: dict, payload: dict, canonical_gk: str) -> None:
        rows = payload.get("embedment_elements")
        if isinstance(rows, list) and rows:
            ex["embedment_elements"] = rows
            first = rows[0] if isinstance(rows[0], dict) else {}
            ex["location"] = first.get("location", "---") or "---"
            ex["dn"] = first.get("dn", "---") or "---"
            ex["pn"] = first.get("pn", "---") or "---"
            ex["material_grade"] = first.get("material_grade", "---") or "---"
            ex["gost"] = first.get("gost", "---") or "---"
        else:
            ex["location"] = payload.get("location", "---") or "---"
            ex["dn"] = payload.get("dn", "---") or "---"
            ex["pn"] = payload.get("pn", "---") or "---"
            ex["material_grade"] = payload.get("material_grade", "---") or "---"
            ex["gost"] = payload.get("gost", "---") or "---"
        if canonical_gk:
            ex["embedment_group_key"] = canonical_gk
        ex["source_manual_embedment"] = True

    async def apply_to_pipeline(self, pipeline_id: int) -> int:
        drafts = (
            (
                await self.session.execute(
                    select(EmbedmentGroupDraftORM).where(
                        EmbedmentGroupDraftORM.pipeline_id == pipeline_id
                    )
                )
            )
            .scalars()
            .all()
        )
        if not drafts:
            return 0

        items = (
            (
                await self.session.execute(
                    select(SpecItemORM).where(
                        SpecItemORM.pipeline_id == pipeline_id,
                        SpecItemORM.section == SpecSection.INSTRUMENT_EMBEDMENT.value,
                    )
                )
            )
            .scalars()
            .all()
        )

        updated = 0
        for item in items:
            ex = dict(item.extra or {})
            if instrument_embedment_extra_enriched(ex):
                continue
            for draft in drafts:
                if not self._matches_draft(draft, ex):
                    continue
                self._apply_payload(ex, draft.payload, (draft.embedment_group_key or "").strip())
                dp = _norm_path(draft.drawing_image_path)
                if dp:
                    ex["drawing_image_path"] = dp
                item.extra = ex
                flag_modified(item, "extra")
                updated += 1
                break

        if updated:
            await self.session.flush()
        return updated
