from backend.app.domain.parsing.parse_pipeline_from_tables import (
    ParsePipelineFromTables,
    page_from_filename,
)
from backend.app.domain.models.specification import Specification, Pipe
from backend.app.domain.models.table_block import TableBlock
from backend.app.infrastructure.files.pdf.models import PDFTable


def test_page_from_filename_hyphen_dot_underscore():
    assert page_from_filename("12.pdf") == "1"
    assert page_from_filename("12-4.pdf") == "4"
    assert page_from_filename("1-1.pdf") == "1"
    assert page_from_filename("5.1.pdf") == "1"
    assert page_from_filename("5.7.pdf") == "7"
    assert page_from_filename("5,7.pdf") == "7"
    assert page_from_filename("1,2.pdf") == "2"
    assert page_from_filename("5.7") == "7"
    assert page_from_filename(r"D:\x\prefix_5.7.pdf") == "7"
    assert page_from_filename("1.2.3.pdf") == "3"
    assert page_from_filename("export_7.pdf") == "7"
    assert page_from_filename("line-5.7.pdf") == "7"


def test_spec_table_attaches_to_params_pipeline_not_line_in_spec(monkeypatch):
    """
    Таблица kind=spec должна идти на имя линии из kind=params на той же странице,
    даже если в спецификации встречается другая «Линия …».
    """
    use_case = ParsePipelineFromTables()
    monkeypatch.setattr(
        "backend.app.domain.parsing.specification_parser.log_pipeline_row",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "backend.app.domain.parsing.specification_parser.log_parsing_event",
        lambda **_kwargs: None,
    )

    params = PDFTable(
        page="1",
        kind="params",
        rows=[
            ["Наименование линии / класс трубопровода", "P-FROM-PARAMS", "suffix"],
            ["Наименование среды", "Вода"],
        ],
    )
    spec = PDFTable(
        page="1",
        kind="spec",
        rows=[
            ["№п/п", "Наименование", "Ед.", "Кол-во"],
            ["1", "Труба по EN 10217-7 DN50", "м", "2"],
            ["Начало", "Линия OTHER-LINE-SHOULD-NOT-WIN"],
        ],
    )

    use_case.process_tables([params, spec])

    assert set(use_case.pipeline_names()) == {"P-FROM-PARAMS"}
    pl = use_case.get_pipeline("P-FROM-PARAMS")
    assert pl is not None
    assert len(pl.specifications) == 1
    assert len(pl.specifications[0].pipes) >= 1


def test_process_tables_skips_first_row_in_block(monkeypatch):
    use_case = ParsePipelineFromTables()

    table = PDFTable(
        page="6",
        rows=[
            ["HEADER", "NOISE"],
            ["DATA", "VALUE"],
        ],
    )
    block = TableBlock(
        pipeline_name="P-100",
        page="6.1",
        rows=table.rows,
    )

    captured_rows_for_params = []
    captured_rows_for_spec = []

    def fake_split(_):
        return [block]

    def fake_parse_params(rows, pipeline):
        captured_rows_for_params.append(rows)

    def fake_parse_spec(rows, page, pipeline_name):
        captured_rows_for_spec.append(rows)
        return Specification(
            page=page,
            pipes=[Pipe(position=1, name="Pipe", unit="m", quantity=10.0, dimensions="57x3")],
        )

    monkeypatch.setattr(use_case.splitter, "split", fake_split)
    monkeypatch.setattr(use_case.param_parser, "parse", fake_parse_params)
    monkeypatch.setattr(use_case.spec_parser, "parse", fake_parse_spec)

    touched = use_case.process_tables([table])
    pipelines = use_case.snapshot()

    assert captured_rows_for_params == [[["DATA", "VALUE"]]]
    assert captured_rows_for_spec == [[["DATA", "VALUE"]]]
    assert touched == {"P-100": {"6.1"}}
    assert len(pipelines) == 1
    assert pipelines[0].name == "P-100"
    assert use_case.spec_items_count() == 1
