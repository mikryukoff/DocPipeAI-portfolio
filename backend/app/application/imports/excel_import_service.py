import asyncio
import json
import re
from pathlib import Path
from time import time

import pandas as pd
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.application.jobs.job_service import JobService
from backend.app.application.imports.vik_tests_persistence import upsert_vik_entries
from backend.app.domain.excel_parsing.excel_flow_direction_parser import (
    ExcelFlowDirectionParser,
)
from backend.app.domain.excel_parsing.excel_speca_armature_parser import ExcelSpecaArmatureParser
from backend.app.infrastructure.db.models.job import JobORM
from backend.app.infrastructure.repositories.pipeline_repository import PipelineRepository
from backend.app.infrastructure.repositories.spec_item_repository import SpecItemRepository
from backend.app.shared.pipeline_code_confusables import normalize_pipeline_code_confusable_o_to_zero
from backend.app.shared.pipeline_number_format import normalize_pipeline_name
from backend.app.shared.pipeline_name_extract import (
    collect_pipeline_names_from_cell,
    extract_pipeline_name_after_line_keyword,
    extract_pipeline_name_from_cell,
    is_cyrillic_line_number,
)
from backend.app.shared.parsing_audit_logger import log_parsing_event


class ExcelImportService:
    """
    Единая точка обработки Excel:
    - один раз читает workbook;
    - в одном проходе собирает все нужные обновления;
    - обновляет БД и статистику job для фронта.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        job_service: JobService,
        preview_output_dir: Path,
    ):
        self.session_factory = session_factory
        self.job_service = job_service
        self.preview_output_dir = preview_output_dir
        self.armature_parser = ExcelSpecaArmatureParser()
        self.flow_direction_parser = ExcelFlowDirectionParser()
        self._user_log_key: str | None = None
        self.building_re = re.compile(r"(Производственный\s+корпус\s*№\s*\d+)", re.IGNORECASE)
        self.axes_re = re.compile(r"(в\s+осях\s*[^,;:]+)", re.IGNORECASE)
        self.running_number_re = re.compile(r"V?(\d{4,7})")
        self.vor_armature_running_re = re.compile(r"(?i)V(\d+)")
        self.tests_duration_re = re.compile(r"(\d+)")
        self.tests_type_re = re.compile(r"гидравл\w+|пневмат\w+", re.IGNORECASE)
        self.vik_statement_re = re.compile(r"заключение\s*(.+)", re.IGNORECASE)
        self._aosr_end_works_label_re = re.compile(
            r"\bокончания\s+работ\b",
            re.IGNORECASE,
        )
        self._aosr_year_in_text_re = re.compile(r"\b(19|20)\d{2}\b")
        self.pipeline_code_re = re.compile(
            r"[A-Z]{2}\d{2}-\d{5}(?:\.\d+)?-[A-Z]{3}-\d{2,3}-[A-Z0-9-]+(?:-[A-Z]{2})?"
        )
        self.styloscopy_object_re = re.compile(r"^\s*объект\s+контроля\s*:\s*(.+)$", re.IGNORECASE)
        self.styloscopy_protocol_re = re.compile(r"протокол\s*№\s*(.+)", re.IGNORECASE)
        self.steel_grade_prefix_re = re.compile(r"(\d+(?:\.\d+)+)")
        self.date_re = re.compile(r"(\d{1,2}\.\d{1,2}\.\d{4}|\d{4}-\d{2}-\d{2})(?:\s+\d{2}:\d{2}:\d{2})?")
        self.months = {
            "января",
            "февраля",
            "марта",
            "апреля",
            "мая",
            "июня",
            "июля",
            "августа",
            "сентября",
            "октября",
            "ноября",
            "декабря",
        }
        self.month_numbers = {
            "января": 1,
            "февраля": 2,
            "марта": 3,
            "апреля": 4,
            "мая": 5,
            "июня": 6,
            "июля": 7,
            "августа": 8,
            "сентября": 9,
            "октября": 10,
            "ноября": 11,
            "декабря": 12,
        }

    async def start_import(self, excel_path: Path) -> JobORM:
        file_kind = self.detect_file_kind(excel_path.name)
        job = await self.job_service.create(
            str(excel_path),
            extra={
                "source": "excel",
                "file_kind": file_kind,
                "sheets_total": 0,
                "sheets_processed": 0,
            },
        )
        logger.info("Excel import scheduled. job_id={} excel_path={} kind={}", job.id, excel_path, file_kind)
        asyncio.create_task(self._run(job.id, excel_path))
        return job

    async def _run(self, job_id: int, excel_path: Path):
        started_at = time()
        try:
            await self.job_service.start_processing(job_id)
            await self._process(job_id=job_id, excel_path=excel_path, started_at=started_at)
            await self.job_service.finish(job_id)
        except Exception as exc:
            logger.exception("Excel import crashed. job_id={} excel_path={}", job_id, excel_path)
            await self.job_service.fail(job_id, str(exc))

    async def _process(
        self,
        *,
        job_id: int,
        excel_path: Path,
        started_at: float,
        user_log_key: str | None = None,
        inspect_output_dir: Path | None = None,
    ):
        self._user_log_key = user_log_key
        workbook = self._read_workbook(excel_path)
        sheet_names = list(workbook.keys())
        sheet_count = len(sheet_names)
        file_kind = self._detect_file_kind(excel_path.name, sheet_names, workbook)
        ndt_kind = self._detect_ndt_vik_kind(workbook, sheet_names)
        if ndt_kind is not None:
            file_kind = ndt_kind

        inspection = self._build_inspection_payload(excel_path, workbook, file_kind)
        dump_path = self._dump_inspection(inspection, output_dir=inspect_output_dir)
        await self.job_service.update_progress(
            job_id,
            progress=0,
            extra={
                "file_name": excel_path.name,
                "file_kind": file_kind,
                "sheets_total": sheet_count,
                "sheets_processed": 0,
                "inspection_dump_path": str(dump_path),
                "armature_parsed_rows": 0,
                "flow_direction_parsed_rows": 0,
                "armature_updated_rows": 0,
                "flow_direction_updated_pipelines": 0,
                "parameters_extracted_from_excel_by_sheet": {},
                "parameters_updated_pipelines": 0,
                "duration_sec": 0,
            },
        )

        if file_kind == "aosr":
            await self._process_aosr(
                job_id=job_id,
                excel_path=excel_path,
                workbook=workbook,
                sheet_names=sheet_names,
                sheet_count=sheet_count,
                started_at=started_at,
            )
            return

        if file_kind == "armature_list":
            await self._process_armature_list(
                job_id=job_id,
                excel_path=excel_path,
                workbook=workbook,
                sheet_names=sheet_names,
                started_at=started_at,
            )
            return

        if file_kind == "tests_act":
            await self._process_tests_act(
                job_id=job_id,
                excel_path=excel_path,
                workbook=workbook,
                sheet_names=sheet_names,
                started_at=started_at,
            )
            return

        if file_kind in {"uzk_act", "pvk_act"}:
            await self._process_ndt_vik_act(
                job_id=job_id,
                excel_path=excel_path,
                workbook=workbook,
                sheet_names=sheet_names,
                started_at=started_at,
                ndt_type="УЗК" if file_kind == "uzk_act" else "ПВК",
            )
            return

        if file_kind == "styloscopy_act":
            await self._process_styloscopy_act(
                job_id=job_id,
                excel_path=excel_path,
                workbook=workbook,
                sheet_names=sheet_names,
                started_at=started_at,
            )
            return

        await self.job_service.update_progress(
            job_id,
            progress=100,
            extra={
                "warnings": [f"unsupported_file_kind_for_sync: {file_kind}"],
                "duration_sec": time() - started_at,
            },
        )

    async def _process_aosr(
        self,
        *,
        job_id: int,
        excel_path: Path,
        workbook: dict[str, list[list[str]]],
        sheet_names: list[str],
        sheet_count: int,
        started_at: float,
    ):
        somtt_sheet_names = self._find_all_somtt_like_sheet_names(sheet_names)
        aosr_sheet_names = self._find_all_aosr_sheet_names(sheet_names)
        registry_sheets = [name for name in sheet_names if "реестр" in name.lower()]

        if not somtt_sheet_names and not aosr_sheet_names and not registry_sheets:
            await self.job_service.update_progress(
                job_id,
                progress=100,
                extra={
                    "warnings": [
                        "sheet_not_found: нет листов СоМТТ, АОСР и реестра с ожидаемыми именами",
                    ],
                    "duration_sec": time() - started_at,
                },
            )
            return

        if somtt_sheet_names:
            somtt_rows = self._concat_sheet_rows(workbook, somtt_sheet_names)
            somtt_sheet = ", ".join(somtt_sheet_names)
        else:
            somtt_rows = []
            somtt_sheet = "(нет листа СоМТТ)"

        merged_aosr_fallback: dict[str, str] = {}
        aosr_fields_by_pipeline: dict[str, dict[str, str]] = {}
        for idx, aosr_sn in enumerate(aosr_sheet_names):
            part = self._extract_aosr_parameters(
                aosr_rows=workbook[aosr_sn],
                somtt_rows=somtt_rows,
                job_id=job_id,
                source_file=str(excel_path),
                aosr_sheet=aosr_sn,
                somtt_sheet=somtt_sheet,
                include_somtt_welding=(idx == 0),
                emit_strength_test_rule_log=(idx == 0),
            )
            self._merge_nonempty_string_dict(merged_aosr_fallback, part)
            sheet_codes = self._collect_pipeline_codes_from_workbook(workbook, [aosr_sn])
            sheet_native = {
                "installation_date": (part.get("installation_date") or "").strip(),
                "mounting_scheme": (part.get("mounting_scheme") or "").strip(),
                "year": (part.get("year") or "").strip(),
                "strength_test_result": (part.get("strength_test_result") or "выдержал").strip(),
            }
            for pname in sheet_codes:
                aosr_fields_by_pipeline[pname] = dict(sheet_native)

        if not aosr_sheet_names:
            merged_aosr_fallback = self._extract_aosr_parameters(
                aosr_rows=[],
                somtt_rows=somtt_rows,
                job_id=job_id,
                source_file=str(excel_path),
                aosr_sheet=None,
                somtt_sheet=somtt_sheet,
                include_somtt_welding=True,
                emit_strength_test_rule_log=True,
            )
            aosr_fields_by_pipeline = {}

        flow_context_suffix = self._extract_flow_context_suffix(
            somtt_rows,
            job_id=job_id,
            source_file=str(excel_path),
            somtt_sheet=somtt_sheet,
        )
        flow_updates = self._extract_flows_from_somtt(
            somtt_rows,
            flow_context_suffix,
            job_id=job_id,
            source_file=str(excel_path),
            somtt_sheet=somtt_sheet,
        )
        unique_flow = {item.pipeline_name: item for item in flow_updates}

        armature_updates = self._extract_armature_updates(
            workbook,
            registry_sheets,
            job_id=job_id,
            source_file=str(excel_path),
        )
        unique_armature = {item.source_prefix: item for item in armature_updates}
        sheet_names_for_codes = list(
            dict.fromkeys([*aosr_sheet_names, *registry_sheets, *somtt_sheet_names])
        )
        codes_in_workbook = self._collect_pipeline_codes_from_workbook(workbook, sheet_names_for_codes)
        pipelines_from_somtt = sorted(set(unique_flow.keys()) | codes_in_workbook)

        armature_not_found = []
        flow_not_found = []
        parameters_not_found: list[str] = []
        armature_updated_rows = 0
        flow_updated_pipelines = 0
        parameters_updated_pipelines_set: set[str] = set()

        await self.job_service.update_progress(
            job_id,
            progress=60,
            extra={
                "sheets_processed": sheet_count,
                "armature_parsed_rows": len(armature_updates),
                "flow_direction_parsed_rows": len(flow_updates),
                "duration_sec": time() - started_at,
            },
        )

        async with self.session_factory() as session:
            spec_repo = SpecItemRepository(session)
            pipeline_repo = PipelineRepository(session)

            for armature in unique_armature.values():
                changed = await spec_repo.apply_armature_excel_update(
                    source_prefix=armature.source_prefix,
                    normalized_name=armature.normalized_name,
                    dn=armature.dn,
                    pn=armature.pn,
                    material_grade=armature.material_grade,
                    gost=armature.gost,
                    source_raw=armature.source_raw,
                )
                if changed == 0:
                    armature_not_found.append(armature.source_prefix)
                armature_updated_rows += changed

            await self.job_service.update_progress(
                job_id,
                progress=80,
                extra={
                    "armature_updated_rows": armature_updated_rows,
                    "armature_unique_prefixes": len(unique_armature),
                    "duration_sec": time() - started_at,
                },
            )

            for flow in unique_flow.values():
                changed = await pipeline_repo.update_flow_direction_from_excel(
                    pipeline_name=flow.pipeline_name,
                    flow_direction_text=flow.flow_direction_text,
                    source_raw=flow.source_raw,
                )
                if not changed:
                    flow_not_found.append(flow.pipeline_name)
                else:
                    flow_updated_pipelines += 1

            for pipeline_name in pipelines_from_somtt:
                parameters_update, aosr_mounting_scheme, aosr_year = (
                    self._build_per_pipeline_aosr_updates(
                        pipeline_name=pipeline_name,
                        merged_aosr_fallback=merged_aosr_fallback,
                        aosr_fields_by_pipeline=aosr_fields_by_pipeline,
                    )
                )
                pr_changed = await pipeline_repo.update_parameters_from_excel(
                    pipeline_name=pipeline_name,
                    parameters_update=parameters_update,
                )
                aosr_changed = await pipeline_repo.update_pipeline_aosr_fields(
                    pipeline_name=pipeline_name,
                    mounting_scheme=aosr_mounting_scheme or None,
                    year=aosr_year,
                )
                if pr_changed or aosr_changed:
                    parameters_updated_pipelines_set.add(pipeline_name)
                elif not pr_changed and not aosr_changed:
                    parameters_not_found.append(pipeline_name)

            await session.commit()

        aosr_warnings: list[str] = []
        if not somtt_sheet_names:
            aosr_warnings.append(
                "somtt_sheet_missing: направления потока из СоМТТ недоступны; "
                "список линий для параметров АОСР собран по коду на листах АОСР/реестра",
            )

        await self.job_service.update_progress(
            job_id,
            progress=95,
            extra={
                "armature_matched_sheets": sorted(registry_sheets),
                "flow_direction_matched_sheets": list(somtt_sheet_names),
                "armature_not_found_prefixes": sorted(armature_not_found),
                "flow_direction_not_found_pipeline_names": sorted(flow_not_found),
                "flow_direction_updated_pipelines": flow_updated_pipelines,
                "flow_direction_unique_pipelines": len(unique_flow),
                "parameters_extracted_from_excel_by_sheet": {
                    somtt_sheet: {
                        **merged_aosr_fallback,
                        "year": int(merged_aosr_fallback["year"])
                        if str(merged_aosr_fallback.get("year", "")).strip().isdigit()
                        else None,
                    },
                },
                "somtt_sheets_processed": list(somtt_sheet_names),
                "aosr_sheets_processed": list(aosr_sheet_names),
                "pipeline_names_detected_by_sheet": {somtt_sheet: pipelines_from_somtt},
                "parameters_not_found_pipeline_names": sorted(set(parameters_not_found)),
                "parameters_updated_pipelines": len(parameters_updated_pipelines_set),
                "duration_sec": time() - started_at,
                **({"warnings": aosr_warnings} if aosr_warnings else {}),
            },
        )

        logger.info(
            "Excel import completed. job_id={} file={} sheets={} armature_updates={} flow_updates={} parameters_updates={} duration_sec={:.2f}",
            job_id,
            excel_path.name,
            sheet_count,
            armature_updated_rows,
            flow_updated_pipelines,
            len(parameters_updated_pipelines_set),
            time() - started_at,
        )

    async def _process_armature_list(
        self,
        *,
        job_id: int,
        excel_path: Path,
        workbook: dict[str, list[list[str]]],
        sheet_names: list[str],
        started_at: float,
    ):
        classic_sheet = self._find_sheet_name(sheet_names, "valve list перечень клапанов")
        if not classic_sheet:
            classic_sheet = self._find_sheet_name(sheet_names, "перечень клапанов")

        notes_by_number: dict[str, dict[str, str | int]] = {}
        matched_sheets: list[str] = []

        if classic_sheet:
            notes_by_number = self._extract_valve_notes(
                workbook[classic_sheet],
                source_sheet=classic_sheet,
            )
            if notes_by_number:
                matched_sheets = [classic_sheet]

        if not notes_by_number:
            # Later sheets overwrite duplicate running numbers (dict.update order).
            notes_by_number = {}
            matched_sheets = []
            for sn in sheet_names:
                vor_notes = self._extract_armature_notes_from_work_name_table(
                    workbook.get(sn, []),
                    source_sheet=sn,
                )
                if vor_notes:
                    matched_sheets.append(sn)
                notes_by_number.update(vor_notes)

        if not notes_by_number:
            await self.job_service.update_progress(
                job_id,
                progress=100,
                extra={
                    "warnings": [
                        "armature_list_no_data: ожидается лист с «VALVE LIST / ПЕРЕЧЕНЬ КЛАПАНОВ» и колонками "
                        "номера и примечания, либо таблица с «Наименование работ» (номер после V) и «Описание»."
                    ],
                    "duration_sec": time() - started_at,
                },
            )
            return

        parsed_rows = len(notes_by_number)
        updated_rows = 0
        not_found_numbers: list[str] = []

        async with self.session_factory() as session:
            spec_repo = SpecItemRepository(session)
            for number, note_data in notes_by_number.items():
                note = note_data["note"]
                parsed = self.armature_parser.try_parse_note(
                    source_prefix=f"Арматура V{number}",
                    note_text=note,
                )
                if parsed is None:
                    continue
                row_sheet = str(note_data.get("sheet", ""))
                log_parsing_event(
                    job_id=job_id,
                    user_log_key=self._user_log_key,
                    source_type="excel",
                    source_file=str(excel_path),
                    parser="ExcelImportService",
                    entity="armature",
                    entity_id=f"V{number}",
                    field="note",
                    value=note,
                    origin={
                        "sheet": row_sheet,
                        "row_index": note_data["row_index"],
                        "row_text": note_data["row_text"],
                        "note_col_index": note_data.get("note_col_index"),
                    },
                )
                changed = await spec_repo.apply_armature_excel_update_by_running_number(
                    running_number=number,
                    normalized_name=parsed.normalized_name,
                    dn=parsed.dn,
                    pn=parsed.pn,
                    material_grade=parsed.material_grade,
                    gost=parsed.gost,
                    source_raw=parsed.source_raw,
                )
                if changed == 0:
                    not_found_numbers.append(number)
                updated_rows += changed
            await session.commit()

        await self.job_service.update_progress(
            job_id,
            progress=95,
            extra={
                "armature_matched_sheets": matched_sheets,
                "armature_parsed_rows": parsed_rows,
                "armature_updated_rows": updated_rows,
                "armature_not_found_running_numbers": sorted(set(not_found_numbers)),
                "duration_sec": time() - started_at,
            },
        )

        logger.info(
            "Excel armature list import completed. job_id={} file={} parsed_rows={} updated_rows={} duration_sec={:.2f}",
            job_id,
            excel_path.name,
            parsed_rows,
            updated_rows,
            time() - started_at,
        )

    def _parse_tests_act_sheet(self, rows: list[list[str]]) -> dict[str, str] | None:
        """Поля акта испытаний с листа; None — если строка 2 не заголовок акта."""
        row_header = rows[1] if len(rows) > 1 else []
        row_header_text = " ".join(cell for cell in row_header if cell).strip()
        if not self._is_tests_act_header(row_header_text):
            return None

        row_type = rows[24] if len(rows) > 24 else []
        row_line = rows[27] if len(rows) > 27 else []
        row_method = rows[29] if len(rows) > 29 else []
        row_pressure = rows[32] if len(rows) > 32 else []
        row_duration = rows[36] if len(rows) > 36 else []
        row_type_text = " ".join(cell for cell in row_type if cell).strip()
        row_line_text = " ".join(cell for cell in row_line if cell).strip()
        row_method_text = " ".join(cell for cell in row_method if cell).strip()
        row_pressure_text = " ".join(cell for cell in row_pressure if cell).strip()
        row_duration_text = " ".join(cell for cell in row_duration if cell).strip()

        return {
            "row_header_text": row_header_text,
            "row_type_text": row_type_text,
            "row_line_text": row_line_text,
            "row_method_text": row_method_text,
            "row_pressure_text": row_pressure_text,
            "row_duration_text": row_duration_text,
            "strength_test_type": self._extract_tests_strength_test_type(row_type_text),
            "pipeline_name": self._extract_tests_pipeline_name(row_line_text),
            "strength_test_method": self._extract_tests_strength_test_method(row_method_text),
            "strength_test_pressure": self._extract_tests_strength_test_pressure(row_pressure_text),
            "strength_test_duration": self._extract_tests_duration(row_duration_text),
        }

    async def _process_tests_act(
        self,
        *,
        job_id: int,
        excel_path: Path,
        workbook: dict[str, list[list[str]]],
        sheet_names: list[str],
        started_at: float,
    ):
        if not sheet_names:
            await self.job_service.update_progress(
                job_id,
                progress=100,
                extra={
                    "warnings": ["sheet_not_found: workbook_empty"],
                    "duration_sec": time() - started_at,
                },
            )
            return

        warnings: list[str] = []
        parameters_extracted_by_sheet: dict[str, dict[str, str]] = {}
        pipeline_names_by_sheet: dict[str, list[str]] = {}
        updated = 0
        not_found: list[str] = []
        last_success_sheet: str | None = None
        last_success_fields: dict[str, str] = {}
        sheets_with_valid_header = 0

        async with self.session_factory() as session:
            pipeline_repo = PipelineRepository(session)

            for sheet_name in sheet_names:
                rows = workbook.get(sheet_name, [])
                parsed = self._parse_tests_act_sheet(rows)
                if parsed is None:
                    row_header = rows[1] if len(rows) > 1 else []
                    row_header_text = " ".join(cell for cell in row_header if cell).strip()
                    if row_header_text:
                        warnings.append(f"tests_act_header_invalid:{sheet_name}")
                        log_parsing_event(
                            job_id=job_id,
                            user_log_key=self._user_log_key,
                            source_type="excel",
                            source_file=str(excel_path),
                            parser="ExcelImportService",
                            entity="tests_act",
                            entity_id=None,
                            field="header_row_2",
                            value=row_header_text,
                            origin={"sheet": sheet_name, "row_index": 2, "row_text": row_header_text},
                            status="warning",
                            note="tests_act_header_invalid",
                        )
                    continue

                sheets_with_valid_header += 1
                strength_test_type = parsed["strength_test_type"]
                pipeline_name = parsed["pipeline_name"]
                strength_test_method = parsed["strength_test_method"]
                strength_test_pressure = parsed["strength_test_pressure"]
                strength_test_duration = parsed["strength_test_duration"]
                row_type_text = parsed["row_type_text"]
                row_line_text = parsed["row_line_text"]
                row_method_text = parsed["row_method_text"]
                row_pressure_text = parsed["row_pressure_text"]
                row_duration_text = parsed["row_duration_text"]

                if strength_test_type:
                    log_parsing_event(
                        job_id=job_id,
                        user_log_key=self._user_log_key,
                        source_type="excel",
                        source_file=str(excel_path),
                        parser="ExcelImportService",
                        entity="pipeline_parameters",
                        entity_id=pipeline_name or None,
                        field="strength_test_type",
                        value=strength_test_type,
                        origin={"sheet": sheet_name, "row_index": 25, "row_text": row_type_text},
                    )

                if pipeline_name:
                    log_parsing_event(
                        job_id=job_id,
                        user_log_key=self._user_log_key,
                        source_type="excel",
                        source_file=str(excel_path),
                        parser="ExcelImportService",
                        entity="pipeline",
                        entity_id=pipeline_name,
                        field="tests_act.pipeline_name",
                        value=pipeline_name,
                        origin={"sheet": sheet_name, "row_index": 28, "row_text": row_line_text},
                    )

                if strength_test_method:
                    log_parsing_event(
                        job_id=job_id,
                        user_log_key=self._user_log_key,
                        source_type="excel",
                        source_file=str(excel_path),
                        parser="ExcelImportService",
                        entity="pipeline_parameters",
                        entity_id=pipeline_name or None,
                        field="strength_test_method",
                        value=strength_test_method,
                        origin={"sheet": sheet_name, "row_index": 30, "row_text": row_method_text},
                    )

                if strength_test_pressure:
                    log_parsing_event(
                        job_id=job_id,
                        user_log_key=self._user_log_key,
                        source_type="excel",
                        source_file=str(excel_path),
                        parser="ExcelImportService",
                        entity="pipeline_parameters",
                        entity_id=pipeline_name or None,
                        field="strength_test_pressure",
                        value=strength_test_pressure,
                        origin={"sheet": sheet_name, "row_index": 33, "row_text": row_pressure_text},
                    )

                if strength_test_duration:
                    log_parsing_event(
                        job_id=job_id,
                        user_log_key=self._user_log_key,
                        source_type="excel",
                        source_file=str(excel_path),
                        parser="ExcelImportService",
                        entity="pipeline_parameters",
                        entity_id=pipeline_name or None,
                        field="strength_test_duration",
                        value=strength_test_duration,
                        origin={"sheet": sheet_name, "row_index": 37, "row_text": row_duration_text},
                    )

                if not pipeline_name or not any(
                    [
                        strength_test_type,
                        strength_test_method,
                        strength_test_pressure,
                        strength_test_duration,
                    ]
                ):
                    sheet_warnings: list[str] = []
                    if not pipeline_name:
                        sheet_warnings.append("tests_act_pipeline_not_found_row_28")
                    if not strength_test_type:
                        sheet_warnings.append("tests_act_strength_test_type_not_found_row_25")
                    if not strength_test_method:
                        sheet_warnings.append("tests_act_strength_test_method_not_found_row_30")
                    if not strength_test_pressure:
                        sheet_warnings.append("tests_act_strength_test_pressure_not_found_row_33")
                    if not strength_test_duration:
                        sheet_warnings.append("tests_act_strength_test_duration_not_found_row_37")
                    for code in sheet_warnings:
                        warnings.append(f"{code}:{sheet_name}")
                    log_parsing_event(
                        job_id=job_id,
                        user_log_key=self._user_log_key,
                        source_type="excel",
                        source_file=str(excel_path),
                        parser="ExcelImportService",
                        entity="tests_act",
                        entity_id=pipeline_name or None,
                        field="parse_status",
                        value="incomplete",
                        origin={
                            "sheet": sheet_name,
                            "row_index": None,
                            "row_text": " | ".join(
                                [
                                    row_type_text,
                                    row_line_text,
                                    row_method_text,
                                    row_pressure_text,
                                    row_duration_text,
                                ]
                            ),
                        },
                        status="warning",
                        note=", ".join(sheet_warnings),
                    )
                    continue

                changed = await pipeline_repo.update_parameters_from_excel(
                    pipeline_name=pipeline_name,
                    parameters_update={
                        "strength_test_type": strength_test_type,
                        "strength_test_method": strength_test_method,
                        "strength_test_pressure": strength_test_pressure,
                        "strength_test_duration": strength_test_duration,
                    },
                )
                parameters_extracted_by_sheet[sheet_name] = {
                    "strength_test_type": strength_test_type,
                    "strength_test_method": strength_test_method,
                    "strength_test_pressure": strength_test_pressure,
                    "strength_test_duration": strength_test_duration,
                }
                pipeline_names_by_sheet[sheet_name] = [pipeline_name]
                last_success_sheet = sheet_name
                last_success_fields = {
                    "strength_test_type": strength_test_type,
                    "strength_test_method": strength_test_method,
                    "strength_test_pressure": strength_test_pressure,
                    "strength_test_duration": strength_test_duration,
                    "pipeline_name": pipeline_name,
                }
                if changed:
                    updated += 1
                    log_parsing_event(
                        job_id=job_id,
                        user_log_key=self._user_log_key,
                        source_type="excel",
                        source_file=str(excel_path),
                        parser="ExcelImportService",
                        entity="pipeline",
                        entity_id=pipeline_name,
                        field="tests_act.update_parameters",
                        value="updated",
                        origin={"sheet": sheet_name, "row_index": None, "row_text": ""},
                    )
                else:
                    not_found.append(pipeline_name)
                    log_parsing_event(
                        job_id=job_id,
                        user_log_key=self._user_log_key,
                        source_type="excel",
                        source_file=str(excel_path),
                        parser="ExcelImportService",
                        entity="pipeline",
                        entity_id=pipeline_name,
                        field="tests_act.update_parameters",
                        value="not_found",
                        origin={"sheet": sheet_name, "row_index": None, "row_text": ""},
                        status="warning",
                    )

            await session.commit()

        if sheets_with_valid_header == 0:
            await self.job_service.update_progress(
                job_id,
                progress=100,
                extra={
                    "warnings": warnings or ["tests_act_header_invalid_row_2"],
                    "duration_sec": time() - started_at,
                },
            )
            return

        if updated == 0 and not parameters_extracted_by_sheet:
            await self.job_service.update_progress(
                job_id,
                progress=100,
                extra={
                    "warnings": warnings,
                    "tests_act_sheets_processed": sheets_with_valid_header,
                    "duration_sec": time() - started_at,
                },
            )
            return

        extra: dict = {
            "tests_act_sheets_processed": len(parameters_extracted_by_sheet),
            "parameters_extracted_from_excel_by_sheet": parameters_extracted_by_sheet,
            "pipeline_names_detected_by_sheet": pipeline_names_by_sheet,
            "parameters_updated_pipelines": updated,
            "parameters_not_found_pipeline_names": sorted(set(not_found)),
            "warnings": warnings,
            "duration_sec": time() - started_at,
        }
        if last_success_sheet and last_success_fields:
            extra.update(
                {
                    "tests_act_sheet": last_success_sheet,
                    "tests_act_strength_test_type": last_success_fields["strength_test_type"],
                    "tests_act_pipeline_name": last_success_fields["pipeline_name"],
                    "tests_act_strength_test_method": last_success_fields["strength_test_method"],
                    "tests_act_strength_test_pressure": last_success_fields["strength_test_pressure"],
                    "tests_act_duration": last_success_fields["strength_test_duration"],
                }
            )
        await self.job_service.update_progress(job_id, progress=95, extra=extra)

    def _extract_tests_pipeline_name(self, row_text: str) -> str:
        raw = extract_pipeline_name_after_line_keyword(row_text)
        if not raw:
            return ""
        if is_cyrillic_line_number(raw):
            return raw
        return normalize_pipeline_code_confusable_o_to_zero(raw)

    def _extract_tests_duration(self, row_text: str) -> str:
        if not row_text:
            return ""
        match = self.tests_duration_re.search(row_text)
        return match.group(1) if match else ""

    @staticmethod
    def _extract_after_phrase(row_text: str, phrase: str) -> str:
        if not row_text:
            return ""
        low = row_text.lower()
        idx = low.find(phrase.lower())
        if idx < 0:
            return ""
        return row_text[idx + len(phrase) :].strip(" :;-").strip()

    def _extract_tests_strength_test_type(self, row_text: str) -> str:
        candidate = self._extract_after_phrase(row_text, "способом")
        if not candidate:
            return ""
        matches = self.tests_type_re.findall(candidate)
        if not matches:
            return candidate
        unique: list[str] = []
        for item in matches:
            norm = item.lower()
            if norm.startswith("гидравл") and "гидравлическим" not in unique:
                unique.append("гидравлическим")
            elif norm.startswith("пневмат") and "пневматическим" not in unique:
                unique.append("пневматическим")
        return ", ".join(unique) if unique else candidate

    def _extract_tests_strength_test_method(self, row_text: str) -> str:
        return self._extract_after_phrase(row_text, "испытание проводилось")

    def _extract_tests_strength_test_pressure(self, row_text: str) -> str:
        return self._extract_after_phrase(row_text, "на прочность давлением")

    def _detect_ndt_vik_kind(
        self,
        workbook: dict[str, list[list[str]]],
        sheet_names: list[str],
    ) -> str | None:
        rk_sheet = self._find_rk_sheet(sheet_names)
        if rk_sheet is None:
            return None
        rows = workbook.get(rk_sheet, [])
        uzk_row = " ".join(cell for cell in (rows[9] if len(rows) > 9 else []) if cell).lower()
        pvk_row = " ".join(cell for cell in (rows[8] if len(rows) > 8 else []) if cell).lower()
        if "по ультразвуковому контролю качества сварных соединений" in uzk_row:
            return "uzk_act"
        if "по капиллярному контролю сварных соединений и основного металла" in pvk_row:
            return "pvk_act"
        return None

    async def _process_ndt_vik_act(
        self,
        *,
        job_id: int,
        excel_path: Path,
        workbook: dict[str, list[list[str]]],
        sheet_names: list[str],
        started_at: float,
        ndt_type: str,
    ) -> None:
        rk_sheet = self._find_rk_sheet(sheet_names)
        if rk_sheet is None:
            await self.job_service.update_progress(
                job_id,
                progress=100,
                extra={"warnings": ["sheet_not_found: РК"], "duration_sec": time() - started_at},
            )
            return

        rows = workbook.get(rk_sheet, [])
        if ndt_type == "УЗК":
            statement = self._extract_statement_after_conclusion(
                " ".join(cell for cell in (rows[8] if len(rows) > 8 else []) if cell).strip()
            )
            pipeline_name = self._extract_pipeline_name_from_row(
                rows[16] if len(rows) > 16 else [], 3, 4
            )
        else:
            statement_num = self._extract_statement_after_conclusion(
                " ".join(cell for cell in (rows[7] if len(rows) > 7 else []) if cell).strip()
            )
            statement_date = " ".join(cell for cell in (rows[9] if len(rows) > 9 else []) if cell).strip()
            statement = self._compose_statement(statement_num, statement_date)
            pipeline_name = self._extract_pipeline_name_from_row(
                rows[17] if len(rows) > 17 else [], 3, 5
            )

        if statement:
            log_parsing_event(
                job_id=job_id,
                user_log_key=self._user_log_key,
                source_type="excel",
                source_file=str(excel_path),
                parser="ExcelImportService",
                entity="vik",
                entity_id=pipeline_name or None,
                field="statement_text",
                value=statement,
                origin={"sheet": rk_sheet, "row_index": 9 if ndt_type == "УЗК" else 8},
            )
        if pipeline_name:
            log_parsing_event(
                job_id=job_id,
                user_log_key=self._user_log_key,
                source_type="excel",
                source_file=str(excel_path),
                parser="ExcelImportService",
                entity="pipeline",
                entity_id=pipeline_name,
                field=f"{ndt_type.lower()}.pipeline_name",
                value=pipeline_name,
                origin={"sheet": rk_sheet, "row_index": 17 if ndt_type == "УЗК" else 18},
            )

        if not statement or not pipeline_name:
            warnings = []
            if not statement:
                warnings.append("ndt_statement_not_found")
            if not pipeline_name:
                warnings.append("ndt_pipeline_not_found")
            await self.job_service.update_progress(
                job_id,
                progress=100,
                extra={
                    "warnings": warnings,
                    "duration_sec": time() - started_at,
                },
            )
            return

        db_update = await upsert_vik_entries(
            self.session_factory,
            [{"pipe_num": pipeline_name, "statement_text": statement, "type": ndt_type}],
            replace_existing_for_pipe_type=True,
        )
        log_parsing_event(
            job_id=job_id,
            user_log_key=self._user_log_key,
            source_type="excel",
            source_file=str(excel_path),
            parser="ExcelImportService",
            entity="vik",
            entity_id=pipeline_name,
            field=f"{ndt_type.lower()}.db_update",
            value=str(db_update),
            origin={"sheet": rk_sheet, "row_index": None},
        )
        await self.job_service.update_progress(
            job_id,
            progress=95,
            extra={
                "ndt_type": ndt_type,
                "ndt_sheet": rk_sheet,
                "ndt_pipeline_name": pipeline_name,
                "ndt_statement_text": statement,
                "db_update": db_update,
                "duration_sec": time() - started_at,
            },
        )

    async def _process_styloscopy_act(
        self,
        *,
        job_id: int,
        excel_path: Path,
        workbook: dict[str, list[list[str]]],
        sheet_names: list[str],
        started_at: float,
    ) -> None:
        rows_to_upsert: list[dict[str, str]] = []
        warnings: list[str] = []

        for sheet_name in sheet_names:
            rows = workbook.get(sheet_name, [])
            extracted = self._extract_styloscopy_sheet_data(rows)
            pipeline_name = extracted.get("pipeline_name", "")
            steel_marks = extracted.get("steel_marks", [])
            protocol_after_no = extracted.get("protocol_after_no", "")
            object_control = extracted.get("object_control", "")
            line_number = extracted.get("line_number", "")

            if not pipeline_name:
                warnings.append(f"styloscopy_pipeline_not_found:{sheet_name}")
                continue
            if not steel_marks:
                warnings.append(f"styloscopy_steel_marks_not_found:{sheet_name}")
                continue

            statement_text = self._pack_styloscopy_statement(
                protocol_after_no=protocol_after_no,
                steel_marks=", ".join(steel_marks),
            )
            rows_to_upsert.append(
                {
                    "pipe_num": pipeline_name,
                    "statement_text": statement_text,
                    "type": "СТИЛОСКОПИРОВАНИЕ",
                }
            )
            log_parsing_event(
                job_id=job_id,
                user_log_key=self._user_log_key,
                source_type="excel",
                source_file=str(excel_path),
                parser="ExcelImportService",
                entity="vik",
                entity_id=pipeline_name,
                field="styloscopy.statement_text",
                value=statement_text,
                origin={
                    "sheet": sheet_name,
                    "object_control": object_control,
                    "line_number": line_number,
                    "protocol_after_no": protocol_after_no,
                },
            )

        if not rows_to_upsert:
            await self.job_service.update_progress(
                job_id,
                progress=100,
                extra={
                    "warnings": warnings or ["styloscopy_data_not_found"],
                    "duration_sec": time() - started_at,
                },
            )
            return

        db_update = await upsert_vik_entries(
            self.session_factory,
            rows_to_upsert,
            replace_existing_for_pipe_type=True,
        )
        await self.job_service.update_progress(
            job_id,
            progress=95,
            extra={
                "styloscopy_rows_total": len(rows_to_upsert),
                "db_update": db_update,
                "warnings": warnings,
                "duration_sec": time() - started_at,
            },
        )

    def _extract_styloscopy_sheet_data(self, rows: list[list[str]]) -> dict[str, str | list[str]]:
        object_control = self._find_styloscopy_object_control_text(rows)
        pipeline_name = self._extract_pipeline_code_from_object_control(object_control)
        line_number = self._extract_line_number_from_object_control(object_control)
        protocol_after_no = self._extract_styloscopy_protocol_after_number(rows)
        steel_marks = self._extract_styloscopy_steel_marks(rows)
        return {
            "object_control": object_control,
            "pipeline_name": pipeline_name,
            "line_number": line_number,
            "protocol_after_no": protocol_after_no,
            "steel_marks": steel_marks,
        }

    def _extract_styloscopy_protocol_after_number(self, rows: list[list[str]]) -> str:
        candidates: list[str] = []
        # Приоритет: A7 (обычно содержит протокол).
        if len(rows) > 6 and len(rows[6]) > 0:
            candidates.append((rows[6][0] or "").strip())
        # Фоллбэк: по всему листу.
        for row in rows:
            for cell in row:
                text = (cell or "").strip()
                if text:
                    candidates.append(text)

        for text in candidates:
            match = self.styloscopy_protocol_re.search(" ".join(text.split()))
            if not match:
                continue
            return match.group(1).strip()
        return ""

    def _find_styloscopy_object_control_text(self, rows: list[list[str]]) -> str:
        for row in rows:
            for cell in row:
                text = (cell or "").strip()
                if not text:
                    continue
                if self.styloscopy_object_re.match(text):
                    return text
        return ""

    def _extract_pipeline_code_from_object_control(self, object_control_text: str) -> str:
        text = (object_control_text or "").strip()
        if not text:
            return ""

        paren_match = re.search(r"\(([^()]+)\)", text)
        if paren_match:
            code_candidate = " ".join(paren_match.group(1).split()).upper()
            code_match = self.pipeline_code_re.search(code_candidate)
            if code_match:
                return normalize_pipeline_code_confusable_o_to_zero(code_match.group(0))

        full_match = self.pipeline_code_re.search(text.upper())
        if full_match:
            return normalize_pipeline_code_confusable_o_to_zero(full_match.group(0))
        return ""

    @staticmethod
    def _extract_line_number_from_object_control(object_control_text: str) -> str:
        match = re.search(r"линия\s*(\d+)", object_control_text or "", re.IGNORECASE)
        return match.group(1) if match else ""

    def _extract_styloscopy_steel_marks(self, rows: list[list[str]]) -> list[str]:
        header_row_index = -1
        column_index = -1
        for row_index, row in enumerate(rows):
            for col_index, cell in enumerate(row):
                text = (cell or "").strip().lower()
                if (
                    "соответствие марки стали" in text
                    or "соответствие марке стали" in text
                ):
                    header_row_index = row_index
                    column_index = col_index
                    break
            if column_index >= 0:
                break

        if column_index < 0:
            return []

        unique_marks: list[str] = []
        seen: set[str] = set()
        for row in rows[header_row_index + 1 :]:
            if column_index >= len(row):
                continue
            raw_value = (row[column_index] or "").strip()
            if not raw_value:
                continue
            match = self.steel_grade_prefix_re.search(raw_value.replace(",", "."))
            if not match:
                continue
            normalized = f"EN {match.group(1)}"
            if normalized in seen:
                continue
            seen.add(normalized)
            unique_marks.append(normalized)
        return unique_marks

    @staticmethod
    def _pack_styloscopy_statement(*, protocol_after_no: str, steel_marks: str) -> str:
        payload = {
            "protocol_after_no": (protocol_after_no or "").strip(),
            "steel_marks": (steel_marks or "").strip(),
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _find_rk_sheet(sheet_names: list[str]) -> str | None:
        for name in sheet_names:
            normalized = " ".join((name or "").lower().split())
            if normalized == "рк":
                return name
        for name in sheet_names:
            normalized = " ".join((name or "").lower().split())
            if "рк" in normalized:
                return name
        return None

    def _extract_statement_after_conclusion(self, row_text: str) -> str:
        text = (row_text or "").strip()
        if not text:
            return ""
        text = " ".join(text.split())
        match = self.vik_statement_re.search(text)
        if not match:
            return ""
        candidate = match.group(1).strip(" .:-").strip()
        date_match = self.date_re.search(candidate)
        if not date_match:
            return candidate
        # Обрезаем все, что идет после первой даты (например: "2,5 (для 10-12мм)").
        prefix = candidate[: date_match.start()]
        return f"{prefix}{self._extract_first_date(date_match.group(1))}".strip(" .:-").strip()

    @staticmethod
    def _join_excel_columns(row: list[str], start_idx: int, end_idx: int) -> str:
        if not row:
            return ""
        end_idx = min(end_idx, len(row) - 1)
        if end_idx < start_idx:
            return ""
        values = [str(row[idx]).strip() for idx in range(start_idx, end_idx + 1)]
        compact = [value for value in values if value]
        return " ".join(compact).strip().rstrip(".")

    def _compose_statement(self, number_part: str, date_part: str) -> str:
        number_clean = (number_part or "").strip()
        date_clean = self._extract_first_date(date_part)
        if number_clean and date_clean:
            return f"{number_clean}-{date_clean}"
        return number_clean or date_clean

    def _extract_pipeline_name_from_row(
        self,
        row: list[str],
        start_idx: int,
        end_idx: int,
    ) -> str:
        text = self._join_excel_columns(row, start_idx, end_idx)
        if not text:
            return ""
        text_norm = " ".join(text.replace("\n", " ").split())
        match = self.pipeline_code_re.search(text_norm.upper())
        if match:
            return normalize_pipeline_code_confusable_o_to_zero(match.group(0))
        label = extract_pipeline_name_from_cell(text_norm)
        if label:
            if is_cyrillic_line_number(label):
                return normalize_pipeline_name(label)
            return normalize_pipeline_code_confusable_o_to_zero(label)
        return text_norm

    def _extract_first_date(self, text: str) -> str:
        raw = (text or "").strip()
        if not raw:
            return ""
        match = self.date_re.search(raw)
        if not match:
            return " ".join(raw.split())
        date_raw = match.group(1).strip()
        # Excel иногда отдаёт дату как YYYY-MM-DD (или с time-хвостом), приводим к DD.MM.YYYY.
        iso_match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", date_raw)
        if iso_match:
            yyyy, mm, dd = iso_match.groups()
            return f"{dd}.{mm}.{yyyy}"
        return date_raw

    @staticmethod
    def _is_tests_act_header(row_text: str) -> bool:
        normalized = " ".join((row_text or "").upper().split())
        return (
            "АКТ ИСПЫТАНИЙ ТРУБОПРОВОДА" in normalized
            or "АКТ ИСПЫТАНИЯ ТРУБОПРОВОДА" in normalized
        )

    @staticmethod
    def detect_file_kind(filename: str) -> str:
        name = filename.lower()
        if "стилоскоп" in name:
            return "styloscopy_act"
        if "акт" in name:
            return "tests_act"
        if "аоср" in name or "aosr" in name:
            return "aosr"
        if "перечень арматур" in name or "valve list" in name:
            return "armature_list"
        if "вор" in name:
            return "armature_list"
        return "unknown"

    def _detect_file_kind(
        self,
        filename: str,
        sheet_names: list[str],
        workbook: dict[str, list[list[str]]],
    ) -> str:
        file_kind = self.detect_file_kind(filename)
        if file_kind != "unknown":
            return file_kind

        if self._is_styloscopy_workbook(workbook, sheet_names):
            return "styloscopy_act"
        if self._find_sheet_name(sheet_names, "valve list перечень клапанов"):
            return "armature_list"
        if self._find_sheet_name(sheet_names, "перечень клапанов"):
            return "armature_list"
        if self._workbook_looks_like_armature_work_table(workbook, sheet_names):
            return "armature_list"
        if self._workbook_looks_like_tests_act(workbook, sheet_names):
            return "tests_act"
        if self._find_all_aosr_sheet_names(sheet_names):
            return "aosr"
        return "unknown"

    @staticmethod
    def _workbook_looks_like_tests_act(
        workbook: dict[str, list[list[str]]],
        sheet_names: list[str],
    ) -> bool:
        """
        Файлы вроде «Испытания.xlsx» без слова «акт» в имени, но с типичным заголовком акта на 2-й строке.
        """
        for sheet_name in sheet_names:
            rows = workbook.get(sheet_name, [])
            if len(rows) < 2:
                continue
            row_header = rows[1]
            row_header_text = " ".join(str(cell).strip() for cell in row_header if cell).strip()
            if ExcelImportService._is_tests_act_header(row_header_text):
                return True
        return False

    @staticmethod
    def _is_styloscopy_workbook(
        workbook: dict[str, list[list[str]]],
        sheet_names: list[str],
    ) -> bool:
        for sheet_name in sheet_names:
            rows = workbook.get(sheet_name, [])
            a1 = ((rows[0][0] if len(rows) > 0 and len(rows[0]) > 0 else "") or "").strip().lower()
            a8 = ((rows[7][0] if len(rows) > 7 and len(rows[7]) > 0 else "") or "").strip().lower()
            if "испытательная лаборатория" in a1:
                return True
            if "по контролю химического состава" in a8:
                return True
        return False

    @staticmethod
    def _read_workbook(excel_path: Path) -> dict[str, list[list[str]]]:
        suffix = excel_path.suffix.lower()
        engine_kw: dict[str, str] = {}
        if suffix in (".xlsx", ".xlsm"):
            engine_kw["engine"] = "openpyxl"
        xls = pd.ExcelFile(excel_path, **engine_kw)
        workbook: dict[str, list[list[str]]] = {}

        for sheet_name in xls.sheet_names:
            df = pd.read_excel(
                xls,
                sheet_name=sheet_name,
                header=None,
                dtype=str,
            ).fillna("")
            workbook[sheet_name] = [
                ["" if value is None else str(value).strip() for value in row]
                for row in df.values.tolist()
            ]

        return workbook

    @staticmethod
    def _drop_empty_rows(rows: list[list[str]]) -> list[list[str]]:
        filtered = []
        for row in rows:
            compact = [value for value in row if value]
            if compact:
                filtered.append(compact)
        return filtered

    def _build_inspection_payload(
        self,
        excel_path: Path,
        workbook: dict[str, list[list[str]]],
        file_kind: str,
    ) -> dict:
        sheets_payload = []
        for sheet_name, rows in workbook.items():
            rows_count = len(rows)
            cols_count = max((len(row) for row in rows), default=0)
            preview_rows = self._drop_empty_rows(rows)
            sheets_payload.append(
                {
                    "sheet_name": sheet_name,
                    "rows_count": rows_count,
                    "cols_count": cols_count,
                    "preview_rows": preview_rows,
                }
            )

        return {
            "file_name": excel_path.name,
            "file_path": str(excel_path),
            "file_kind": file_kind,
            "sheet_count": len(workbook),
            "sheets": sheets_payload,
            "preview_limits": {
                "max_preview_rows": None,
                "max_preview_cols": None,
            },
        }

    def _dump_inspection(self, payload: dict, *, output_dir: Path | None = None) -> Path:
        d = output_dir or self.preview_output_dir
        d.mkdir(parents=True, exist_ok=True)
        stem = Path(payload["file_name"]).stem
        dump_path = d / f"{stem}.inspect.json"
        dump_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return dump_path

    @staticmethod
    def _aosr_row_join(row: list) -> str:
        return " ".join(str(c).strip() for c in row if c is not None and str(c).strip())

    @staticmethod
    def _extract_mounting_scheme_from_aosr_row_concat(row_concat: str) -> str:
        """Строка, начинающаяся с «ПСИ»; значение до первой «;» (или до запятой / конца)."""
        s = (row_concat or "").strip()
        if not s.casefold().startswith("пси"):
            return ""
        if ";" in s:
            head = s.split(";", 1)[0].strip()
        elif "," in s:
            head = s.split(",", 1)[0].strip()
        else:
            head = s
        if not head.casefold().startswith("пси") or len(head) < 4:
            return ""
        return head

    def _extract_year_from_aosr_end_works_row(self, row_concat: str) -> int | None:
        if not row_concat or not self._aosr_end_works_label_re.search(row_concat):
            return None
        m = self._aosr_year_in_text_re.search(row_concat)
        return int(m.group(0)) if m else None

    def _extract_aosr_parameters(
        self,
        *,
        aosr_rows: list[list[str]],
        somtt_rows: list[list[str]],
        job_id: int,
        source_file: str,
        aosr_sheet: str | None,
        somtt_sheet: str,
        include_somtt_welding: bool = True,
        emit_strength_test_rule_log: bool = True,
    ) -> dict[str, str]:
        installation_date = ""
        welding_material = ""
        mounting_scheme = ""
        year_str = ""

        for idx, row in enumerate(aosr_rows):
            row_concat = self._aosr_row_join(row)
            if not row_concat:
                continue
            row_text_lower = row_concat.casefold()
            if not installation_date and "окончания работ" in row_text_lower:
                installation_date = self._parse_installation_date_nearby(aosr_rows, idx)
                if installation_date:
                    log_parsing_event(
                        job_id=job_id,
                        user_log_key=self._user_log_key,
                        source_type="excel",
                        source_file=source_file,
                        parser="ExcelImportService",
                        entity="pipeline_parameters",
                        entity_id=None,
                        field="installation_date",
                        value=installation_date,
                        origin={
                            "sheet": aosr_sheet or "АОСР",
                            "row_index": idx + 1,
                            "row_text": " | ".join(str(c) for c in row if c is not None and str(c).strip()),
                        },
                    )
            if not mounting_scheme:
                ms = self._extract_mounting_scheme_from_aosr_row_concat(row_concat)
                if ms:
                    mounting_scheme = ms
                    log_parsing_event(
                        job_id=job_id,
                        user_log_key=self._user_log_key,
                        source_type="excel",
                        source_file=source_file,
                        parser="ExcelImportService",
                        entity="pipeline",
                        entity_id=None,
                        field="mounting_scheme",
                        value=mounting_scheme,
                        origin={
                            "sheet": aosr_sheet or "АОСР",
                            "row_index": idx + 1,
                            "row_text": " | ".join(str(c) for c in row if c is not None and str(c).strip()),
                        },
                    )
            if not year_str:
                y = self._extract_year_from_aosr_end_works_row(row_concat)
                if y is None and idx + 1 < len(aosr_rows):
                    combined = f"{row_concat} {self._aosr_row_join(aosr_rows[idx + 1])}"
                    y = self._extract_year_from_aosr_end_works_row(combined)
                if y is not None:
                    year_str = str(y)
                    log_parsing_event(
                        job_id=job_id,
                        user_log_key=self._user_log_key,
                        source_type="excel",
                        source_file=source_file,
                        parser="ExcelImportService",
                        entity="pipeline",
                        entity_id=None,
                        field="year",
                        value=year_str,
                        origin={
                            "sheet": aosr_sheet or "АОСР",
                            "row_index": idx + 1,
                            "row_text": " | ".join(str(c) for c in row if c is not None and str(c).strip()),
                        },
                    )

        if include_somtt_welding:
            for idx, row in enumerate(somtt_rows):
                row_text = " ".join([cell for cell in row if cell]).strip()
                if "вид сварки, применявшиеся при монтаже трубопровода" not in row_text.lower():
                    continue
                values = [cell.strip() for cell in row if cell and cell.strip()]
                candidate = values[1] if len(values) >= 2 else row_text
                parts = [part.strip() for part in candidate.split(",", 1)]
                welding_material = parts[1] if len(parts) == 2 else ""
                log_parsing_event(
                    job_id=job_id,
                    user_log_key=self._user_log_key,
                    source_type="excel",
                    source_file=source_file,
                    parser="ExcelImportService",
                    entity="pipeline_parameters",
                    entity_id=None,
                    field="welding_material",
                    value=welding_material,
                    origin={
                        "sheet": somtt_sheet,
                        "row_index": idx + 1,
                        "row_text": " | ".join(cell for cell in row if cell),
                    },
                )
                break

        if emit_strength_test_rule_log:
            log_parsing_event(
                job_id=job_id,
                user_log_key=self._user_log_key,
                source_type="excel",
                source_file=source_file,
                parser="ExcelImportService",
                entity="pipeline_parameters",
                entity_id=None,
                field="strength_test_result",
                value="выдержал",
                origin={
                    "sheet": aosr_sheet or "АОСР",
                    "row_index": None,
                    "row_text": "constant rule",
                },
                note="set by business rule",
            )

        return {
            "installation_date": installation_date,
            "strength_test_result": "выдержал",
            "welding_material": welding_material,
            "mounting_scheme": mounting_scheme,
            "year": year_str,
        }

    def _extract_flows_from_somtt(
        self,
        rows: list[list[str]],
        flow_context_suffix: str,
        *,
        job_id: int,
        source_file: str,
        somtt_sheet: str,
    ):
        flow_updates = []
        for row_index, row in enumerate(rows, start=1):
            row_text = " ".join([cell for cell in row if cell]).strip()
            if not row_text:
                continue
            # Раньше фильтровали только «линия » — в новых шаблонах направление идёт без «Линия N:»,
            # но с кодом линии в строке (или словом «линия» в другом падеже/без пробела).
            low = row_text.lower()
            if "линия" not in low and not self.pipeline_code_re.search(row_text):
                continue
            parsed = self.flow_direction_parser.try_parse(row_text)
            if parsed is None:
                continue
            if flow_context_suffix:
                parsed.flow_direction_text = f"{parsed.flow_direction_text} {flow_context_suffix}".strip()
            flow_updates.append(parsed)
            log_parsing_event(
                job_id=job_id,
                user_log_key=self._user_log_key,
                source_type="excel",
                source_file=source_file,
                parser="ExcelFlowDirectionParser",
                entity="pipeline",
                entity_id=parsed.pipeline_name,
                field="flow_direction.start",
                value=parsed.flow_direction_text,
                origin={
                    "sheet": somtt_sheet,
                    "row_index": row_index,
                    "row_text": row_text,
                },
            )
        return flow_updates

    def _extract_armature_updates(
        self,
        workbook: dict[str, list[list[str]]],
        registry_sheets: list[str],
        *,
        job_id: int,
        source_file: str,
    ):
        armature_updates = []
        for sheet_name in registry_sheets:
            for row_index, row in enumerate(workbook.get(sheet_name, []), start=1):
                for value in row:
                    raw_value = str(value).strip()
                    parsed = self.armature_parser.try_parse(raw_value)
                    if parsed is not None:
                        armature_updates.append(parsed)
                        log_parsing_event(
                            job_id=job_id,
                            user_log_key=self._user_log_key,
                            source_type="excel",
                            source_file=source_file,
                            parser="ExcelSpecaArmatureParser",
                            entity="armature",
                            entity_id=parsed.source_prefix,
                            field="normalized_name",
                            value=parsed.normalized_name,
                            origin={
                                "sheet": sheet_name,
                                "row_index": row_index,
                                "row_text": raw_value,
                            },
                        )
        return armature_updates

    def _extract_flow_context_suffix(
        self,
        somtt_rows: list[list[str]],
        *,
        job_id: int,
        source_file: str,
        somtt_sheet: str,
    ) -> str:
        building = ""
        axes = ""
        for row_index, row in enumerate(somtt_rows, start=1):
            row_text = " ".join([cell for cell in row if cell]).strip()
            if not row_text:
                continue
            if not building:
                building_match = self.building_re.search(row_text)
                if building_match:
                    building = building_match.group(1).strip().rstrip(".")
                    log_parsing_event(
                        job_id=job_id,
                        user_log_key=self._user_log_key,
                        source_type="excel",
                        source_file=source_file,
                        parser="ExcelImportService",
                        entity="pipeline_context",
                        entity_id=None,
                        field="building",
                        value=building,
                        origin={
                            "sheet": somtt_sheet,
                            "row_index": row_index,
                            "row_text": row_text,
                        },
                    )
            if not axes and row_text.lower().startswith("технологический трубопровод в осях"):
                axes_match = self.axes_re.search(row_text)
                if axes_match:
                    axes = axes_match.group(1).strip().rstrip(".:")
                    log_parsing_event(
                        job_id=job_id,
                        user_log_key=self._user_log_key,
                        source_type="excel",
                        source_file=source_file,
                        parser="ExcelImportService",
                        entity="pipeline_context",
                        entity_id=None,
                        field="axes",
                        value=axes,
                        origin={
                            "sheet": somtt_sheet,
                            "row_index": row_index,
                            "row_text": row_text,
                        },
                    )
            if building and axes:
                break
        if not building and not axes:
            return ""
        return f"({building} {axes})".replace("  ", " ").strip()

    def _extract_valve_notes(
        self,
        rows: list[list[str]],
        *,
        source_sheet: str | None = None,
    ) -> dict[str, dict[str, str | int]]:
        header_idx = -1
        running_idx = -1
        note_idx = -1
        note_score = -1
        for idx, row in enumerate(rows):
            normalized = [self._normalize_header_cell(cell) for cell in row]
            for col_idx, cell in enumerate(normalized):
                if running_idx < 0 and (
                    "unique running number" in cell
                    or "индивидуальный порядковый номер" in cell
                ):
                    running_idx = col_idx
                score = self._score_note_column(cell)
                if score > note_score:
                    note_idx = col_idx
                    note_score = score
            if running_idx >= 0 and note_idx >= 0:
                header_idx = idx
                break

        if header_idx < 0:
            return {}

        notes_by_number: dict[str, dict[str, str | int]] = {}
        for row_index, row in enumerate(rows[header_idx + 1 :], start=header_idx + 2):
            running_value = row[running_idx] if running_idx < len(row) else ""
            note_value = row[note_idx] if note_idx < len(row) else ""
            running_number = self._extract_running_number(running_value)
            note_text = str(note_value).strip() if note_value else ""
            if not running_number or not note_text:
                continue
            entry: dict[str, str | int] = {
                "note": note_text,
                "row_index": row_index,
                "row_text": " | ".join(str(x) for x in row if str(x).strip()),
                "note_col_index": note_idx + 1,
            }
            if source_sheet is not None:
                entry["sheet"] = source_sheet
            notes_by_number[running_number] = entry
        return notes_by_number

    @staticmethod
    def _find_armature_work_table_column_indices(row: list[str]) -> tuple[int, int] | None:
        work_idx = -1
        desc_idx = -1
        normalized = [ExcelImportService._normalize_header_cell(cell) for cell in row]
        for col_idx, cell in enumerate(normalized):
            if work_idx < 0 and "наименование работ" in cell:
                work_idx = col_idx
            if desc_idx < 0 and "описание" in cell:
                desc_idx = col_idx
        if work_idx >= 0 and desc_idx >= 0:
            return work_idx, desc_idx
        return None

    @classmethod
    def _workbook_looks_like_armature_work_table(
        cls,
        workbook: dict[str, list[list[str]]],
        sheet_names: list[str],
    ) -> bool:
        for sheet_name in sheet_names:
            for row in workbook.get(sheet_name, []):
                if cls._find_armature_work_table_column_indices(row) is not None:
                    return True
        return False

    def _extract_armature_notes_from_work_name_table(
        self,
        rows: list[list[str]],
        *,
        source_sheet: str | None = None,
    ) -> dict[str, dict[str, str | int]]:
        header_idx = -1
        work_idx = -1
        desc_idx = -1
        for idx, row in enumerate(rows):
            found = self._find_armature_work_table_column_indices(row)
            if found is not None:
                work_idx, desc_idx = found
                header_idx = idx
                break
        if header_idx < 0:
            return {}

        notes_by_number: dict[str, dict[str, str | int]] = {}
        for row_index, row in enumerate(rows[header_idx + 1 :], start=header_idx + 2):
            work_value = row[work_idx] if work_idx < len(row) else ""
            note_value = row[desc_idx] if desc_idx < len(row) else ""
            note_text = str(note_value).strip() if note_value else ""
            if not note_text:
                continue
            match = self.vor_armature_running_re.search(str(work_value))
            if not match:
                continue
            running_number = match.group(1)
            entry: dict[str, str | int] = {
                "note": note_text,
                "row_index": row_index,
                "row_text": " | ".join(str(x) for x in row if str(x).strip()),
                "note_col_index": desc_idx + 1,
            }
            if source_sheet is not None:
                entry["sheet"] = source_sheet
            notes_by_number[running_number] = entry
        return notes_by_number

    @staticmethod
    def _normalize_header_cell(value: str) -> str:
        return " ".join(str(value or "").lower().replace("\n", " ").split())

    @staticmethod
    def _score_note_column(cell: str) -> int:
        if not cell:
            return -1
        if "note" not in cell:
            return -1
        if "примечание" in cell and "примечания" not in cell:
            return 100
        if "примечан" in cell:
            return 50
        return 1

    def _extract_running_number(self, value: str) -> str:
        if not value:
            return ""
        match = self.running_number_re.search(str(value))
        return match.group(1) if match else ""

    @staticmethod
    def _find_sheet_name(sheet_names: list[str], needle: str) -> str | None:
        normalized_needle = " ".join(needle.lower().split())
        for sheet_name in sheet_names:
            normalized_name = " ".join(sheet_name.lower().split())
            if normalized_needle in normalized_name:
                return sheet_name
        return None

    @staticmethod
    def _find_all_sheet_names(sheet_names: list[str], needle: str) -> list[str]:
        normalized_needle = " ".join(needle.lower().split())
        out: list[str] = []
        for sheet_name in sheet_names:
            normalized_name = " ".join(sheet_name.lower().split())
            if normalized_needle in normalized_name:
                out.append(sheet_name)
        return out

    def _find_all_somtt_like_sheet_names(self, sheet_names: list[str]) -> list[str]:
        """
        Листы данных СоМТТ: классическое имя «…СоМТТ…» или «Свидет.монтаже …»
        (актуальный шаблон вместо отдельного листа «СоМТТ»).
        """
        out: list[str] = []
        seen: set[str] = set()
        for sheet_name in sheet_names:
            if sheet_name in seen:
                continue
            low = " ".join(sheet_name.lower().split())
            if "сомтт" in low:
                seen.add(sheet_name)
                out.append(sheet_name)
                continue
            if "свидет" in low and "монтаж" in low:
                seen.add(sheet_name)
                out.append(sheet_name)
        return out

    def _find_all_aosr_sheet_names(self, sheet_names: list[str]) -> list[str]:
        """
        Все листы АОСР в порядке следования в файле.
        Листы «Реестр …» не включаем — арматура с них обрабатывается отдельно.
        """
        out: list[str] = []
        for sheet_name in sheet_names:
            normalized = " ".join(sheet_name.lower().split())
            if "аоср" not in normalized:
                continue
            if "реестр" in normalized:
                continue
            out.append(sheet_name)
        return out

    @staticmethod
    def _build_per_pipeline_aosr_updates(
        *,
        pipeline_name: str,
        merged_aosr_fallback: dict[str, str],
        aosr_fields_by_pipeline: dict[str, dict[str, str]],
    ) -> tuple[dict[str, str], str, int | None]:
        """
        Для линии, чей код встречается на листе АОСР, дата окончания работ, ПСИ и год
        берутся с этого листа. Для линий только из СоМТТ/реестра (без кода на листах АОСР)
        — первое непустое значение по всем листам АОСР (как раньше). Материал сварки —
        из объединённого импорта (обычно СоМТТ при обработке первого листа АОСР).
        """
        fb = merged_aosr_fallback
        welding = (fb.get("welding_material") or "").strip()
        native = aosr_fields_by_pipeline.get(pipeline_name)
        if native:
            installation_date = (native.get("installation_date") or "").strip()
            mounting_scheme = (native.get("mounting_scheme") or "").strip()
            year_token = (native.get("year") or "").strip()
            strength_test_result = (native.get("strength_test_result") or "").strip() or "выдержал"
        else:
            installation_date = (fb.get("installation_date") or "").strip()
            mounting_scheme = (fb.get("mounting_scheme") or "").strip()
            year_token = (fb.get("year") or "").strip()
            strength_test_result = (fb.get("strength_test_result") or "").strip() or "выдержал"

        parameters_update = {
            "installation_date": installation_date,
            "strength_test_result": strength_test_result,
            "welding_material": welding,
        }
        year_int = int(year_token) if year_token.isdigit() else None
        return parameters_update, mounting_scheme, year_int

    @staticmethod
    def _merge_nonempty_string_dict(target: dict[str, str], addition: dict[str, str]) -> None:
        """Для каждого ключа подставляет значение из addition, если в target ещё пусто."""
        for key, val in addition.items():
            if val is None:
                continue
            if str(target.get(key, "")).strip():
                continue
            stripped = str(val).strip()
            if stripped:
                target[key] = val

    @staticmethod
    def _concat_sheet_rows(
        workbook: dict[str, list[list[str]]],
        sheet_names: list[str],
    ) -> list[list[str]]:
        """Подряд объединяет строки нескольких листов (порядок как в sheet_names)."""
        merged: list[list[str]] = []
        for sn in sheet_names:
            merged.extend(workbook.get(sn, []))
        return merged

    def _collect_pipeline_codes_from_workbook(
        self,
        workbook: dict[str, list[list[str]]],
        sheet_names: list[str],
    ) -> set[str]:
        """
        Имена линий по шаблону pipeline_code_re на указанных листах
        (АОСР, реестр, СоМТТ / «Свидет.монтаже…»).

        Дополняет список линий из блоков «Линия …», когда код встречается в ячейке,
        но строка не проходит фильтр _extract_flows_from_somtt.
        """
        found: set[str] = set()
        for sn in sheet_names:
            for row in workbook.get(sn, []):
                for cell in row:
                    raw = str(cell).strip() if cell is not None else ""
                    if not raw:
                        continue
                    for m in self.pipeline_code_re.finditer(raw.upper()):
                        found.add(m.group(0))
                    for label in collect_pipeline_names_from_cell(raw):
                        if not label:
                            continue
                        if is_cyrillic_line_number(label):
                            found.add(label)
                        else:
                            found.add(
                                normalize_pipeline_code_confusable_o_to_zero(label)
                            )
        return found

    def _parse_installation_date_nearby(self, rows: list[list[str]], anchor_idx: int) -> str:
        nearby_tokens: list[str] = []
        for row in rows[anchor_idx : anchor_idx + 4]:
            nearby_tokens.extend([cell.strip() for cell in row if cell and cell.strip()])
        if not nearby_tokens:
            return ""

        cleaned = [token.strip().strip('"').strip("«»").lower() for token in nearby_tokens]
        for i, token in enumerate(cleaned):
            if not token.isdigit():
                continue
            day = int(token)
            if day < 1 or day > 31:
                continue

            month_idx = i + 1
            while month_idx < len(cleaned) and cleaned[month_idx] in {"", "г", "г.", "."}:
                month_idx += 1
            if month_idx >= len(cleaned) or cleaned[month_idx] not in self.months:
                continue
            month = cleaned[month_idx]

            year_idx = month_idx + 1
            while year_idx < len(cleaned) and not re.fullmatch(r"\d{4}", cleaned[year_idx]):
                year_idx += 1
            if year_idx >= len(cleaned):
                continue

            year = cleaned[year_idx]
            month_num = self.month_numbers.get(month)
            if month_num is None:
                continue
            return f"{day:02d}.{month_num:02d}.{year}г."
        return ""
