import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from backend.app.application.imports.excel_import_service import ExcelImportService


class _FakeJobService:
    def __init__(self):
        self.created = []

    async def create(self, filename: str, extra: dict | None = None):
        job = SimpleNamespace(id=101, status="pending", filename=filename, extra=extra)
        self.created.append(job)
        return job

    async def start_processing(self, job_id: int):
        return None

    async def update_progress(self, job_id: int, progress: int | None = None, extra: dict | None = None):
        return None

    async def finish(self, job_id: int):
        return None

    async def fail(self, job_id: int, error: str):
        return None


class _FakeSessionCtx:
    class _Session:
        async def commit(self):
            return None

    async def __aenter__(self):
        return self._Session()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return False


class _FakeSessionFactory:
    def __call__(self):
        return _FakeSessionCtx()


@pytest.mark.asyncio
async def test_excel_import_service_start_import_creates_job_and_schedules_background(monkeypatch, tmp_path):
    service = ExcelImportService(
        session_factory=None,
        job_service=_FakeJobService(),
        preview_output_dir=tmp_path,
    )

    excel_path = tmp_path / "1. АОСР test.xlsx"
    excel_path.write_text("stub", encoding="utf-8")

    scheduled = {}

    async def fake_run(job_id: int, path: Path):
        scheduled["job_id"] = job_id
        scheduled["path"] = path

    def fake_create_task(coro):
        scheduled["coro"] = coro
        coro.close()
        return SimpleNamespace()

    monkeypatch.setattr(service, "_run", fake_run)
    monkeypatch.setattr(asyncio, "create_task", fake_create_task)

    job = await service.start_import(excel_path)

    assert job.id == 101
    assert service.job_service.created[0].extra["file_kind"] == "aosr"
    assert "coro" in scheduled


def test_excel_import_service_detect_file_kind():
    assert ExcelImportService.detect_file_kind("1. АОСР 3 этап PSA.xlsx") == "aosr"
    assert ExcelImportService.detect_file_kind("Акт №1ПК2. Линия 41079 (№110).xlsx") == "tests_act"
    assert ExcelImportService.detect_file_kind("5 этап Стилоскопирование.xlsx") == "styloscopy_act"
    assert ExcelImportService.detect_file_kind("ВОР этап 4.xlsx") == "armature_list"
    assert ExcelImportService.detect_file_kind("report.xlsx") == "unknown"


def test_excel_import_service_tests_act_header_variants():
    assert ExcelImportService._is_tests_act_header("АКТ ИСПЫТАНИЙ ТРУБОПРОВОДА")
    assert ExcelImportService._is_tests_act_header("АКТ ИСПЫТАНИЯ ТРУБОПРОВОДА")
    assert not ExcelImportService._is_tests_act_header("АКТ ПРОДУВКИ ТРУБОПРОВОДА")


def test_excel_import_service_detect_ndt_vik_kind_headers():
    service = ExcelImportService(
        session_factory=None,
        job_service=_FakeJobService(),
        preview_output_dir=Path("data/interim/excel_inspect"),
    )
    workbook_uzk = {
        "РК": [[""]] * 12,
    }
    workbook_uzk["РК"][9] = ["по ультразвуковому контролю качества сварных соединений"]
    assert service._detect_ndt_vik_kind(workbook_uzk, ["РК"]) == "uzk_act"

    workbook_pvk = {
        "РК": [[""]] * 12,
    }
    workbook_pvk["РК"][8] = ["по капиллярному контролю сварных соединений и основного металла"]
    assert service._detect_ndt_vik_kind(workbook_pvk, ["РК"]) == "pvk_act"


def test_excel_import_service_detect_file_kind_by_styloscopy_cells():
    service = ExcelImportService(
        session_factory=None,
        job_service=_FakeJobService(),
        preview_output_dir=Path("data/interim/excel_inspect"),
    )
    workbook = {"Лист1": [["Испытательная лаборатория"], [""], [""], [""], [""], [""], [""], ["по контролю химического состава"]]}
    file_kind = service._detect_file_kind("report.xlsx", ["Лист1"], workbook)
    assert file_kind == "styloscopy_act"


def test_excel_import_service_detect_tests_act_from_workbook_without_akt_in_filename():
    """«Испытания.xlsx»: в имени нет подстроки «акт», тип определяется по заголовку 2-й строки."""
    service = ExcelImportService(
        session_factory=None,
        job_service=_FakeJobService(),
        preview_output_dir=Path("data/interim/excel_inspect"),
    )
    assert ExcelImportService.detect_file_kind("Испытания.xlsx") == "unknown"
    workbook = {
        ".": [
            [""] * 5,
            ["  АКТ ИСПЫТАНИЯ ТРУБОПРОВОДА  "],
        ],
    }
    assert service._detect_file_kind("Испытания.xlsx", ["."], workbook) == "tests_act"


def test_excel_import_service_extract_styloscopy_sheet_data():
    service = ExcelImportService(
        session_factory=None,
        job_service=_FakeJobService(),
        preview_output_dir=Path("data/interim/excel_inspect"),
    )
    rows = [[""] * 14 for _ in range(20)]
    rows[6][0] = "ПРОТОКОЛ № ОК 1510/4-25 от 15 октября 2025г."
    rows[12][0] = "Объект контроля: Технологические трубопроводы, линия 29 (YY03-90454-CSC-25-E010H2A00-FC). Категория Аа(1)"
    rows[13][12] = "Соответствие марке стали"
    rows[14][12] = "1.4404 (аналог 03X17H14M3)"
    rows[15][12] = "1.4404 (аналог 03X17H14M3)"
    rows[16][12] = "1.4571 (аналог 10Х17Н13М2Т)"

    extracted = service._extract_styloscopy_sheet_data(rows)

    assert extracted["pipeline_name"] == "YY03-90454-CSC-25-E010H2A00-FC"
    assert extracted["line_number"] == "29"
    assert extracted["protocol_after_no"] == "ОК 1510/4-25 от 15 октября 2025г."
    assert extracted["steel_marks"] == ["EN 1.4404", "EN 1.4571"]


def test_excel_import_service_extract_styloscopy_protocol_fallback_on_sheet():
    service = ExcelImportService(
        session_factory=None,
        job_service=_FakeJobService(),
        preview_output_dir=Path("data/interim/excel_inspect"),
    )
    rows = [[""] * 6 for _ in range(12)]
    rows[10][3] = "ПРОТОКОЛ № 77-25 от 17 октября 2025г."

    assert service._extract_styloscopy_protocol_after_number(rows) == "77-25 от 17 октября 2025г."


def test_excel_import_service_extract_statement_trims_excel_datetime_and_tail():
    service = ExcelImportService(
        session_factory=None,
        job_service=_FakeJobService(),
        preview_output_dir=Path("data/interim/excel_inspect"),
    )

    s1 = service._extract_statement_after_conclusion("ЗАКЛЮЧЕНИЕ № 005/5-2025-10-15 00:00:00")
    s2 = service._extract_statement_after_conclusion("ЗАКЛЮЧЕНИЕ №002/СМУ от 10.11.2025 2,5 (для 10-12мм)")

    assert s1 == "№ 005/5-15.10.2025"
    assert s2 == "№002/СМУ от 10.11.2025"


def test_excel_import_service_extract_pipeline_name_from_noisy_row():
    service = ExcelImportService(
        session_factory=None,
        job_service=_FakeJobService(),
        preview_output_dir=Path("data/interim/excel_inspect"),
    )
    row = ["", "", "", "Гидравлическое масло, линия \nYY03-90051-HML-100-E010H2A00-IE", "", ""]

    parsed = service._extract_pipeline_name_from_row(row, 3, 5)

    assert parsed == "YY03-90051-HML-100-E010H2A00-IE"


def test_excel_import_service_read_workbook(tmp_path):
    excel_path = tmp_path / "test.xlsx"
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        pd.DataFrame([["A", "B"], [1, 2]]).to_excel(writer, sheet_name="S1", index=False, header=False)
        pd.DataFrame([["X"], ["Y"]]).to_excel(writer, sheet_name="S2", index=False, header=False)

    workbook = ExcelImportService._read_workbook(excel_path)

    assert set(workbook.keys()) == {"S1", "S2"}
    assert workbook["S1"][0] == ["A", "B"]
    assert workbook["S2"][1] == ["Y"]


def test_find_all_aosr_sheet_names_skips_registry():
    service = ExcelImportService(
        session_factory=None,
        job_service=_FakeJobService(),
        preview_output_dir=Path("data/interim/excel_inspect"),
    )
    names = ["СоМТТ", "АОСР этап 1", "Реестр арматуры АОСР", "АОСР этап 2"]
    assert service._find_all_aosr_sheet_names(names) == ["АОСР этап 1", "АОСР этап 2"]


def test_find_all_somtt_like_sheet_names_includes_svidet_montage():
    service = ExcelImportService(
        session_factory=None,
        job_service=_FakeJobService(),
        preview_output_dir=Path("data/interim/excel_inspect"),
    )
    names = [
        "АОСР",
        "Свидет.монтаже №1 (1-17)",
        "СоМТТ копия",
        "Свидет.монтаже №2(18-19)",
        "Лист1",
    ]
    assert service._find_all_somtt_like_sheet_names(names) == [
        "Свидет.монтаже №1 (1-17)",
        "СоМТТ копия",
        "Свидет.монтаже №2(18-19)",
    ]


def test_concat_sheet_rows_preserves_order():
    wb = {"A": [["x"]], "B": [["y"], ["z"]]}
    assert ExcelImportService._concat_sheet_rows(wb, ["A", "B"]) == [["x"], ["y"], ["z"]]


def test_collect_pipeline_codes_from_workbook():
    service = ExcelImportService(
        session_factory=None,
        job_service=_FakeJobService(),
        preview_output_dir=Path("."),
    )
    wb = {
        "АОСР №1": [
            ["", "ZZ04-25001-PSU-65-E010H4C03-IP"],
            ["XX02-30273-PSU-50-E010H3A00-IP", "noise"],
        ],
    }
    codes = service._collect_pipeline_codes_from_workbook(wb, ["АОСР №1"])
    assert codes == {"ZZ04-25001-PSU-65-E010H4C03-IP", "XX02-30273-PSU-50-E010H3A00-IP"}


def test_excel_import_service_extract_aosr_parameters():
    service = ExcelImportService(
        session_factory=None,
        job_service=_FakeJobService(),
        preview_output_dir=Path("data/interim/excel_inspect"),
    )
    aosr_rows = [
        ["окончания работ", '"', "7", '"', "февраля", "2025", "г."],
        ["ПСИ00000-1-ТК1; ПСИ00000-2-ТК1.2.ИЧ, выполненный ООО"],
        ["5. Даты: начала работ с 01.01.2024 г."],
    ]
    somtt_rows = [
        ["Вид сварки, применявшиеся при монтаже трубопровода", "РАД, Проволока сварочная Weld T 316LSi2,0х1000"],
    ]

    extracted = service._extract_aosr_parameters(
        aosr_rows=aosr_rows,
        somtt_rows=somtt_rows,
        job_id=0,
        source_file="test.xlsx",
        aosr_sheet="АОСР PSA",
        somtt_sheet="СоМТТ",
    )

    assert extracted["welding_material"] == "Проволока сварочная Weld T 316LSi2,0х1000"
    assert extracted["installation_date"] == "07.02.2025г."
    assert extracted["strength_test_result"] == "выдержал"
    assert extracted["mounting_scheme"] == "ПСИ00000-1-ТК1"
    assert extracted["year"] == "2025"


def test_excel_import_service_extract_mounting_scheme_helper():
    assert (
        ExcelImportService._extract_mounting_scheme_from_aosr_row_concat(
            "ПСИ00000-1-ТК1; ПСИ00000-2-ТК1.2.ИЧ, выполненный ООО",
        )
        == "ПСИ00000-1-ТК1"
    )
    assert ExcelImportService._extract_mounting_scheme_from_aosr_row_concat("не ПСИ") == ""


def test_excel_import_service_extract_flows_from_somtt():
    service = ExcelImportService(
        session_factory=None,
        job_service=_FakeJobService(),
        preview_output_dir=Path("data/interim/excel_inspect"),
    )
    rows = [
        [
            "Линия 1: XX01-41001-PSA-50-E010H2A00-IP: от насоса ...; 0,8 МПа; 5/85°С",
        ],
        [
            "Линия 2: XX01-41011-PSA-100-E010H2A00-IE: от насоса ...; 0,8 МПа; -34/85°С",
        ],
    ]

    extracted = service._extract_flows_from_somtt(
        rows=rows,
        flow_context_suffix="",
        job_id=0,
        source_file="test.xlsx",
        somtt_sheet="СоМТТ",
    )

    names = {item.pipeline_name for item in extracted}
    assert names == {
        "XX01-41001-PSA-50-E010H2A00-IP",
        "XX01-41011-PSA-100-E010H2A00-IE",
    }


@pytest.mark.asyncio
async def test_excel_import_service_process_applies_parameters_to_pipelines_from_same_sheet(monkeypatch, tmp_path):
    workbook = {
        "СоМТТ": [
            ["Вид сварки, применявшиеся при монтаже трубопровода", "РАД, Проволока сварочная Weld T 316LSi2,0х1000"],
            [
                "Линия 1: XX01-41001-PSA-50-E010H2A00-IP: от насоса ...; 0,8 МПа; 5/85°С",
            ],
            [
                "Линия 2: XX01-41011-PSA-100-E010H2A00-IE: от насоса ...; 0,8 МПа; -34/85°С",
            ],
        ],
        "АОСР PSA": [
            ["окончания работ", '"', "7", '"', "февраля", "2025", "г."],
            ["ПСИ00000-1-ТК1; ПСИ00000-2-ТК1.2.ИЧ"],
            ["5. Даты: начала работ с 15.03.2025 г."],
        ],
        "СВОДКА": [
            [
                "XX01-41009-PSL-200-E010H2A00-IE: от линии ...; 0,07 Мпа; -34/85°С",
            ]
        ],
    }

    class RecordingPipelineRepo:
        flow_updates = []
        parameters_updates = []
        aosr_updates = []

        def __init__(self, _session):
            pass

        async def update_flow_direction_from_excel(self, *, pipeline_name: str, flow_direction_text: str, source_raw: str):
            self.flow_updates.append((pipeline_name, flow_direction_text, source_raw))
            return True

        async def update_parameters_from_excel(self, *, pipeline_name: str, parameters_update: dict[str, str]):
            self.parameters_updates.append((pipeline_name, parameters_update))
            return True

        async def update_pipeline_aosr_fields(self, *, pipeline_name: str, mounting_scheme: str | None, year: int | None):
            self.aosr_updates.append(
                {"pipeline_name": pipeline_name, "mounting_scheme": mounting_scheme, "year": year},
            )
            return True

    class RecordingSpecRepo:
        def __init__(self, _session):
            pass

        async def apply_armature_excel_update(self, **kwargs):
            return 0

    service = ExcelImportService(
        session_factory=_FakeSessionFactory(),
        job_service=_FakeJobService(),
        preview_output_dir=tmp_path,
    )

    monkeypatch.setattr(service, "_read_workbook", lambda _path: workbook)
    monkeypatch.setattr(
        "backend.app.application.imports.excel_import_service.PipelineRepository",
        RecordingPipelineRepo,
    )
    monkeypatch.setattr(
        "backend.app.application.imports.excel_import_service.SpecItemRepository",
        RecordingSpecRepo,
    )

    RecordingPipelineRepo.flow_updates = []
    RecordingPipelineRepo.parameters_updates = []
    RecordingPipelineRepo.aosr_updates = []

    await service._process(
        job_id=1,
        excel_path=tmp_path / "1. АОСР 3 этап PSA.xlsx",
        started_at=0.0,
    )

    updated_names = {name for name, _ in RecordingPipelineRepo.parameters_updates}
    assert "XX01-41001-PSA-50-E010H2A00-IP" in updated_names
    assert "XX01-41011-PSA-100-E010H2A00-IE" in updated_names
    # Проверяем, что параметры не "размазываются" на посторонние линии только из сводки.
    assert "XX01-41009-PSL-200-E010H2A00-IE" not in updated_names

    for _, params in RecordingPipelineRepo.parameters_updates:
        assert "mounting_scheme" not in params
        assert "year" not in params
        assert params["welding_material"].startswith("Проволока сварочная")
        assert params["installation_date"] == "07.02.2025г."

    assert len(RecordingPipelineRepo.aosr_updates) == 2
    for u in RecordingPipelineRepo.aosr_updates:
        assert u["mounting_scheme"] == "ПСИ00000-1-ТК1"
        assert u["year"] == 2025


@pytest.mark.asyncio
async def test_excel_import_service_aosr_merges_flow_with_pipeline_codes_on_somtt_cells(
    monkeypatch, tmp_path,
):
    """Код линии в ячейке СоМТТ без подстроки «линия » всё равно получает поля АОСР/параметры."""
    workbook = {
        "СоМТТ": [
            ["Вид сварки, применявшиеся при монтаже трубопровода", "РАД, Проволока сварочная Weld T 316LSi2,0х1000"],
            ["Линия 1: XX01-41001-PSA-50-E010H2A00-IP: от насоса ...; 0,8 МПа; 5/85°С"],
            ["Доп. строка XX01-41011-PSA-100-E010H2A00-IE без ключевого слова"],
        ],
        "АОСР PSA": [
            ["окончания работ", '"', "7", '"', "февраля", "2025", "г."],
            ["ПСИ00000-1-ТК1; ПСИ00000-2-ТК1.2.ИЧ"],
            ["5. Даты: начала работ с 15.03.2025 г."],
        ],
    }

    class RecordingPipelineRepo:
        flow_updates = []
        parameters_updates = []
        aosr_updates = []

        def __init__(self, _session):
            pass

        async def update_flow_direction_from_excel(self, *, pipeline_name: str, flow_direction_text: str, source_raw: str):
            self.flow_updates.append((pipeline_name, flow_direction_text, source_raw))
            return True

        async def update_parameters_from_excel(self, *, pipeline_name: str, parameters_update: dict[str, str]):
            self.parameters_updates.append((pipeline_name, parameters_update))
            return True

        async def update_pipeline_aosr_fields(self, *, pipeline_name: str, mounting_scheme: str | None, year: int | None):
            self.aosr_updates.append(
                {"pipeline_name": pipeline_name, "mounting_scheme": mounting_scheme, "year": year},
            )
            return True

    class RecordingSpecRepo:
        def __init__(self, _session):
            pass

        async def apply_armature_excel_update(self, **kwargs):
            return 0

    service = ExcelImportService(
        session_factory=_FakeSessionFactory(),
        job_service=_FakeJobService(),
        preview_output_dir=tmp_path,
    )

    monkeypatch.setattr(service, "_read_workbook", lambda _path: workbook)
    monkeypatch.setattr(
        "backend.app.application.imports.excel_import_service.PipelineRepository",
        RecordingPipelineRepo,
    )
    monkeypatch.setattr(
        "backend.app.application.imports.excel_import_service.SpecItemRepository",
        RecordingSpecRepo,
    )

    RecordingPipelineRepo.flow_updates = []
    RecordingPipelineRepo.parameters_updates = []
    RecordingPipelineRepo.aosr_updates = []

    await service._process(
        job_id=1,
        excel_path=tmp_path / "1. АОСР 3 этап PSA.xlsx",
        started_at=0.0,
    )

    assert len(RecordingPipelineRepo.flow_updates) == 1
    aosr_names = {u["pipeline_name"] for u in RecordingPipelineRepo.aosr_updates}
    assert aosr_names == {"XX01-41001-PSA-50-E010H2A00-IP", "XX01-41011-PSA-100-E010H2A00-IE"}


@pytest.mark.asyncio
async def test_excel_import_service_process_merges_multiple_aosr_sheets(monkeypatch, tmp_path):
    workbook = {
        "СоМТТ": [
            ["Вид сварки, применявшиеся при монтаже трубопровода", "РАД, Проволока сварочная Weld T 316LSi2,0х1000"],
            [
                "Линия 1: XX01-41001-PSA-50-E010H2A00-IP: от насоса ...; 0,8 МПа; 5/85°С",
            ],
        ],
        "АОСР (1)": [
            ["ПСИ00000-1-ТК1; ПСИ00000-2-ТК1.2.ИЧ"],
        ],
        "АОСР (2)": [
            ["окончания работ", '"', "7", '"', "февраля", "2025", "г."],
            ["5. Даты: начала работ с 15.03.2025 г."],
        ],
    }

    class RecordingPipelineRepo:
        flow_updates = []
        parameters_updates = []
        aosr_updates = []

        def __init__(self, _session):
            pass

        async def update_flow_direction_from_excel(self, *, pipeline_name: str, flow_direction_text: str, source_raw: str):
            self.flow_updates.append((pipeline_name, flow_direction_text, source_raw))
            return True

        async def update_parameters_from_excel(self, *, pipeline_name: str, parameters_update: dict[str, str]):
            self.parameters_updates.append((pipeline_name, parameters_update))
            return True

        async def update_pipeline_aosr_fields(self, *, pipeline_name: str, mounting_scheme: str | None, year: int | None):
            self.aosr_updates.append(
                {"pipeline_name": pipeline_name, "mounting_scheme": mounting_scheme, "year": year},
            )
            return True

    class RecordingSpecRepo:
        def __init__(self, _session):
            pass

        async def apply_armature_excel_update(self, **kwargs):
            return 0

    service = ExcelImportService(
        session_factory=_FakeSessionFactory(),
        job_service=_FakeJobService(),
        preview_output_dir=tmp_path,
    )

    monkeypatch.setattr(service, "_read_workbook", lambda _path: workbook)
    monkeypatch.setattr(
        "backend.app.application.imports.excel_import_service.PipelineRepository",
        RecordingPipelineRepo,
    )
    monkeypatch.setattr(
        "backend.app.application.imports.excel_import_service.SpecItemRepository",
        RecordingSpecRepo,
    )

    RecordingPipelineRepo.flow_updates = []
    RecordingPipelineRepo.parameters_updates = []
    RecordingPipelineRepo.aosr_updates = []

    await service._process(
        job_id=1,
        excel_path=tmp_path / "1. АОСР 2 этап.xlsx",
        started_at=0.0,
    )

    assert len(RecordingPipelineRepo.parameters_updates) == 1
    _, params = RecordingPipelineRepo.parameters_updates[0]
    assert params["installation_date"] == "07.02.2025г."
    assert params["welding_material"].startswith("Проволока сварочная")
    assert len(RecordingPipelineRepo.aosr_updates) == 1
    assert RecordingPipelineRepo.aosr_updates[0]["mounting_scheme"] == "ПСИ00000-1-ТК1"
    assert RecordingPipelineRepo.aosr_updates[0]["year"] == 2025


@pytest.mark.asyncio
async def test_excel_import_service_aosr_installation_date_from_sheet_with_pipeline_code(
    monkeypatch, tmp_path,
):
    """На разных листах АОСР разные даты: линия получает дату с листа, где встречается её код."""
    workbook = {
        "СоМТТ": [
            ["Вид сварки, применявшиеся при монтаже трубопровода", "РАД, Проволока сварочная Weld T 316LSi2,0х1000"],
            ["Линия 1: XX01-41001-PSA-50-E010H2A00-IP: от насоса ...; 0,8 МПа; 5/85°С"],
            ["Линия 2: XX01-41011-PSA-100-E010H2A00-IE: от насоса ...; 0,8 МПа; -34/85°С"],
        ],
        "АОСР (1)": [
            ["окончания работ", '"', "7", '"', "февраля", "2025", "г."],
            ["ПСИ11111-1-ТК1; выполненный ООО", "XX01-41001-PSA-50-E010H2A00-IP"],
            ["5. Даты: начала работ с 01.01.2024 г."],
        ],
        "АОСР (2)": [
            ["окончания работ", '"', "15", '"', "марта", "2026", "г."],
            ["ПСИ22222-2-ТК2; выполненный ООО", "XX01-41011-PSA-100-E010H2A00-IE"],
        ],
    }

    class RecordingPipelineRepo:
        flow_updates = []
        parameters_updates = []
        aosr_updates = []

        def __init__(self, _session):
            pass

        async def update_flow_direction_from_excel(self, *, pipeline_name: str, flow_direction_text: str, source_raw: str):
            self.flow_updates.append((pipeline_name, flow_direction_text, source_raw))
            return True

        async def update_parameters_from_excel(self, *, pipeline_name: str, parameters_update: dict[str, str]):
            self.parameters_updates.append((pipeline_name, parameters_update))
            return True

        async def update_pipeline_aosr_fields(self, *, pipeline_name: str, mounting_scheme: str | None, year: int | None):
            self.aosr_updates.append(
                {"pipeline_name": pipeline_name, "mounting_scheme": mounting_scheme, "year": year},
            )
            return True

    class RecordingSpecRepo:
        def __init__(self, _session):
            pass

        async def apply_armature_excel_update(self, **kwargs):
            return 0

    service = ExcelImportService(
        session_factory=_FakeSessionFactory(),
        job_service=_FakeJobService(),
        preview_output_dir=tmp_path,
    )

    monkeypatch.setattr(service, "_read_workbook", lambda _path: workbook)
    monkeypatch.setattr(
        "backend.app.application.imports.excel_import_service.PipelineRepository",
        RecordingPipelineRepo,
    )
    monkeypatch.setattr(
        "backend.app.application.imports.excel_import_service.SpecItemRepository",
        RecordingSpecRepo,
    )

    RecordingPipelineRepo.flow_updates = []
    RecordingPipelineRepo.parameters_updates = []
    RecordingPipelineRepo.aosr_updates = []

    await service._process(
        job_id=1,
        excel_path=tmp_path / "1. АОСР 2 этап.xlsx",
        started_at=0.0,
    )

    by_name = {name: upd for name, upd in RecordingPipelineRepo.parameters_updates}
    assert by_name["XX01-41001-PSA-50-E010H2A00-IP"]["installation_date"] == "07.02.2025г."
    assert by_name["XX01-41011-PSA-100-E010H2A00-IE"]["installation_date"] == "15.03.2026г."

    aosr_by = {u["pipeline_name"]: u for u in RecordingPipelineRepo.aosr_updates}
    assert aosr_by["XX01-41001-PSA-50-E010H2A00-IP"]["mounting_scheme"] == "ПСИ11111-1-ТК1"
    assert aosr_by["XX01-41001-PSA-50-E010H2A00-IP"]["year"] == 2025
    assert aosr_by["XX01-41011-PSA-100-E010H2A00-IE"]["mounting_scheme"] == "ПСИ22222-2-ТК2"
    assert aosr_by["XX01-41011-PSA-100-E010H2A00-IE"]["year"] == 2026


@pytest.mark.asyncio
async def test_excel_import_service_process_merges_multiple_somtt_sheets(monkeypatch, tmp_path):
    workbook = {
        "СоМТТ (1)": [
            ["Вид сварки, применявшиеся при монтаже трубопровода", "РАД, Проволока сварочная Weld T 316LSi2,0х1000"],
            [
                "Линия 1: XX01-41001-PSA-50-E010H2A00-IP: от насоса ...; 0,8 МПа; 5/85°С",
            ],
        ],
        "СоМТТ (2)": [
            [
                "Линия 2: XX01-41011-PSA-100-E010H2A00-IE: от насоса ...; 0,8 МПа; -34/85°С",
            ],
        ],
        "АОСР": [
            ["окончания работ", '"', "7", '"', "февраля", "2025", "г."],
            ["ПСИ00000-1-ТК1; ПСИ00000-2-ТК1.2.ИЧ"],
        ],
    }

    class RecordingPipelineRepo:
        flow_updates = []
        parameters_updates = []
        aosr_updates = []

        def __init__(self, _session):
            pass

        async def update_flow_direction_from_excel(self, *, pipeline_name: str, flow_direction_text: str, source_raw: str):
            self.flow_updates.append((pipeline_name, flow_direction_text, source_raw))
            return True

        async def update_parameters_from_excel(self, *, pipeline_name: str, parameters_update: dict[str, str]):
            self.parameters_updates.append((pipeline_name, parameters_update))
            return True

        async def update_pipeline_aosr_fields(self, *, pipeline_name: str, mounting_scheme: str | None, year: int | None):
            self.aosr_updates.append(
                {"pipeline_name": pipeline_name, "mounting_scheme": mounting_scheme, "year": year},
            )
            return True

    class RecordingSpecRepo:
        def __init__(self, _session):
            pass

        async def apply_armature_excel_update(self, **kwargs):
            return 0

    service = ExcelImportService(
        session_factory=_FakeSessionFactory(),
        job_service=_FakeJobService(),
        preview_output_dir=tmp_path,
    )

    monkeypatch.setattr(service, "_read_workbook", lambda _path: workbook)
    monkeypatch.setattr(
        "backend.app.application.imports.excel_import_service.PipelineRepository",
        RecordingPipelineRepo,
    )
    monkeypatch.setattr(
        "backend.app.application.imports.excel_import_service.SpecItemRepository",
        RecordingSpecRepo,
    )

    RecordingPipelineRepo.flow_updates = []
    RecordingPipelineRepo.parameters_updates = []
    RecordingPipelineRepo.aosr_updates = []

    await service._process(
        job_id=1,
        excel_path=tmp_path / "1. АОСР merge.xlsx",
        started_at=0.0,
    )

    flow_names = {t[0] for t in RecordingPipelineRepo.flow_updates}
    assert flow_names == {
        "XX01-41001-PSA-50-E010H2A00-IP",
        "XX01-41011-PSA-100-E010H2A00-IE",
    }
    assert len(RecordingPipelineRepo.parameters_updates) == 2


@pytest.mark.asyncio
async def test_excel_import_service_process_aosr_without_somtt_targets_pipelines_by_code(
    monkeypatch, tmp_path
):
    """Книга без СоМТТ: параметры и АОСР-поля применяются к линиям, найденным по коду на листах АОСР."""
    workbook = {
        "АОСР №1": [
            ["окончания работ", '"', "7", '"', "февраля", "2025", "г."],
            ["ПСИ00000-1-ТК1; ПСИ00000-2-ТК1.2.ИЧ"],
            ["", "ZZ04-25001-PSU-65-E010H4C03-IP"],
        ],
    }

    class RecordingPipelineRepo:
        flow_updates = []
        parameters_updates = []
        aosr_updates = []

        def __init__(self, _session):
            pass

        async def update_flow_direction_from_excel(self, *, pipeline_name: str, flow_direction_text: str, source_raw: str):
            self.flow_updates.append((pipeline_name, flow_direction_text, source_raw))
            return True

        async def update_parameters_from_excel(self, *, pipeline_name: str, parameters_update: dict[str, str]):
            self.parameters_updates.append((pipeline_name, parameters_update))
            return True

        async def update_pipeline_aosr_fields(self, *, pipeline_name: str, mounting_scheme: str | None, year: int | None):
            self.aosr_updates.append(
                {"pipeline_name": pipeline_name, "mounting_scheme": mounting_scheme, "year": year},
            )
            return True

    class RecordingSpecRepo:
        def __init__(self, _session):
            pass

        async def apply_armature_excel_update(self, **kwargs):
            return 0

    service = ExcelImportService(
        session_factory=_FakeSessionFactory(),
        job_service=_FakeJobService(),
        preview_output_dir=tmp_path,
    )

    monkeypatch.setattr(service, "_read_workbook", lambda _path: workbook)
    monkeypatch.setattr(
        "backend.app.application.imports.excel_import_service.PipelineRepository",
        RecordingPipelineRepo,
    )
    monkeypatch.setattr(
        "backend.app.application.imports.excel_import_service.SpecItemRepository",
        RecordingSpecRepo,
    )

    RecordingPipelineRepo.flow_updates = []
    RecordingPipelineRepo.parameters_updates = []
    RecordingPipelineRepo.aosr_updates = []

    await service._process(
        job_id=1,
        excel_path=tmp_path / "report.xlsx",
        started_at=0.0,
    )

    assert not RecordingPipelineRepo.flow_updates
    names = {u["pipeline_name"] for u in RecordingPipelineRepo.aosr_updates}
    assert names == {"ZZ04-25001-PSU-65-E010H4C03-IP"}
    assert RecordingPipelineRepo.aosr_updates[0]["mounting_scheme"] == "ПСИ00000-1-ТК1"
    assert RecordingPipelineRepo.aosr_updates[0]["year"] == 2025


@pytest.mark.asyncio
async def test_pipeline_repo_update_aosr_fields_skips_nonempty_mounting():
    from unittest.mock import AsyncMock

    from backend.app.infrastructure.repositories.pipeline_repository import PipelineRepository

    orm = SimpleNamespace(mounting_scheme="KEEP", year=None)
    repo = PipelineRepository.__new__(PipelineRepository)
    repo.session = None
    repo._pipeline_cache = {}
    repo._get_pipeline_orm = AsyncMock(return_value=orm)

    changed = await repo.update_pipeline_aosr_fields(
        pipeline_name="P",
        mounting_scheme="ПСИ999",
        year=2025,
    )
    assert changed is True
    assert orm.mounting_scheme == "KEEP"
    assert orm.year == 2025


@pytest.mark.asyncio
async def test_pipeline_repo_update_aosr_fields_skips_nonempty_year():
    from unittest.mock import AsyncMock

    from backend.app.infrastructure.repositories.pipeline_repository import PipelineRepository

    orm = SimpleNamespace(mounting_scheme="", year=2019)
    repo = PipelineRepository.__new__(PipelineRepository)
    repo.session = None
    repo._pipeline_cache = {}
    repo._get_pipeline_orm = AsyncMock(return_value=orm)

    changed = await repo.update_pipeline_aosr_fields(
        pipeline_name="P",
        mounting_scheme="ПСИ00000-1-ТК1",
        year=2025,
    )
    assert changed is True
    assert orm.mounting_scheme == "ПСИ00000-1-ТК1"
    assert orm.year == 2019


@pytest.mark.asyncio
async def test_excel_import_service_process_tests_act_updates_strength_duration(monkeypatch, tmp_path):
    workbook = {
        "Лист1": [
            [""],
        ] * 40
    }
    workbook["Лист1"][1] = ["АКТ ИСПЫТАНИЙ ТРУБОПРОВОДА"]
    workbook["Лист1"][24] = ["Испытание проводилось способом гидравлическим и пневматическим"]
    workbook["Лист1"][27] = ["", "Линия 41079 (№110)"]
    workbook["Лист1"][29] = ["Испытание проводилось водой очищенной"]
    workbook["Лист1"][32] = ["на прочность давлением 2,4 МПа"]
    workbook["Лист1"][36] = ["Продолжительность испытания 30 мин"]

    class RecordingPipelineRepo:
        parameters_updates = []

        def __init__(self, _session):
            pass

        async def update_parameters_from_excel(self, *, pipeline_name: str, parameters_update: dict[str, str]):
            self.parameters_updates.append((pipeline_name, parameters_update))
            return True

    class RecordingSpecRepo:
        def __init__(self, _session):
            pass

    service = ExcelImportService(
        session_factory=_FakeSessionFactory(),
        job_service=_FakeJobService(),
        preview_output_dir=tmp_path,
    )
    monkeypatch.setattr(service, "_read_workbook", lambda _path: workbook)
    monkeypatch.setattr(
        "backend.app.application.imports.excel_import_service.PipelineRepository",
        RecordingPipelineRepo,
    )
    monkeypatch.setattr(
        "backend.app.application.imports.excel_import_service.SpecItemRepository",
        RecordingSpecRepo,
    )

    await service._process(
        job_id=1,
        excel_path=tmp_path / "Акт №1ПК2. Линия 41079 (№110).xlsx",
        started_at=0.0,
    )

    assert RecordingPipelineRepo.parameters_updates == [
        (
            "41079",
            {
                "strength_test_type": "гидравлическим, пневматическим",
                "strength_test_method": "водой очищенной",
                "strength_test_pressure": "2,4 МПа",
                "strength_test_duration": "30",
            },
        )
    ]


def _tests_act_sheet_rows(
    *,
    pipeline_line: str,
    duration: str = "30 мин",
) -> list[list[str]]:
    rows = [[""]] * 40
    rows[1] = ["АКТ ИСПЫТАНИЙ ТРУБОПРОВОДА"]
    rows[24] = ["Испытание проводилось способом гидравлическим"]
    rows[27] = ["", pipeline_line]
    rows[29] = ["Испытание проводилось водой очищенной"]
    rows[32] = ["на прочность давлением 2,4 МПа"]
    rows[36] = [f"Продолжительность испытания {duration}"]
    return rows


@pytest.mark.asyncio
async def test_excel_import_service_process_tests_act_all_sheets(monkeypatch, tmp_path):
    workbook = {
        "Лист1": _tests_act_sheet_rows(pipeline_line="Линия 41079 (№110)"),
        "Лист2": _tests_act_sheet_rows(
            pipeline_line="Линия 42080 (№111)",
            duration="45 мин",
        ),
    }

    class RecordingPipelineRepo:
        parameters_updates = []

        def __init__(self, _session):
            pass

        async def update_parameters_from_excel(self, *, pipeline_name: str, parameters_update: dict[str, str]):
            self.parameters_updates.append((pipeline_name, parameters_update))
            return True

    class RecordingSpecRepo:
        def __init__(self, _session):
            pass

    service = ExcelImportService(
        session_factory=_FakeSessionFactory(),
        job_service=_FakeJobService(),
        preview_output_dir=tmp_path,
    )
    monkeypatch.setattr(service, "_read_workbook", lambda _path: workbook)
    monkeypatch.setattr(
        "backend.app.application.imports.excel_import_service.PipelineRepository",
        RecordingPipelineRepo,
    )
    monkeypatch.setattr(
        "backend.app.application.imports.excel_import_service.SpecItemRepository",
        RecordingSpecRepo,
    )

    await service._process(
        job_id=1,
        excel_path=tmp_path / "Испытания.xlsx",
        started_at=0.0,
    )

    assert [name for name, _ in RecordingPipelineRepo.parameters_updates] == ["41079", "42080"]
    assert RecordingPipelineRepo.parameters_updates[1][1]["strength_test_duration"] == "45"


@pytest.mark.asyncio
async def test_excel_import_service_process_tests_act_skips_non_tests_header(monkeypatch, tmp_path):
    workbook = {
        "Лист1": [
            [""],
        ] * 40
    }
    workbook["Лист1"][1] = ["АКТ ПРОДУВКИ ТРУБОПРОВОДА"]
    workbook["Лист1"][24] = ["Испытание проводилось способом гидравлическим"]
    workbook["Лист1"][27] = ["", "Линия 41079 (№110)"]
    workbook["Лист1"][29] = ["Испытание проводилось водой очищенной"]
    workbook["Лист1"][32] = ["на прочность давлением 2,4 МПа"]
    workbook["Лист1"][36] = ["Продолжительность испытания 30 мин"]

    class RecordingPipelineRepo:
        parameters_updates = []

        def __init__(self, _session):
            pass

        async def update_parameters_from_excel(self, *, pipeline_name: str, parameters_update: dict[str, str]):
            self.parameters_updates.append((pipeline_name, parameters_update))
            return True

    class RecordingSpecRepo:
        def __init__(self, _session):
            pass

    service = ExcelImportService(
        session_factory=_FakeSessionFactory(),
        job_service=_FakeJobService(),
        preview_output_dir=tmp_path,
    )
    monkeypatch.setattr(service, "_read_workbook", lambda _path: workbook)
    monkeypatch.setattr(
        "backend.app.application.imports.excel_import_service.PipelineRepository",
        RecordingPipelineRepo,
    )
    monkeypatch.setattr(
        "backend.app.application.imports.excel_import_service.SpecItemRepository",
        RecordingSpecRepo,
    )

    await service._process(
        job_id=1,
        excel_path=tmp_path / "Акт продувки.xlsx",
        started_at=0.0,
    )

    assert RecordingPipelineRepo.parameters_updates == []


@pytest.mark.asyncio
async def test_excel_import_service_process_uzk_act_upserts_vik_type(monkeypatch, tmp_path):
    workbook = {"РК": [[""]] * 20}
    workbook["РК"][9] = ["по ультразвуковому контролю качества сварных соединений"]
    workbook["РК"][8] = ["ЗАКЛЮЧЕНИЕ 001-07.08.25"]
    workbook["РК"][16] = ["", "", "", "41081", "A"]

    captured_rows = []

    upsert_flags = {}

    async def fake_upsert(_session_factory, rows, *, replace_existing_for_pipe_type=False):
        captured_rows.extend(rows)
        upsert_flags["replace_existing_for_pipe_type"] = replace_existing_for_pipe_type
        return {"processed_total": len(rows), "pipelines_found": 1, "inserted_total": 1, "duplicates_total": 0, "not_found_total": 0}

    service = ExcelImportService(
        session_factory=_FakeSessionFactory(),
        job_service=_FakeJobService(),
        preview_output_dir=tmp_path,
    )
    monkeypatch.setattr(service, "_read_workbook", lambda _path: workbook)
    monkeypatch.setattr(
        "backend.app.application.imports.excel_import_service.upsert_vik_entries",
        fake_upsert,
    )

    await service._process(
        job_id=1,
        excel_path=tmp_path / "001 УЗК.xlsx",
        started_at=0.0,
    )

    assert captured_rows == [
        {
            "pipe_num": "41081 A",
            "statement_text": "001-07.08.25",
            "type": "УЗК",
        }
    ]
    assert upsert_flags["replace_existing_for_pipe_type"] is True


@pytest.mark.asyncio
async def test_excel_import_service_process_pvk_act_upserts_vik_type(monkeypatch, tmp_path):
    workbook = {"РК": [[""]] * 21}
    workbook["РК"][8] = ["по капиллярному контролю сварных соединений и основного металла"]
    workbook["РК"][7] = ["ЗАКЛЮЧЕНИЕ 002"]
    workbook["РК"][9] = ["07.08.25"]
    workbook["РК"][17] = ["", "", "", "41082", "B", "C"]

    captured_rows = []

    upsert_flags = {}

    async def fake_upsert(_session_factory, rows, *, replace_existing_for_pipe_type=False):
        captured_rows.extend(rows)
        upsert_flags["replace_existing_for_pipe_type"] = replace_existing_for_pipe_type
        return {"processed_total": len(rows), "pipelines_found": 1, "inserted_total": 1, "duplicates_total": 0, "not_found_total": 0}

    service = ExcelImportService(
        session_factory=_FakeSessionFactory(),
        job_service=_FakeJobService(),
        preview_output_dir=tmp_path,
    )
    monkeypatch.setattr(service, "_read_workbook", lambda _path: workbook)
    monkeypatch.setattr(
        "backend.app.application.imports.excel_import_service.upsert_vik_entries",
        fake_upsert,
    )

    await service._process(
        job_id=1,
        excel_path=tmp_path / "002.xlsx",
        started_at=0.0,
    )

    assert captured_rows == [
        {
            "pipe_num": "41082 B C",
            "statement_text": "002-07.08.25",
            "type": "ПВК",
        }
    ]
    assert upsert_flags["replace_existing_for_pipe_type"] is True


@pytest.mark.asyncio
async def test_excel_import_service_process_styloscopy_act_upserts_en_marks(monkeypatch, tmp_path):
    rows = [[""] * 14 for _ in range(20)]
    rows[0][0] = "Испытательная лаборатория"
    rows[6][0] = "ПРОТОКОЛ № ОК 1510/4-25 от 15 октября 2025г."
    rows[12][0] = "Объект контроля: Технологические трубопроводы, линия 29 (YY03-90454-CSC-25-E010H2A00-FC). Категория Аа(1)"
    rows[13][12] = "Соответствие марке стали"
    rows[14][12] = "1.4404 (аналог 03X17H14M3)"
    rows[15][12] = "1.4571 (аналог 10Х17Н13М2Т)"
    workbook = {"Sheet1": rows}

    captured_rows = []
    upsert_flags = {}

    async def fake_upsert(_session_factory, payload, *, replace_existing_for_pipe_type=False):
        captured_rows.extend(payload)
        upsert_flags["replace_existing_for_pipe_type"] = replace_existing_for_pipe_type
        return {
            "processed_total": len(payload),
            "pipelines_found": 1,
            "inserted_total": 1,
            "duplicates_total": 0,
            "not_found_total": 0,
        }

    service = ExcelImportService(
        session_factory=_FakeSessionFactory(),
        job_service=_FakeJobService(),
        preview_output_dir=tmp_path,
    )
    monkeypatch.setattr(service, "_read_workbook", lambda _path: workbook)
    monkeypatch.setattr(
        "backend.app.application.imports.excel_import_service.upsert_vik_entries",
        fake_upsert,
    )

    await service._process(
        job_id=1,
        excel_path=tmp_path / "5 этап Стилоскопирование.xlsx",
        started_at=0.0,
    )

    assert len(captured_rows) == 1
    assert captured_rows[0]["pipe_num"] == "YY03-90454-CSC-25-E010H2A00-FC"
    assert captured_rows[0]["type"] == "СТИЛОСКОПИРОВАНИЕ"
    payload = json.loads(captured_rows[0]["statement_text"])
    assert payload["protocol_after_no"] == "ОК 1510/4-25 от 15 октября 2025г."
    assert payload["steel_marks"] == "EN 1.4404, EN 1.4571"
    assert upsert_flags["replace_existing_for_pipe_type"] is True


def test_excel_import_service_extract_armature_notes_from_work_name_table():
    service = ExcelImportService(
        session_factory=None,
        job_service=_FakeJobService(),
        preview_output_dir=Path("data/interim/excel_inspect"),
    )
    rows = [
        ["", "Наименование работ", "", "", "", "Описание"],
        ["1", "Прокладка трубопровода", "", "", "", ""],
        ["2", "Установка арматуры YY03-V90110 тип X", "", "", "", "Задвижка Ду100 Ру16"],
        ["3", "Категория Б — общие работы", "", "", "", ""],
        ["4", "YY03-v88888 установка", "", "", "", "Клапан обратный"],
    ]
    out = service._extract_armature_notes_from_work_name_table(rows, source_sheet="ВОР")
    assert set(out.keys()) == {"90110", "88888"}
    assert out["90110"]["note"] == "Задвижка Ду100 Ру16"
    assert out["90110"]["sheet"] == "ВОР"
    assert out["88888"]["note"] == "Клапан обратный"


def test_excel_import_service_extract_running_number_audit_like_tags():
    """Форматы тегов как в parsing_audit (unicode −, суффикс .n после номера)."""
    service = ExcelImportService(
        session_factory=None,
        job_service=_FakeJobService(),
        preview_output_dir=Path("data/interim/excel_inspect"),
    )
    assert service._extract_running_number("EW12\u2212V56560") == "56560"
    assert service._extract_running_number("EW12-V56655.4") == "56655"
    assert service._extract_running_number("TM50\u2212V57031") == "57031"
    assert service._extract_running_number("WW05-V95285.1") == "95285"


def test_excel_import_service_detect_file_kind_vor_workbook_structure():
    service = ExcelImportService(
        session_factory=None,
        job_service=_FakeJobService(),
        preview_output_dir=Path("data/interim/excel_inspect"),
    )
    workbook = {
        "Лист1": [
            ["", "Наименование работ", "Описание"],
            ["", "YY03-V90110", "Примечание к арматуре"],
        ],
    }
    assert service._detect_file_kind("generic_report.xlsx", ["Лист1"], workbook) == "armature_list"
