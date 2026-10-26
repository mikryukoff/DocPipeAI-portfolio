from backend.app.domain.excel_parsing.excel_flow_direction_parser import (
    ExcelFlowDirectionParser,
)


def test_excel_flow_direction_parser_parses_summary_row():
    raw = (
        "XX01-41009-PSL-200-E010H2A00-IE: "
        "от линии XX01-41009-PSL-200-E010H2A00-IP до питающего бака резервуара XX01-ТК005 "
        "(наружная установка); 0,07 Мпа; -34/85°С"
    )

    parsed = ExcelFlowDirectionParser.try_parse(raw)

    assert parsed is not None
    assert parsed.pipeline_name == "XX01-41009-PSL-200-E010H2A00-IE"
    assert (
        parsed.flow_direction_text
        == "от линии XX01-41009-PSL-200-E010H2A00-IP до питающего бака резервуара XX01-ТК005 (наружная установка)"
    )


def test_excel_flow_direction_parser_ignores_non_matching_rows():
    assert ExcelFlowDirectionParser.try_parse("Просто текст без структуры") is None
    assert ExcelFlowDirectionParser.try_parse("XX01-41009-PSL-200-E010H2A00-IE: ;") is None


def test_excel_flow_direction_parser_parses_line_with_prefix():
    raw = (
        "Линия 1: XX01-41001-PSA-50-E010H2A00-IP: "
        "от насоса насосной станции XX01-PU007 до коллектора XX01-LA001 (штуцер N2); "
        "0,8 МПа; 5/85°С"
    )

    parsed = ExcelFlowDirectionParser.try_parse(raw)

    assert parsed is not None
    assert parsed.pipeline_name == "XX01-41001-PSA-50-E010H2A00-IP"
    assert parsed.flow_direction_text.startswith("от насоса насосной станции")


def test_excel_flow_direction_parser_parses_without_semicolon_after_colon():
    raw = (
        "WW05-95468-WSL-50-E010H2A00: "
        "от Установки SF12 Линия WW05-95465-WSL-80-E010H2A00-IE до глухого фланца (коллектор)"
    )
    parsed = ExcelFlowDirectionParser.try_parse(raw)
    assert parsed is not None
    assert parsed.pipeline_name == "WW05-95468-WSL-50-E010H2A00"
    assert "от Установки SF12" in parsed.flow_direction_text


def test_excel_flow_direction_parser_parses_code_then_ot_without_colon():
    raw = (
        "Технологический трубопровод WW05-95657-WSL-25-E010H2A00 "
        "от Установки AG11 до фильтра очистки"
    )
    parsed = ExcelFlowDirectionParser.try_parse(raw)
    assert parsed is not None
    assert parsed.pipeline_name == "WW05-95657-WSL-25-E010H2A00"
    assert parsed.flow_direction_text.startswith("от Установки AG11")
