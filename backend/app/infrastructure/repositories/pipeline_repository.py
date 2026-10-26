from collections import defaultdict
from dataclasses import asdict
import re
from typing import Iterable

from loguru import logger
from sqlalchemy import select, delete, or_
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from backend.app.domain.models.spec_section import SpecSection
from backend.app.infrastructure.db.models.instrument_embedment_saved import (
    InstrumentEmbedmentSavedORM,
)
from backend.app.infrastructure.db.models.pipeline import PipelineORM
from backend.app.infrastructure.db.models.spec_item import SpecItemORM

from backend.app.domain.models.pipeline import Pipeline

from backend.app.infrastructure.db.mappers.pipeline_mapper import (
    domain_to_orm_pipeline,
    orm_to_domain_pipeline,
)
from backend.app.infrastructure.embedment_extra import instrument_embedment_extra_enriched
from backend.app.shared.pipeline_number_format import normalize_pipeline_name
from backend.app.shared.strength_test_duration import format_strength_test_duration


def _spec_item_merge_key(item: SpecItemORM) -> tuple[str, str, int, str]:
    """Один элемент спецификации на странице: позиция + раздел + ед. изм. Имя не входит — иначе дубли после Excel."""
    return (item.page, item.section, item.position, item.unit)


def _armature_enrichment_score(row: SpecItemORM) -> tuple[int, int, int, int]:
    ex = row.extra or {}
    has_src = 1 if ex.get("source_excel_armature") else 0
    g = ex.get("gost")
    has_gost = 1 if g and str(g).strip() not in ("", "---") else 0
    return (has_src, has_gost, len(row.name or ""), -row.id)


def _preserve_pipeline_armature_name(existing: SpecItemORM) -> bool:
    ex = existing.extra or {}
    if ex.get("source_excel_armature"):
        return True
    g = ex.get("gost")
    return bool(g and str(g).strip() not in ("", "---"))


# Чтобы max(id) не смешивал spec_items.id и instrument_embedment_saved.id при одинаковых числах.
_SAVED_EMBEDMENT_ID_OFFSET = 1_000_000_000


def _global_embedment_candidate_match(ex: dict, *, gk: str, peers: set[str]) -> bool:
    row_gk = (ex.get("embedment_group_key") or "").strip()
    tag = (ex.get("instrument_tag") or "").strip()
    if gk and row_gk == gk:
        return True
    if tag and tag in peers:
        return True
    return False


def _merge_spec_item_extra(existing: dict | None, incoming: dict | None) -> dict:
    out = dict(existing or {})
    for k, v in (incoming or {}).items():
        if v is None:
            continue
        if k == "embedment_elements":
            prev = out.get("embedment_elements")
            if (
                isinstance(prev, list)
                and len(prev) > 0
                and isinstance(v, list)
                and len(v) == 0
            ):
                continue
        if isinstance(v, str):
            s = v.strip()
            if not s:
                continue
            if s == "---":
                prev = out.get(k)
                if prev is not None and str(prev).strip() not in ("", "---"):
                    continue
        out[k] = v
    return out


class PipelineRepository:
    def __init__(self, session: AsyncSession):
        self.session = session
        self._pipeline_cache: dict[str, PipelineORM | None] = {}

    async def save(self, pipeline: Pipeline):
        pipeline.name = normalize_pipeline_name(pipeline.name)
        existing = await self.get_by_name(pipeline.name)
        if existing:
            logger.debug("Skip save existing pipeline. name={}", pipeline.name)
            return
        self.session.add(domain_to_orm_pipeline(pipeline))
        await self.session.flush()
        logger.debug("Pipeline inserted. name={}", pipeline.name)

    async def save_or_update(
        self,
        pipeline: Pipeline,
        replace_pages: Iterable[str] | None = None,
        *,
        job_id: int | None = None,
    ):
        pipeline.name = normalize_pipeline_name(pipeline.name)
        # Основной режим импорта: upsert трубопровода + merge spec_items без удаления старых записей.
        pipelines_len = pipeline.pipelines_len or {}
        incoming_len_json: dict[str, dict] = {}
        for dim, length_obj in pipelines_len.items():
            incoming_len_json[dim] = {
                "total_length": float(length_obj.total_length),
                "pages": list(length_obj.pages or []),
            }

        existing_orm = await self._get_pipeline_orm(pipeline.name)
        full_refresh = bool(
            existing_orm is not None
            and job_id is not None
            and existing_orm.last_import_job_id is not None
            and int(existing_orm.last_import_job_id) != int(job_id)
        )
        initial_len_json: dict[str, dict] = (
            dict(existing_orm.pipelines_len or {})
            if existing_orm and existing_orm.pipelines_len and not full_refresh
            else dict(incoming_len_json)
        )

        payload = {
            "name": pipeline.name,
            "medium": pipeline.medium,
            "mounting_scheme": pipeline.mounting_scheme,
            "year": pipeline.year,
            "flow_direction": asdict(pipeline.flow_direction),
            "parameters": asdict(pipeline.parameters),
            "pipelines_len": initial_len_json,
            "last_import_job_id": job_id if job_id is not None else (existing_orm.last_import_job_id if existing_orm else None),
        }

        upsert_stmt = mysql_insert(PipelineORM).values(**payload)
        upsert_stmt = upsert_stmt.on_duplicate_key_update(
            medium=upsert_stmt.inserted.medium,
            mounting_scheme=upsert_stmt.inserted.mounting_scheme,
            year=upsert_stmt.inserted.year,
            flow_direction=upsert_stmt.inserted.flow_direction,
            parameters=upsert_stmt.inserted.parameters,
            pipelines_len=upsert_stmt.inserted.pipelines_len,
            last_import_job_id=upsert_stmt.inserted.last_import_job_id,
        )
        await self.session.execute(upsert_stmt)

        result = await self.session.execute(
            select(PipelineORM.id).where(PipelineORM.name == pipeline.name)
        )
        pipeline_id = result.scalar_one()

        pages = {p for p in (replace_pages or []) if p}

        existing_items: list[SpecItemORM] = []
        if full_refresh:
            await self.session.execute(
                delete(SpecItemORM).where(SpecItemORM.pipeline_id == pipeline_id)
            )
            await self.session.flush()
        else:
            # Загружаем существующие spec_items для merge.
            stmt = select(SpecItemORM).where(SpecItemORM.pipeline_id == pipeline_id)
            if pages:
                stmt = stmt.where(SpecItemORM.page.in_(pages))
            existing_result = await self.session.execute(stmt)
            existing_items = list(existing_result.scalars())

        groups: defaultdict[tuple[str, str, int, str], list[SpecItemORM]] = defaultdict(list)
        for row in existing_items:
            groups[_spec_item_merge_key(row)].append(row)

        existing_by_key: dict[tuple[str, str, int, str], SpecItemORM] = {}
        for key, group in groups.items():
            if len(group) == 1:
                existing_by_key[key] = group[0]
                continue
            if key[1] == SpecSection.PIPELINE_ARMATURE.value:
                best = max(group, key=_armature_enrichment_score)
            else:
                best = min(group, key=lambda r: r.id)
            existing_by_key[key] = best
            for g in group:
                if g.id != best.id:
                    await self.session.delete(g)
        if any(len(g) > 1 for g in groups.values()):
            await self.session.flush()

        orm_pipeline = domain_to_orm_pipeline(pipeline)
        merged_count = 0
        inserted_count = 0

        for item in orm_pipeline.spec_items:
            if pages and item.page not in pages:
                continue

            key = _spec_item_merge_key(item)
            existing = existing_by_key.get(key)
            if existing is not None:
                existing.quantity = item.quantity
                if (
                    item.section == SpecSection.PIPELINE_ARMATURE.value
                    and _preserve_pipeline_armature_name(existing)
                ):
                    pass
                else:
                    existing.name = item.name
                existing.extra = _merge_spec_item_extra(existing.extra, item.extra)
                merged_count += 1
            else:
                self.session.add(
                    SpecItemORM(
                        pipeline_id=pipeline_id,
                        page=item.page,
                        section=item.section,
                        position=item.position,
                        name=item.name,
                        unit=item.unit,
                        quantity=item.quantity,
                        extra=item.extra,
                    )
                )
                inserted_count += 1

        await self.session.flush()
        await self._refresh_pipeline_lengths(pipeline_id)
        logger.debug(
            "Pipeline upserted. name={} mode={} spec_items_merged={} spec_items_inserted={}",
            pipeline.name,
            "full_refresh" if full_refresh else "merge",
            merged_count,
            inserted_count,
        )

        from backend.app.infrastructure.repositories.embedment_draft_repository import (
            EmbedmentDraftRepository,
        )

        applied = await EmbedmentDraftRepository(self.session).apply_to_pipeline(
            pipeline_id
        )
        if applied:
            logger.debug(
                "Embedment drafts applied to new spec rows. pipeline_id={} count={}",
                pipeline_id,
                applied,
            )

        propagated = await self._propagate_global_embedment_templates(pipeline_id)
        if propagated:
            logger.debug(
                "Global instrument embedment template applied. pipeline_id={} count={}",
                pipeline_id,
                propagated,
            )

    async def _refresh_pipeline_lengths(self, pipeline_id: int) -> None:
        rows_result = await self.session.execute(
            select(SpecItemORM).where(
                SpecItemORM.pipeline_id == pipeline_id,
                SpecItemORM.section == SpecSection.PIPES.value,
            )
        )
        pipe_rows = list(rows_result.scalars().all())
        recalculated = self._build_pipelines_len_from_pipe_items(pipe_rows)

        pipeline_result = await self.session.execute(
            select(PipelineORM).where(PipelineORM.id == pipeline_id)
        )
        pipeline_orm = pipeline_result.scalar_one_or_none()
        if pipeline_orm is None:
            return
        pipeline_orm.pipelines_len = recalculated
        await self.session.flush()

    @staticmethod
    def _build_pipelines_len_from_pipe_items(items: list[SpecItemORM]) -> dict[str, dict]:
        grouped: dict[str, dict[str, object]] = {}
        for item in items:
            if str(getattr(item, "section", "")) != SpecSection.PIPES.value:
                continue
            extra = dict(item.extra or {})
            dim = str(extra.get("dimensions") or "").strip()
            if not dim:
                continue
            qty = float(getattr(item, "quantity", 0.0) or 0.0)
            if qty <= 0:
                continue
            page = str(getattr(item, "page", "") or "").strip()

            entry = grouped.setdefault(dim, {"total_length": 0.0, "pages": []})
            entry["total_length"] = float(entry["total_length"]) + qty
            if page and page not in entry["pages"]:
                entry["pages"].append(page)

        out: dict[str, dict] = {}
        for dim, entry in grouped.items():
            pages = sorted(entry["pages"], key=PipelineRepository._page_sort_key)
            out[dim] = {
                "total_length": round(float(entry["total_length"]), 1),
                "pages": pages,
            }
        return out

    @staticmethod
    def _page_sort_key(page: str):
        try:
            return tuple(int(p) for p in str(page).split("."))
        except Exception:  # noqa: BLE001 - fallback key для нестандартной страницы
            return (10**9, str(page))

    async def update_flow_direction_from_excel(
        self,
        *,
        pipeline_name: str,
        flow_direction_text: str,
        source_raw: str,
    ) -> bool:
        pipeline = await self._get_pipeline_orm(pipeline_name)
        if pipeline is None:
            return False

        flow_direction = dict(pipeline.flow_direction or {})
        flow_direction["start"] = flow_direction_text
        flow_direction["end"] = ""
        flow_direction["source_excel_flow_direction"] = source_raw
        pipeline.flow_direction = flow_direction

        return True

    async def update_parameters_from_excel(
        self,
        *,
        pipeline_name: str,
        parameters_update: dict[str, str],
    ) -> bool:
        pipeline = await self._get_pipeline_orm(pipeline_name)
        if pipeline is None:
            return False

        params = dict(pipeline.parameters or {})
        for key, value in parameters_update.items():
            if not value:
                continue
            if key == "strength_test_duration":
                value = format_strength_test_duration(str(value)) or str(value)
            params[key] = value

        pipeline.parameters = params

        return True

    async def update_pipeline_aosr_fields(
        self,
        *,
        pipeline_name: str,
        mounting_scheme: str | None,
        year: int | None,
    ) -> bool:
        """Поля из АОСР: схема монтажа (ПСИ…) и год — только если в БД ещё пусто."""
        pipeline = await self._get_pipeline_orm(pipeline_name)
        if pipeline is None:
            return False
        changed = False
        ms = (mounting_scheme or "").strip()
        if ms and not (pipeline.mounting_scheme or "").strip():
            pipeline.mounting_scheme = ms
            changed = True
        if year is not None and getattr(pipeline, "year", None) is None:
            pipeline.year = year
            changed = True
        return changed

    async def get_id_by_name(self, name: str) -> int | None:
        orm = await self._get_pipeline_orm(name)
        return int(orm.id) if orm else None

    async def find_global_enriched_instrument_embedment_extra(
        self,
        *,
        peer_tags: set[str],
        embedment_group_key: str,
    ) -> dict | None:
        """Любая обогащённая закладная по всей БД с тем же group_key или instrument_tag из peer_tags.

        Совпадение обозначений между разными проектами даёт ложное переиспользование — осознанный компромисс
        до появления отдельного каталога/префикса проекта.
        """
        peers = {str(p).strip() for p in peer_tags if p and str(p).strip()}
        gk = (embedment_group_key or "").strip()
        stmt = select(SpecItemORM).where(
            SpecItemORM.section == SpecSection.INSTRUMENT_EMBEDMENT.value,
        )
        result = await self.session.execute(stmt)
        rows = list(result.scalars().all())
        candidates: list[tuple[int, dict]] = []
        for row in rows:
            ex = dict(row.extra or {})
            if not instrument_embedment_extra_enriched(ex):
                continue
            if not _global_embedment_candidate_match(ex, gk=gk, peers=peers):
                continue
            candidates.append((row.id, ex))

        stmt_saved = select(InstrumentEmbedmentSavedORM)
        result_saved = await self.session.execute(stmt_saved)
        for row in result_saved.scalars().all():
            ex = dict(row.extra or {})
            if not instrument_embedment_extra_enriched(ex):
                continue
            if not _global_embedment_candidate_match(ex, gk=gk, peers=peers):
                continue
            candidates.append((row.id + _SAVED_EMBEDMENT_ID_OFFSET, ex))

        if not candidates:
            return None
        _rid, best = max(candidates, key=lambda x: x[0])
        return dict(best)

    async def _propagate_global_embedment_templates(self, pipeline_id: int) -> int:
        """Копирует обогащённый extra из глобального каталога; совпадение по ключу JSON / alias (см. find_global_…)."""
        from backend.app.domain.parsing.drawing_4_store import get_drawing_4_store

        store = get_drawing_4_store()
        stmt = select(SpecItemORM).where(
            SpecItemORM.pipeline_id == pipeline_id,
            SpecItemORM.section == SpecSection.INSTRUMENT_EMBEDMENT.value,
        )
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())
        preserve_keys = frozenset({"instrument_tag", "drawing_image_path"})
        updated = 0
        for item in items:
            ex = dict(item.extra or {})
            if instrument_embedment_extra_enriched(ex):
                continue
            tag = (ex.get("instrument_tag") or "").strip()
            if not tag:
                continue
            entry = store.resolve(tag)
            if entry is None:
                continue
            peers = {str(p).strip() for p in entry.peer_tags if p and str(p).strip()}
            gk = (entry.group_key or "").strip()
            template = await self.find_global_enriched_instrument_embedment_extra(
                peer_tags=peers,
                embedment_group_key=gk,
            )
            if template is None:
                continue
            new_ex = dict(ex)
            for k, v in template.items():
                if k in preserve_keys:
                    continue
                new_ex[k] = v
            new_ex["embedment_group_key"] = gk
            item.extra = new_ex
            flag_modified(item, "extra")
            updated += 1
        if updated:
            await self.session.flush()
        return updated

    async def is_instrument_embedment_group_enriched(
        self,
        *,
        pipeline_id: int,
        embedment_group_key: str,
        peer_tags: set[str],
    ) -> bool:
        stmt = select(SpecItemORM).where(
            SpecItemORM.pipeline_id == pipeline_id,
            SpecItemORM.section == SpecSection.INSTRUMENT_EMBEDMENT.value,
        )
        result = await self.session.execute(stmt)
        rows = list(result.scalars().all())
        gk = (embedment_group_key or "").strip()
        peers = {str(p).strip() for p in peer_tags if p and str(p).strip()}
        for row in rows:
            ex = dict(row.extra or {})
            row_gk = (ex.get("embedment_group_key") or "").strip()
            tag = (ex.get("instrument_tag") or "").strip()
            match = False
            if gk and row_gk == gk:
                match = True
            elif tag and tag in peers:
                match = True
            if not match:
                continue
            if instrument_embedment_extra_enriched(ex):
                return True
        if (
            await self.find_global_enriched_instrument_embedment_extra(
                peer_tags=peers,
                embedment_group_key=gk,
            )
            is not None
        ):
            return True
        return False

    async def get_by_name(self, name: str) -> Pipeline | None:
        orm = await self._get_pipeline_orm(name)
        return (
            orm_to_domain_pipeline(orm, items=orm.spec_items, vik_items=orm.vik_entries)
            if orm
            else None
        )

    async def list_names(self) -> list[str]:
        result = await self.session.execute(select(PipelineORM.name))
        return list(result.scalars())

    async def _archive_instrument_embedments_before_pipeline_delete(
        self,
        *,
        pipeline_id: int,
        pipeline_name: str,
    ) -> int:
        stmt = select(SpecItemORM).where(
            SpecItemORM.pipeline_id == pipeline_id,
            SpecItemORM.section == SpecSection.INSTRUMENT_EMBEDMENT.value,
        )
        result = await self.session.execute(stmt)
        rows = list(result.scalars().all())
        for row in rows:
            self.session.add(
                InstrumentEmbedmentSavedORM(
                    source_pipeline_name=pipeline_name,
                    extra=dict(row.extra or {}),
                )
            )
        if rows:
            await self.session.flush()
        return len(rows)

    async def delete_by_name(self, pipeline_name: str) -> bool:
        pipeline = await self._get_pipeline_orm(pipeline_name)
        if pipeline is None:
            return False

        archived = await self._archive_instrument_embedments_before_pipeline_delete(
            pipeline_id=pipeline.id,
            pipeline_name=pipeline_name,
        )
        if archived:
            logger.info(
                "Instrument embedments archived before pipeline delete. name={} count={}",
                pipeline_name,
                archived,
            )

        await self.session.execute(
            delete(SpecItemORM).where(SpecItemORM.pipeline_id == pipeline.id)
        )
        await self.session.execute(
            delete(PipelineORM).where(PipelineORM.id == pipeline.id)
        )
        self._pipeline_cache[pipeline_name] = None
        await self.session.flush()
        logger.info("Pipeline deleted. name={}", pipeline_name)
        return True

    async def _get_pipeline_orm(self, pipeline_name: str) -> PipelineORM | None:
        canonical = normalize_pipeline_name(pipeline_name)
        for lookup_name in (pipeline_name, canonical):
            if lookup_name in self._pipeline_cache:
                return self._pipeline_cache[lookup_name]

        pipeline: PipelineORM | None = None
        for lookup_name in (pipeline_name, canonical):
            if not lookup_name:
                continue
            stmt = select(PipelineORM).where(PipelineORM.name == lookup_name)
            result = await self.session.execute(stmt)
            pipeline = result.scalar_one_or_none()
            if pipeline is not None:
                break

        if pipeline is None:
            normalized_target = self._normalize_pipeline_lookup(pipeline_name)
            numeric_tokens = sorted(set(re.findall(r"\d{3,}", pipeline_name or "")))
            if normalized_target:
                fallback_stmt = select(PipelineORM)
                if numeric_tokens:
                    fallback_stmt = fallback_stmt.where(
                        or_(*[PipelineORM.name.ilike(f"%{token}%") for token in numeric_tokens])
                    )
                fallback_result = await self.session.execute(fallback_stmt)
                candidates = list(fallback_result.scalars().all())
                for candidate in candidates:
                    if self._normalize_pipeline_lookup(candidate.name) == normalized_target:
                        pipeline = candidate
                        logger.warning(
                            "Pipeline lookup fallback match. requested={} matched={}",
                            pipeline_name,
                            candidate.name,
                        )
                        break
        self._pipeline_cache[pipeline_name] = pipeline
        if canonical and canonical != pipeline_name:
            self._pipeline_cache[canonical] = pipeline
        return pipeline

    @staticmethod
    def _normalize_pipeline_lookup(value: str) -> str:
        """
        Нормализация имени трубопровода для fallback-сопоставления:
        - убирает ведущий №;
        - приводит похожие кириллические/латинские символы к единому виду;
        - убирает пробелы;
        - унифицирует дефисы.
        """
        if not value:
            return ""
        text = normalize_pipeline_name(str(value)).strip().lower()
        text = re.sub(r"[\u2010-\u2015\u2212]", "-", text)
        text = text.translate(
            str.maketrans(
                {
                    "а": "a",
                    "в": "b",
                    "е": "e",
                    "к": "k",
                    "м": "m",
                    "н": "h",
                    "о": "o",
                    "р": "p",
                    "с": "c",
                    "т": "t",
                    "у": "y",
                    "х": "x",
                    "і": "i",
                    "ї": "i",
                    "ё": "e",
                }
            )
        )
        return "".join(text.split())
