from backend.app.domain.parsing.csv_block_splitter import CSVBlockSplitter
from backend.app.domain.excel_parsing.excel_flow_direction_parser import ExcelFlowDirectionParser
from backend.app.shared.http_content_disposition import attachment_content_disposition
from backend.app.shared.pipeline_name_extract import (
    collect_pipeline_names_from_cell,
    extract_pipeline_name_from_cell,
    looks_like_pipeline_code,
)


def test_extract_pipeline_name_from_cell_line_label():
    assert extract_pipeline_name_from_cell("Линия ТТ5") == "ТТ5"
    assert extract_pipeline_name_from_cell("  линия тт5  ") == "тт5"


def test_extract_pipeline_name_from_cell_strips_installation_description():
    assert extract_pipeline_name_from_cell("Линия ТТ5 Выпарная установка") == "ТТ5"


def test_extract_pipeline_name_from_cell_without_linia_word_in_name():
    assert extract_pipeline_name_from_cell("Линия ТТ5") != "Линия"
    assert extract_pipeline_name_from_cell("Линия ТТ5") != "Линия ТТ5"
    assert extract_pipeline_name_from_cell("Линия ТТ5") != "ТТ5 Выпарная установка"


def test_extract_pipeline_name_from_cell_keeps_code():
    code = "XX01-41086-WSL-50-E010H2A00"
    assert extract_pipeline_name_from_cell(code) == code
    assert looks_like_pipeline_code(code)


def test_collect_pipeline_names_from_cell_mixed():
    names = collect_pipeline_names_from_cell("Линия ТТ5, линия В-12")
    assert "ТТ5" in names
    assert "В-12" in names
    assert "Линия" not in names


def test_csv_block_splitter_finds_line_label_in_params_cell():
    rows = [
        ["Наименование линии / класс трубопровода", "Линия ТТ5 Выпарная установка", ""],
        ["Наименование среды", "Вода"],
    ]
    name, _page = CSVBlockSplitter._find_pipeline_in_table(rows)
    assert name == "ТТ5"


def test_excel_flow_direction_parser_line_label_with_colon():
    parsed = ExcelFlowDirectionParser.try_parse(
        "Линия ТТ5: от узла 1 до узла 2"
    )
    assert parsed is not None
    assert parsed.pipeline_name == "ТТ5"
    assert "узла 1" in parsed.flow_direction_text


def test_attachment_content_disposition_utf8():
    headers = attachment_content_disposition("ТТ5.docx")
    value = headers["Content-Disposition"]
    assert "filename*=" in value
    assert "UTF-8" in value
