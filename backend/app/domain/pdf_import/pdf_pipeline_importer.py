from typing import Callable, Any
from pathlib import Path
from time import time
from urllib.parse import quote

from loguru import logger

from backend.app.domain.parsing.drawing_4_store import get_drawing_4_store

from backend.app.application.jobs.job_service import JobService
from backend.app.domain.models.pipeline import Pipeline
from backend.app.domain.parsing.parse_pipeline_from_tables import ParsePipelineFromTables
from backend.app.domain.parsing.pipe_length_calculator import PipeLengthCalculator
from backend.app.domain.parsing.specification.spec_section_mapping_store import (
    UndefinedSpecSectionError,
)
from backend.app.infrastructure.files.pdf.pdf_table_source import PDFTableSource
from backend.app.shared.parsing_audit_logger import log_parsing_event


class PDFPipelineImporter:
    def __init__(
        self,
        repo_factory: Callable,
        job_service: JobService,
    ):
        self.repo_factory = repo_factory
        self.job_service = job_service

    async def embedment_markers_all_resolved(self, markers: list[dict[str, Any]]) -> bool:
        if not markers:
            return True
        store = get_drawing_4_store()
        async with self.repo_factory() as repo:
            for m in markers:
                pname = (m.get("pipeline_name") or "").strip()
                if not pname:
                    return False
                pid = await repo.get_id_by_name(pname)
                if pid is None:
                    return False
                gk = (m.get("embedment_group_key") or "").strip()
                tag = (m.get("instrument_tag") or "").strip()
                peers = set(m.get("peer_tags") or [])
                if isinstance(peers, list):
                    peers = {str(x).strip() for x in peers if x and str(x).strip()}
                if tag:
                    peers.add(tag)
                entry = store.resolve(tag) if tag else None
                if entry is not None:
                    peers |= {str(x).strip() for x in entry.peer_tags if x}
                ok = await repo.is_instrument_embedment_group_enriched(
                    pipeline_id=pid,
                    embedment_group_key=gk,
                    peer_tags=peers,
                )
                if not ok:
                    return False
        return True

    async def _collect_embedment_pending_markers(
        self,
        *,
        touched: dict[str, set[str]],
        pipeline_map: dict[str, Pipeline],
        blocked: set[str],
        pdf_path: Path,
        page_num: int,
    ) -> list[dict[str, Any]]:
        store = get_drawing_4_store()
        seen: set[tuple[str, str]] = set()
        out: list[dict[str, Any]] = []
        async with self.repo_factory() as repo:
            pipeline_id_cache: dict[str, int | None] = {}
            enriched_cache: dict[tuple[int, str, tuple[str, ...]], bool] = {}
            for pipeline_name, pages in touched.items():
                if pipeline_name in blocked:
                    continue
                pl = pipeline_map.get(pipeline_name)
                if pl is None:
                    continue
                page_set = {str(p).strip() for p in pages if str(p).strip()}
                for spec in pl.specifications:
                    sp = (spec.page or "").strip()
                    if sp not in page_set:
                        continue
                    for emb in getattr(spec, "instrument_embedments", []) or []:
                        path = (emb.drawing_image_path or "").strip()
                        if not path:
                            continue
                        tag = (emb.instrument_tag or "").strip()
                        gk = (emb.embedment_group_key or "").strip()
                        peers: set[str] = set()
                        entry = store.resolve(tag) if tag else None
                        if entry is not None:
                            peers = {str(x).strip() for x in entry.peer_tags if x}
                        if tag:
                            peers.add(tag)
                        if gk:
                            peers.add(gk)
                        dedup = gk or tag or (emb.name or "").strip() or "?"
                        key = (pipeline_name, dedup)
                        if key in seen:
                            continue

                        if pipeline_name not in pipeline_id_cache:
                            pipeline_id_cache[pipeline_name] = await repo.get_id_by_name(
                                pipeline_name
                            )
                        pid = pipeline_id_cache[pipeline_name]
                        if pid is None:
                            continue

                        peers_tuple = tuple(sorted(peers))
                        cache_key = (pid, gk, peers_tuple)
                        if cache_key not in enriched_cache:
                            enriched_cache[cache_key] = (
                                await repo.is_instrument_embedment_group_enriched(
                                    pipeline_id=pid,
                                    embedment_group_key=gk,
                                    peer_tags=peers,
                                )
                            )
                        if enriched_cache[cache_key]:
                            continue

                        seen.add(key)
                        crop_url = f"/pipelines/embedment-crop-image?path={quote(path, safe='')}"
                        out.append(
                            {
                                "pipeline_name": pipeline_name,
                                "instrument_tag": tag,
                                "embedment_group_key": gk,
                                "drawing_image_path": path,
                                "crop_image_url": crop_url,
                                "page": str(page_num),
                                "spec_page": sp,
                                "full_name": emb.name,
                                "peer_tags": list(peers_tuple),
                            }
                        )
        return out

    async def run(self, pdf_path: Path, job_id: int, user_log_key: str | None = None):
        await self.run_from_page(pdf_path, job_id, start_page=1, user_log_key=user_log_key)

    async def run_from_page(
        self,
        pdf_path: Path,
        job_id: int,
        start_page: int = 1,
        blocked_pipelines: set[str] | None = None,
        user_log_key: str | None = None,
    ) -> dict[str, Any]:
        start_time = time()
        last_page_processed = 0
        logger.info("Start PDF import. job_id={} pdf_path={} start_page={}", job_id, pdf_path, start_page)
        log_parsing_event(
            job_id=job_id,
            user_log_key=user_log_key,
            source_type="pdf",
            source_file=str(pdf_path),
            parser="PDFPipelineImporter",
            entity="file",
            entity_id=pdf_path.name,
            field="import_start",
            value=start_page,
            origin={"start_page": start_page},
        )
        blocked = blocked_pipelines if blocked_pipelines is not None else set()
        file_invalid_records: list[dict[str, Any]] = []
        blocked_in_file: set[str] = set()

        source = PDFTableSource(
            pdf_path=pdf_path,
            job_id=job_id,
            job_service=self.job_service,
        )
        # ParsePipelineFromTables принимает job_id и source как опциональные аргументы,
        # но здесь создаётся без них для совместимости с тестовыми double-классами.
        parser = ParsePipelineFromTables()
        # В реальном импорте после создания можем передать фактический контекст,
        # если у parser есть соответствующий метод (у тестовых double его может не быть).
        if hasattr(parser, "set_context"):
            parser.set_context(
                job_id=job_id, source=str(pdf_path), user_log_key=user_log_key
            )

        async for page_num, page_tables in source.iter_tables_by_page(start_page=start_page):
            last_page_processed = page_num
            try:
                # Парсим только текущую страницу, но состояние парсера сохраняем между итерациями.
                touched = parser.process_tables(page_tables)
            except UndefinedSpecSectionError as exc:
                log_parsing_event(
                    job_id=job_id,
                    user_log_key=user_log_key,
                    source_type="pdf",
                    source_file=str(pdf_path),
                    parser="PDFPipelineImporter",
                    entity="file",
                    entity_id=pdf_path.name,
                    field="section_undefined",
                    value=exc.item_name,
                    status="warning",
                    note=str(exc),
                    origin={"page": str(page_num)},
                )
                file_invalid_records.append(
                    {
                        "kind": "section_undefined",
                        "source": str(pdf_path),
                        "pipeline": None,
                        "page": str(page_num),
                        "section": "not_defined",
                        "item_name": exc.item_name,
                        "full_name": exc.full_name,
                        "row": exc.row,
                        "error": str(exc),
                    }
                )
                return {
                    "needs_user_input": True,
                    "undefined_names": [exc.item_name],
                    "undefined_full_names": {exc.item_name: exc.full_name},
                    "invalid_records": file_invalid_records,
                    "blocked_pipelines": sorted(blocked_in_file),
                    "pages_in_file": last_page_processed,
                    "spec_items_in_file": parser.spec_items_count(),
                    "all_pipelines_in_file": list(getattr(parser, "pipeline_names", lambda: [])() or []),
                    "valid_pipelines_in_file": [
                        name for name in (getattr(parser, "pipeline_names", lambda: [])() or [])
                        if name not in blocked
                    ],
                }
            except Exception as exc:  # noqa: BLE001 - не прерываем пакет при ошибках на странице
                log_parsing_event(
                    job_id=job_id,
                    user_log_key=user_log_key,
                    source_type="pdf",
                    source_file=str(pdf_path),
                    parser="PDFPipelineImporter",
                    entity="file",
                    entity_id=pdf_path.name,
                    field="page_error",
                    value=f"page={page_num}",
                    status="warning",
                    note=str(exc),
                    origin={"page": str(page_num)},
                )
                file_invalid_records.append(
                    {
                        "kind": "error",
                        "source": str(pdf_path),
                        "pipeline": None,
                        "page": str(page_num),
                        "section": "process_tables",
                        "row": [],
                        "error": str(exc),
                    }
                )
                logger.exception(
                    "Page parsing failed. job_id={} file={} page={}",
                    job_id,
                    pdf_path,
                    page_num,
                )
                continue

            pop_parser_warnings = getattr(parser, "pop_warnings", None)
            parser_warnings = pop_parser_warnings() if callable(pop_parser_warnings) else []
            newly_blocked: set[str] = set()
            for w in parser_warnings or []:
                pipeline_name = (w.get("pipeline") or "").strip()
                event = {
                    "kind": w.get("kind") or "warning",
                    "source": str(pdf_path),
                    "pipeline": pipeline_name or None,
                    "page": str(w.get("page") or page_num),
                    "section": w.get("section"),
                    "item_name": w.get("item_name"),
                    "row": w.get("row"),
                    "error": w.get("error"),
                }
                file_invalid_records.append(event)
                if pipeline_name:
                    newly_blocked.add(pipeline_name)

            if newly_blocked:
                blocked.update(newly_blocked)
                blocked_in_file.update(newly_blocked)
                for pipeline_name in newly_blocked:
                    async with self.repo_factory() as repo:
                        await repo.delete_by_name(pipeline_name)
                    logger.warning(
                        "Pipeline moved to blocked set due to warnings. pipeline={} file={}",
                        pipeline_name,
                        pdf_path,
                    )

            pipelines = parser.snapshot(touched.keys())
            spec_items = parser.spec_items_count()
            pipeline_map = {p.name: p for p in pipelines}

            for pipeline_name, pages in touched.items():
                if pipeline_name in blocked:
                    continue

                pipeline = pipeline_map.get(pipeline_name)
                if pipeline is None:
                    continue

                try:
                    async with self.repo_factory() as repo:
                        target_pipeline = pipeline
                        if start_page > 1:
                            # При продолжении после падения объединяем новые данные
                            # с уже сохранённым состоянием трубопровода.
                            existing_pipeline = await repo.get_by_name(pipeline.name)
                            if existing_pipeline is not None:
                                target_pipeline = self._merge_pipeline(existing_pipeline, pipeline)
                        await repo.save_or_update(
                            target_pipeline,
                            replace_pages=pages,
                            job_id=job_id,
                        )
                except Exception as exc:  # noqa: BLE001 - блокируем только конкретный трубопровод
                    blocked.add(pipeline_name)
                    blocked_in_file.add(pipeline_name)
                    file_invalid_records.append(
                        {
                            "kind": "error",
                            "source": str(pdf_path),
                            "pipeline": pipeline_name,
                            "page": ",".join(sorted(p for p in pages if p)),
                            "section": "save_or_update",
                            "row": [],
                            "error": str(exc),
                        }
                    )
                    log_parsing_event(
                        job_id=job_id,
                        user_log_key=user_log_key,
                        source_type="pdf",
                        source_file=str(pdf_path),
                        parser="PDFPipelineImporter",
                        entity="pipeline",
                        entity_id=pipeline_name,
                        field="save_or_update",
                        value="failed",
                        status="warning",
                        note=str(exc),
                        origin={"pages": sorted(p for p in pages if p)},
                    )
                    async with self.repo_factory() as repo:
                        await repo.delete_by_name(pipeline_name)
                    logger.exception(
                        "Pipeline save failed and pipeline blocked. job_id={} file={} pipeline={}",
                        job_id,
                        pdf_path,
                        pipeline_name,
                    )

            embedment_pending = await self._collect_embedment_pending_markers(
                touched=touched,
                pipeline_map=pipeline_map,
                blocked=blocked,
                pdf_path=pdf_path,
                page_num=page_num,
            )
            if embedment_pending:
                elapsed = time() - start_time
                await self.job_service.update_progress(
                    job_id=job_id,
                    extra={
                        "pages": page_num,
                        "pipelines": max(parser.pipelines_count() - len(blocked), 0),
                        "spec_items": spec_items,
                        "duration_sec": elapsed,
                        "waiting_embedment_input": True,
                        "embedment_pending": embedment_pending,
                        "embedment_pending_total": len(embedment_pending),
                    },
                )
                logger.info(
                    "PDF import paused for embedment input. job_id={} pending={}",
                    job_id,
                    len(embedment_pending),
                )
                return {
                    "needs_embedment_input": True,
                    "embedment_pending": embedment_pending,
                    "invalid_records": file_invalid_records,
                    "blocked_pipelines": sorted(blocked_in_file),
                    "pages_in_file": last_page_processed,
                    "spec_items_in_file": parser.spec_items_count(),
                    "all_pipelines_in_file": list(
                        getattr(parser, "pipeline_names", lambda: [])() or []
                    ),
                    "valid_pipelines_in_file": [
                        name
                        for name in (getattr(parser, "pipeline_names", lambda: [])() or [])
                        if name not in blocked
                    ],
                }

            elapsed = time() - start_time
            await self.job_service.update_progress(
                job_id=job_id,
                extra={
                    "pages": page_num,
                    "pipelines": max(parser.pipelines_count() - len(blocked), 0),
                    "spec_items": spec_items,
                    "duration_sec": elapsed,
                    "waiting_user_input": False,
                    "waiting_embedment_input": False,
                },
            )
            logger.debug(
                "Page processed. job_id={} page={} tables={} pipelines={} spec_items={} duration_sec={:.2f}",
                job_id,
                page_num,
                len(page_tables),
                parser.pipelines_count(),
                spec_items,
                elapsed,
            )
            if page_num % 10 == 0:
                logger.info(
                    "PDF import progress. job_id={} page={} pipelines={} spec_items={} duration_sec={:.2f}",
                    job_id,
                    page_num,
                    parser.pipelines_count(),
                    spec_items,
                    elapsed,
                )

        # Если у трубопровода в файле не найдено ни одной позиции спецификации,
        # считаем такой трубопровод некорректным и исключаем из БД.
        all_pipeline_names = list(getattr(parser, "pipeline_names", lambda: [])() or [])
        all_pipelines = parser.snapshot(all_pipeline_names)
        no_specs_pipelines = [
            p.name
            for p in all_pipelines
            if p.name not in blocked and self._count_pipeline_spec_items(p) == 0
        ]
        if no_specs_pipelines:
            for pipeline_name in no_specs_pipelines:
                blocked.add(pipeline_name)
                blocked_in_file.add(pipeline_name)
                file_invalid_records.append(
                    {
                        "kind": "error",
                        "source": str(pdf_path),
                        "pipeline": pipeline_name,
                        "page": None,
                        "section": "specification",
                        "row": [],
                        "error": "no_specifications_in_file",
                    }
                )
                async with self.repo_factory() as repo:
                    await repo.delete_by_name(pipeline_name)
                logger.warning(
                    "Pipeline blocked: no specifications found in file. pipeline={} file={}",
                    pipeline_name,
                    pdf_path,
                )

        # Финальный апдейт с накопленными предупреждениями по файлу.
        # parser может быть подменён тестовым double-объектом, который не имеет методов
        # warnings/pipeline_names. В таком случае пропускаем дополнительный апдейт прогресса,
        # чтобы не ломать ожидания тестов.
        if hasattr(parser, "warnings") or hasattr(parser, "pipeline_names"):
            warnings = [x for x in file_invalid_records if x.get("kind") == "warning"]
            trimmed = warnings[:50]
            pipeline_names = [
                name for name in (getattr(parser, "pipeline_names", lambda: [])() or [])
                if name not in blocked
            ]
            pipelines_count = len(pipeline_names)
            spec_items_total = parser.spec_items_count()
            has_any_invalid = bool(file_invalid_records)

            # Важный кейс: импорт формально завершился, но ничего не извлечено.
            # Помечаем файл как проблемный, чтобы фронт и логи показывали явную причину.
            if pipelines_count == 0 and spec_items_total == 0 and not has_any_invalid:
                file_invalid_records.append(
                    {
                        "kind": "error",
                        "source": str(pdf_path),
                        "pipeline": None,
                        "page": None,
                        "section": "file_import",
                        "row": [],
                        "error": "no_data_extracted_from_pdf",
                    }
                )
                logger.warning(
                    "PDF import completed with no extracted data. job_id={} file={}",
                    job_id,
                    pdf_path,
                )

            extra: dict = {
                "pipelines": pipelines_count,
                "spec_items": spec_items_total,
                "pipelines_in_file": pipeline_names,
            }
            if trimmed:
                extra["warnings"] = trimmed
                extra["warnings_total"] = len(warnings)

            await self.job_service.update_progress(job_id=job_id, extra=extra)

            logger.info(
                "Import completed. job_id={} pipelines={} spec_items={} warnings={} pipeline_names={}",
                job_id,
                pipelines_count,
                spec_items_total,
                len(warnings),
                pipeline_names,
            )
            log_parsing_event(
                job_id=job_id,
                user_log_key=user_log_key,
                source_type="pdf",
                source_file=str(pdf_path),
                parser="PDFPipelineImporter",
                entity="file",
                entity_id=pdf_path.name,
                field="import_completed",
                value={
                    "pipelines": pipelines_count,
                    "spec_items": spec_items_total,
                    "warnings": len(warnings),
                },
                origin={"blocked_pipelines": sorted(blocked_in_file)},
                status=(
                    "warning"
                    if pipelines_count == 0 and spec_items_total == 0
                    else "parsed"
                ),
                note=(
                    "no_data_extracted_from_pdf"
                    if pipelines_count == 0 and spec_items_total == 0
                    else None
                ),
            )

        return {
            "invalid_records": file_invalid_records,
            "blocked_pipelines": sorted(blocked_in_file),
            "pages_in_file": last_page_processed,
            "spec_items_in_file": parser.spec_items_count(),
            "all_pipelines_in_file": list(getattr(parser, "pipeline_names", lambda: [])() or []),
            "valid_pipelines_in_file": [
                name for name in (getattr(parser, "pipeline_names", lambda: [])() or [])
                if name not in blocked
            ],
        }

    @staticmethod
    def _merge_pipeline(existing: Pipeline, incoming: Pipeline) -> Pipeline:
        # Приоритет за incoming, но пустые поля дозаполняем из existing.
        merged = Pipeline(
            name=incoming.name,
            medium=incoming.medium or existing.medium,
            mounting_scheme=incoming.mounting_scheme or existing.mounting_scheme,
            flow_direction=incoming.flow_direction,
            parameters=incoming.parameters,
            specifications=[*existing.specifications, *incoming.specifications],
            pipelines_len={},
            year=incoming.year if incoming.year is not None else existing.year,
        )

        if not merged.flow_direction.start:
            merged.flow_direction.start = existing.flow_direction.start
        if not merged.flow_direction.end:
            merged.flow_direction.end = existing.flow_direction.end

        for attr in (
            "gost_category",
            "working_pressure",
            "working_temperature",
            "calculated_pressure",
            "calculated_temperature",
            "strength_test_pressure",
            "strength_test_method",
            "strength_test_duration",
            "strength_test_result",
            "material",
            "installation_date",
            "welding_type",
            "welding_material",
        ):
            if not getattr(merged.parameters, attr):
                setattr(merged.parameters, attr, getattr(existing.parameters, attr))

        length_calc = PipeLengthCalculator()
        for spec in merged.specifications:
            length_calc.accumulate(merged.name, spec)
        merged.pipelines_len = length_calc.finalize(merged.name)

        return merged

    @staticmethod
    def _count_pipeline_spec_items(pipeline: Pipeline) -> int:
        total = 0
        for spec in pipeline.specifications:
            total += (
                len(spec.pipeline_armature)
                + len(spec.instrument_embedments)
                + len(spec.pipes)
                + len(spec.connection_parts)
                + len(spec.flanges)
                + len(spec.supports)
            )
        return total

