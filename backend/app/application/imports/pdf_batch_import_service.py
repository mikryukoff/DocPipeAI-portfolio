import asyncio
from pathlib import Path
import re
from time import monotonic, time

from loguru import logger

from backend.app.application.jobs.job_service import JobService
from backend.app.domain.pdf_import.pdf_pipeline_importer import PDFPipelineImporter
from backend.app.domain.parsing.specification.spec_section_mapping_store import (
    SpecSectionMappingStore,
)
from backend.app.infrastructure.db.models.job import JobORM
from backend.app.shared.invalid_pipeline_logger import log_invalid_pipeline_event
from backend.app.shared.job_workspace_cleanup import maybe_delete_job_workspace


class PdfBatchImportService:
    _WAIT_PROGRESS_INTERVAL_SEC = 3.0
    _DOT_COMMA_NUMERIC_STEM_RE = re.compile(r"^\d+(?:[.,]\d+)+$")

    def __init__(
        self,
        job_service: JobService,
        importer: PDFPipelineImporter,
    ):
        self.job_service = job_service
        self.importer = importer

    async def start_batch_import(
        self,
        job_id: int,
        pdf_paths: list[Path],
        user_log_key: str,
        *,
        job_workspace: str | None = None,
    ) -> JobORM:
        if not pdf_paths:
            raise ValueError("no_pdf_files")

        pdf_paths = sorted(pdf_paths, key=self._sort_key)

        logger.info(
            "PDF batch import scheduled. job_id={} files_total={} user_log_key={}",
            job_id,
            len(pdf_paths),
            user_log_key,
        )

        task = asyncio.create_task(
            self._run(
                job_id,
                pdf_paths,
                user_log_key,
                job_workspace=job_workspace,
            ),
            name=f"pdf_batch_import_{job_id}",
        )
        self._attach_task_logger(task, task_name="pdf_batch_import", job_id=job_id)
        return await self.job_service.get_status(job_id)

    @staticmethod
    def _numeric_group_key(filepath: Path | str) -> tuple[int, ...] | None:
        """
        Ключ группы PDF в пачке по числовому префиксу имени.
        - 222.1 / 222,2 → (222,) — один трубопровод, разные листы
        - 1.1 → (1,), 1.1.1 → (1, 1) — разные группы
        - 1-2 / 1,2 / 1 2 / 1_2 → (1,) — первое число
        """
        stem = Path(filepath).stem.strip()
        if not stem:
            return None
        if PdfBatchImportService._DOT_COMMA_NUMERIC_STEM_RE.fullmatch(stem):
            parts = tuple(int(part) for part in re.split(r"[.,]", stem))
            return parts[:-1] if len(parts) > 1 else parts
        nums = re.findall(r"\d+", stem)
        if not nums:
            return None
        return (int(nums[0]),)

    @staticmethod
    def _first_numeric_prefix_int(filepath: Path | str) -> int | None:
        """Первое число ключа группы; без цифр — None."""
        key = PdfBatchImportService._numeric_group_key(filepath)
        return key[0] if key else None

    @staticmethod
    def _format_numeric_group_key(key: tuple[int, ...]) -> str:
        return ".".join(str(part) for part in key)

    @staticmethod
    def _sort_key(filepath):
        stem = Path(filepath).stem
        stem_lower = stem.lower()
        if PdfBatchImportService._DOT_COMMA_NUMERIC_STEM_RE.fullmatch(stem):
            parts = tuple(int(part) for part in re.split(r"[.,]", stem))
            return (0, parts)
        nums = re.findall(r"\d+", stem)
        if not nums:
            # Ненумерованные файлы отправляем в хвост, но сортируем стабильно по имени.
            return (1, stem_lower)
        sub = int(nums[1]) if len(nums) > 1 else 0
        # Поддерживаем форматы: 1-2, 1.2, 1,2, 1 2, 1_2.
        return (0, (int(nums[0]), sub), stem_lower)

    async def _run(
        self,
        job_id: int,
        pdf_paths: list[Path],
        user_log_key: str,
        *,
        job_workspace: str | None = None,
    ):
        started_at = time()
        paused_total_sec = 0.0
        total_pages = 0
        total_spec_items = 0
        discovered_pipelines: set[str] = set()
        aggregated_warnings: list[dict] = []
        total_warnings = 0
        blocked_pipelines: set[str] = set()
        aggregated_invalid_records: list[dict] = []
        invalid_records_total = 0
        undefined_spec_names: set[str] = set()
        undefined_spec_sources: dict[str, str] = {}
        undefined_spec_full_names: dict[str, str] = {}
        pipeline_prefixes: dict[str, set[tuple[int, ...]]] = {}
        pipeline_first_source: dict[str, str] = {}
        cross_file_duplicate_handled: set[str] = set()
        cross_file_duplicate_sources_logged: dict[str, set[str]] = {}
        prefix_canonical_pipelines: dict[tuple[int, ...], frozenset[str]] = {}
        prefix_first_source: dict[tuple[int, ...], str] = {}
        prefix_mismatch_handled: set[tuple[int, ...]] = set()
        prefix_mismatch_sources_logged: dict[tuple[int, ...], set[str]] = {}

        try:
            await self.job_service.start_processing(job_id)
            for idx, pdf_path in enumerate(pdf_paths, start=1):
                logger.info(
                    "PDF file import started. job_id={} index={} of {} file={}",
                    job_id,
                    idx,
                    len(pdf_paths),
                    pdf_path.name,
                )
                while True:
                    try:
                        file_result = await self.importer.run_from_page(
                            pdf_path,
                            job_id,
                            start_page=1,
                            blocked_pipelines=blocked_pipelines,
                            user_log_key=user_log_key,
                        )
                    except Exception as exc:  # noqa: BLE001 - не останавливаем пакет из-за одного файла
                        exc_type = type(exc).__name__
                        exc_text = str(exc).strip() or "no_exception_message"
                        logger.exception(
                            "PDF file import failed, continue with next file. job_id={} file={} error_type={} error={}",
                            job_id,
                            pdf_path.name,
                            exc_type,
                            exc_text,
                        )
                        file_result = {
                            "invalid_records": [
                                {
                                    "kind": "error",
                                    "source": pdf_path.name,
                                    "pipeline": None,
                                    "page": None,
                                    "section": "file_import",
                                    "row": [],
                                    "error": exc_text,
                                    "error_type": exc_type,
                                }
                            ],
                            "blocked_pipelines": [],
                            "valid_pipelines_in_file": [],
                        }

                    if file_result.get("needs_embedment_input"):
                        markers = list(file_result.get("embedment_pending") or [])
                        frozen_duration = self._elapsed_seconds(
                            started_at, paused_total_sec
                        )
                        waited_sec = await self._wait_for_embedment_input(
                            job_id=job_id,
                            pdf_path=pdf_path,
                            file_index=idx,
                            files_total=len(pdf_paths),
                            frozen_duration=frozen_duration,
                            markers=markers,
                        )
                        paused_total_sec += waited_sec
                        continue

                    if file_result.get("needs_user_input"):
                        pending = list(file_result.get("undefined_names") or [])
                        pending_full_names = dict(file_result.get("undefined_full_names") or {})
                        frozen_duration = self._elapsed_seconds(started_at, paused_total_sec)
                        waited_sec = await self._wait_for_user_section_mapping(
                            job_id=job_id,
                            pdf_path=pdf_path,
                            file_index=idx,
                            files_total=len(pdf_paths),
                            frozen_duration=frozen_duration,
                            pending_names=pending,
                            pending_full_names=pending_full_names,
                        )
                        paused_total_sec += waited_sec
                        # После определения разделов перезапускаем тот же файл.
                        continue
                    break
                file_invalid_records = list(file_result.get("invalid_records") or [])
                file_blocked = set(file_result.get("blocked_pipelines") or [])
                blocked_pipelines.update(str(p) for p in file_blocked if p)

                if file_invalid_records:
                    invalid_records_total += len(file_invalid_records)
                    for record in file_invalid_records:
                        if record.get("kind") == "section_undefined" and record.get("item_name"):
                            item_name = str(record["item_name"])
                            undefined_spec_names.add(item_name)
                            full_name = str(record.get("full_name") or "").strip()
                            if full_name:
                                undefined_spec_full_names.setdefault(item_name, full_name)
                            source_path = Path(str(record.get("source") or pdf_path.name)).name
                            undefined_spec_sources.setdefault(item_name, source_path)
                    for record in file_invalid_records:
                        log_invalid_pipeline_event(
                            record, user_log_key=user_log_key
                        )
                    remaining_slots = max(50 - len(aggregated_invalid_records), 0)
                    if remaining_slots > 0:
                        aggregated_invalid_records.extend(file_invalid_records[:remaining_slots])

                # Берём статистику только из результата текущего файла.
                file_pages = int(file_result.get("pages_in_file") or 0)
                file_spec_items = int(file_result.get("spec_items_in_file") or 0)
                file_all_pipeline_names = list(file_result.get("all_pipelines_in_file") or [])
                file_warnings = [x for x in file_invalid_records if x.get("kind") == "warning"]
                file_warnings_total = len(file_warnings)

                total_pages += file_pages
                total_spec_items += file_spec_items

                # Множество всех найденных трубопроводов по всей пачке файлов (включая те,
                # которые позже могли стать проблемными и быть исключены из БД).
                try:
                    discovered_pipelines.update(str(name) for name in file_all_pipeline_names)
                except TypeError:
                    # на случай, если pipelines_in_file пришёл неитерируемым — игнорируем.
                    pass

                added_invalid = await self._handle_cross_file_pipeline_prefix_duplicates(
                    pdf_path=pdf_path,
                    file_all_pipeline_names=file_all_pipeline_names,
                    blocked_pipelines=blocked_pipelines,
                    pipeline_prefixes=pipeline_prefixes,
                    pipeline_first_source=pipeline_first_source,
                    cross_file_duplicate_handled=cross_file_duplicate_handled,
                    cross_file_duplicate_sources_logged=cross_file_duplicate_sources_logged,
                    aggregated_invalid_records=aggregated_invalid_records,
                    user_log_key=user_log_key,
                )
                if added_invalid:
                    invalid_records_total += added_invalid

                added_invalid = await self._handle_cross_file_same_prefix_pipeline_mismatch(
                    pdf_path=pdf_path,
                    file_all_pipeline_names=file_all_pipeline_names,
                    blocked_pipelines=blocked_pipelines,
                    prefix_canonical_pipelines=prefix_canonical_pipelines,
                    prefix_first_source=prefix_first_source,
                    prefix_mismatch_handled=prefix_mismatch_handled,
                    prefix_mismatch_sources_logged=prefix_mismatch_sources_logged,
                    aggregated_invalid_records=aggregated_invalid_records,
                    user_log_key=user_log_key,
                )
                if added_invalid:
                    invalid_records_total += added_invalid

                valid_pipelines_total = len(discovered_pipelines - blocked_pipelines)

                # Нефатальные предупреждения по всем файлам пачки.
                if isinstance(file_warnings, list) and file_warnings:
                    # накапливаем до 50 элементов для отображения на фронте
                    remaining_slots = max(50 - len(aggregated_warnings), 0)
                    if remaining_slots > 0:
                        aggregated_warnings.extend(file_warnings[:remaining_slots])
                    total_warnings += file_warnings_total

                progress = int(idx / len(pdf_paths) * 100)
                await self.job_service.update_progress(
                    job_id,
                    progress=progress,
                    extra={
                        # для обратной совместимости сохраняем старые поля
                        "pages": total_pages,
                        "pipelines": valid_pipelines_total,
                        "spec_items": total_spec_items,
                        # новые агрегированные поля по всей пачке
                        "pipelines_total": valid_pipelines_total,
                        "pipelines_found_total": len(discovered_pipelines),
                        "spec_items_total": total_spec_items,
                        "files_total": len(pdf_paths),
                         # агрегированные предупреждения по всей пачке
                        "warnings": aggregated_warnings if aggregated_warnings else None,
                        "warnings_total": total_warnings,
                        "blocked_pipelines": sorted(blocked_pipelines),
                        "blocked_pipelines_total": len(blocked_pipelines),
                        "invalid_rows": aggregated_invalid_records if aggregated_invalid_records else None,
                        "invalid_rows_total": invalid_records_total,
                        "undefined_spec_names": sorted(undefined_spec_names),
                        "undefined_spec_names_total": len(undefined_spec_names),
                        "undefined_spec_sources": {
                            name: undefined_spec_sources[name]
                            for name in sorted(undefined_spec_names)
                            if name in undefined_spec_sources
                        },
                        "undefined_spec_full_names": {
                            name: undefined_spec_full_names[name]
                            for name in sorted(undefined_spec_names)
                            if name in undefined_spec_full_names
                        },
                        "waiting_user_input": False,
                        "waiting_embedment_input": False,
                        "embedment_pending": None,
                        "embedment_pending_total": 0,
                        "duration_sec": self._elapsed_seconds(started_at, paused_total_sec),
                        "files_processed": idx,
                        "current_file": pdf_path.name,
                    },
                )

            has_issues = bool(blocked_pipelines) or total_warnings > 0 or invalid_records_total > 0
            final_progress = 99 if has_issues else 100
            await self.job_service.finish(job_id, progress=final_progress)
        except Exception as exc:
            logger.exception("PDF batch import crashed. job_id={}", job_id)
            await self.job_service.fail(job_id, str(exc))
        finally:
            maybe_delete_job_workspace(job_workspace=job_workspace, job_id=job_id)

    @staticmethod
    def _attach_task_logger(task: asyncio.Task, *, task_name: str, job_id: int) -> None:
        def _on_done(done_task: asyncio.Task) -> None:
            try:
                done_task.result()
            except asyncio.CancelledError:
                logger.warning(
                    "Background task cancelled. task_name={} job_id={}",
                    task_name,
                    job_id,
                )
            except Exception:
                logger.exception(
                    "Background task failed unexpectedly. task_name={} job_id={}",
                    task_name,
                    job_id,
                )

        task.add_done_callback(_on_done)

    async def _handle_cross_file_pipeline_prefix_duplicates(
        self,
        *,
        pdf_path: Path,
        file_all_pipeline_names: list[str],
        blocked_pipelines: set[str],
        pipeline_prefixes: dict[str, set[tuple[int, ...]]],
        pipeline_first_source: dict[str, str],
        cross_file_duplicate_handled: set[str],
        cross_file_duplicate_sources_logged: dict[str, set[str]],
        aggregated_invalid_records: list[dict],
        user_log_key: str,
    ) -> int:
        """
        Одна линия в PDF с разным первым числом в имени файла (в пределах job) — блок, удаление из БД, invalid_rows.
        Для последующих файлов пачки с той же уже отклонённой линией — ещё одна запись invalid_rows на файл.
        Возвращает приращение invalid_records_total (число залогированных записей).
        """
        pref_cur = self._numeric_group_key(pdf_path)
        cur_name = pdf_path.name
        invalid_delta = 0

        for raw_name in file_all_pipeline_names:
            name = str(raw_name).strip()
            if not name:
                continue
            if name in cross_file_duplicate_handled:
                logged = cross_file_duplicate_sources_logged.setdefault(name, set())
                if cur_name in logged:
                    continue
                logged.add(cur_name)
                msg = (
                    f"cross_file_duplicate: линия «{name}» в той же пачке уже отклонена из-за разных "
                    f"первых чисел в имени PDF; этот файл также содержит эту линию."
                )
                rec = {
                    "kind": "error",
                    "source": cur_name,
                    "pipeline": name,
                    "page": None,
                    "section": "cross_file_duplicate",
                    "row": [],
                    "error": msg,
                }
                log_invalid_pipeline_event(rec, user_log_key=user_log_key)
                invalid_delta += 1
                if len(aggregated_invalid_records) < 50:
                    aggregated_invalid_records.append(rec)
                continue

            if name in blocked_pipelines:
                continue

            if pref_cur is None:
                continue

            prefixes = pipeline_prefixes.setdefault(name, set())
            if pref_cur in prefixes:
                continue
            if not prefixes:
                prefixes.add(pref_cur)
                pipeline_first_source[name] = cur_name
                continue

            first_file = pipeline_first_source.get(name, "")
            old_sorted = sorted(prefixes)
            cross_file_duplicate_handled.add(name)
            blocked_pipelines.add(name)

            logger.warning(
                "Cross-file duplicate pipeline prefix in batch. pipeline={} first_files_prefixes={} "
                "new_prefix={} new_file={} first_file={}",
                name,
                old_sorted,
                pref_cur,
                cur_name,
                first_file,
            )

            try:
                async with self.importer.repo_factory() as repo:
                    await repo.delete_by_name(name)
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "delete_by_name failed after cross-file duplicate. pipeline={} file={} error={}",
                    name,
                    cur_name,
                    exc,
                )

            old_keys = [self._format_numeric_group_key(p) for p in old_sorted]
            msg = (
                f"cross_file_duplicate: линия «{name}» встречается в PDF с разным числовым префиксом в имени: "
                f"префиксы {old_keys} (файл «{first_file}») и "
                f"{self._format_numeric_group_key(pref_cur)} (файл «{cur_name}»)"
            )
            rec_first = {
                "kind": "error",
                "source": first_file,
                "pipeline": name,
                "page": None,
                "section": "cross_file_duplicate",
                "row": [],
                "error": msg,
            }
            rec_cur = {
                "kind": "error",
                "source": cur_name,
                "pipeline": name,
                "page": None,
                "section": "cross_file_duplicate",
                "row": [],
                "error": msg,
            }
            new_recs = [rec_first, rec_cur]
            _logged = cross_file_duplicate_sources_logged.setdefault(name, set())
            for _src in (first_file, cur_name):
                if _src:
                    _logged.add(_src)
            for rec in new_recs:
                log_invalid_pipeline_event(rec, user_log_key=user_log_key)
                invalid_delta += 1
                if len(aggregated_invalid_records) < 50:
                    aggregated_invalid_records.append(rec)

        return invalid_delta

    @staticmethod
    def _pipeline_names_frozen(names: list[str]) -> frozenset[str]:
        return frozenset(str(raw).strip() for raw in names if str(raw).strip())

    @staticmethod
    def _format_pipeline_set(names: frozenset[str]) -> str:
        return ", ".join(sorted(names))

    async def _handle_cross_file_same_prefix_pipeline_mismatch(
        self,
        *,
        pdf_path: Path,
        file_all_pipeline_names: list[str],
        blocked_pipelines: set[str],
        prefix_canonical_pipelines: dict[tuple[int, ...], frozenset[str]],
        prefix_first_source: dict[tuple[int, ...], str],
        prefix_mismatch_handled: set[tuple[int, ...]],
        prefix_mismatch_sources_logged: dict[tuple[int, ...], set[str]],
        aggregated_invalid_records: list[dict],
        user_log_key: str,
    ) -> int:
        """
        PDF с одинаковым первым числом в имени (в пределах job) должны содержать одну и ту же линию.
        Разные линии при одном префиксе — блок, удаление из БД, invalid_rows.
        """
        pref_cur = self._numeric_group_key(pdf_path)
        pref_label = self._format_numeric_group_key(pref_cur) if pref_cur else ""
        cur_name = pdf_path.name
        names_cur = self._pipeline_names_frozen(file_all_pipeline_names)
        invalid_delta = 0

        if pref_cur is None or not names_cur:
            return 0

        if pref_cur in prefix_mismatch_handled:
            logged = prefix_mismatch_sources_logged.setdefault(pref_cur, set())
            if cur_name in logged:
                return 0
            logged.add(cur_name)
            msg = (
                f"cross_file_prefix_mismatch: для PDF с числовым префиксом {pref_label} в той же пачке уже "
                f"зафиксировано несовпадение линий; этот файл также относится к этой группе."
            )
            rec = {
                "kind": "error",
                "source": cur_name,
                "pipeline": self._format_pipeline_set(names_cur) or None,
                "page": None,
                "section": "cross_file_prefix_mismatch",
                "row": [],
                "error": msg,
            }
            log_invalid_pipeline_event(rec, user_log_key=user_log_key)
            invalid_delta += 1
            if len(aggregated_invalid_records) < 50:
                aggregated_invalid_records.append(rec)
            return invalid_delta

        canonical = prefix_canonical_pipelines.get(pref_cur)
        if canonical is None:
            prefix_canonical_pipelines[pref_cur] = names_cur
            prefix_first_source[pref_cur] = cur_name
            return 0

        if names_cur == canonical:
            return 0

        first_file = prefix_first_source.get(pref_cur, "")
        prefix_mismatch_handled.add(pref_cur)
        all_names = set(canonical) | set(names_cur)
        blocked_pipelines.update(all_names)

        logger.warning(
            "Cross-file pipeline mismatch for same filename prefix in batch. prefix={} "
            "canonical_pipelines={} new_pipelines={} first_file={} new_file={}",
            pref_cur,
            sorted(canonical),
            sorted(names_cur),
            first_file,
            cur_name,
        )

        try:
            async with self.importer.repo_factory() as repo:
                for pname in sorted(all_names):
                    await repo.delete_by_name(pname)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "delete_by_name failed after same-prefix pipeline mismatch. pipelines={} file={} error={}",
                sorted(all_names),
                cur_name,
                exc,
            )

        canon_str = self._format_pipeline_set(canonical)
        names_str = self._format_pipeline_set(names_cur)
        msg = (
            f"cross_file_prefix_mismatch: для PDF с одинаковым числовым префиксом в имени ({pref_label}) "
            f"ожидается одна линия, но в файле «{first_file}» — «{canon_str}», "
            f"в файле «{cur_name}» — «{names_str}»"
        )
        pipeline_field = self._format_pipeline_set(frozenset(all_names)) or None
        rec_first = {
            "kind": "error",
            "source": first_file,
            "pipeline": pipeline_field,
            "page": None,
            "section": "cross_file_prefix_mismatch",
            "row": [],
            "error": msg,
        }
        rec_cur = {
            "kind": "error",
            "source": cur_name,
            "pipeline": pipeline_field,
            "page": None,
            "section": "cross_file_prefix_mismatch",
            "row": [],
            "error": msg,
        }
        _logged = prefix_mismatch_sources_logged.setdefault(pref_cur, set())
        for _src in (first_file, cur_name):
            if _src:
                _logged.add(_src)
        for rec in (rec_first, rec_cur):
            log_invalid_pipeline_event(rec, user_log_key=user_log_key)
            invalid_delta += 1
            if len(aggregated_invalid_records) < 50:
                aggregated_invalid_records.append(rec)

        return invalid_delta

    async def _wait_for_user_section_mapping(
        self,
        *,
        job_id: int,
        pdf_path: Path,
        file_index: int,
        files_total: int,
        frozen_duration: float,
        pending_names: list[str],
        pending_full_names: dict[str, str] | None = None,
    ) -> float:
        wait_started_at = time()
        progress = int((file_index - 1) / files_total * 100)
        last_emit_at = 0.0
        last_pending_count = -1
        while True:
            store = SpecSectionMappingStore()
            still_pending = [name for name in pending_names if store.is_pending(name)]
            if not still_pending:
                return time() - wait_started_at
            now = monotonic()
            pending_count = len(still_pending)
            should_emit = (
                pending_count != last_pending_count
                or (now - last_emit_at) >= self._WAIT_PROGRESS_INTERVAL_SEC
            )
            if should_emit:
                await self.job_service.update_progress(
                    job_id,
                    progress=progress,
                    extra={
                        "current_file": pdf_path.name,
                        "files_total": files_total,
                        "files_processed": file_index - 1,
                        "undefined_spec_names": still_pending,
                        "undefined_spec_names_total": pending_count,
                        "undefined_spec_sources": {name: pdf_path.name for name in still_pending},
                        "undefined_spec_full_names": {
                            name: pending_full_names[name]
                            for name in still_pending
                            if pending_full_names and name in pending_full_names
                        },
                        "waiting_user_input": True,
                        "duration_sec": frozen_duration,
                    },
                )
                last_emit_at = now
                last_pending_count = pending_count
            await asyncio.sleep(1.0)

    async def _wait_for_embedment_input(
        self,
        *,
        job_id: int,
        pdf_path: Path,
        file_index: int,
        files_total: int,
        frozen_duration: float,
        markers: list[dict],
    ) -> float:
        wait_started_at = time()
        progress = int((file_index - 1) / files_total * 100)
        last_emit_at = 0.0
        while True:
            if await self.importer.embedment_markers_all_resolved(markers):
                return time() - wait_started_at
            now = monotonic()
            if (now - last_emit_at) >= self._WAIT_PROGRESS_INTERVAL_SEC:
                await self.job_service.update_progress(
                    job_id,
                    progress=progress,
                    extra={
                        "current_file": pdf_path.name,
                        "files_total": files_total,
                        "files_processed": file_index - 1,
                        "waiting_embedment_input": True,
                        "embedment_pending": markers,
                        "embedment_pending_total": len(markers),
                        "duration_sec": frozen_duration,
                    },
                )
                last_emit_at = now
            await asyncio.sleep(1.0)

    @staticmethod
    def _elapsed_seconds(started_at: float, paused_total_sec: float) -> float:
        return max(time() - started_at - paused_total_sec, 0.0)

