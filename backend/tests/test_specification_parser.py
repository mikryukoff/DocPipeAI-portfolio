from backend.app.domain.models.spec_section import SpecSection
from backend.app.domain.parsing.specification_parser import SpecificationParser


def test_specification_parser_does_not_warn_on_positions_gap(monkeypatch):
    parser = SpecificationParser()

    monkeypatch.setattr(
        parser,
        "_resolve_section_by_name",
        lambda _full_name: (SpecSection.PIPES, None),
    )
    monkeypatch.setattr(
        "backend.app.domain.parsing.specification_parser.log_pipeline_row",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "backend.app.domain.parsing.specification_parser.log_parsing_event",
        lambda **_kwargs: None,
    )

    spec = parser.parse(
        rows=[
            ["1", "Труба EN 10217-7 60,3х3,2", "м", "10"],
            ["2", "Труба EN 10217-7 76,1х3,2", "м", "20"],
            ["4", "Колено 90 EN 10253-4", "шт", "2"],
        ],
        page="1",
        pipeline_name="P-100",
    )
    warnings = parser.pop_warnings()

    assert len(spec.pipes) == 3
    assert not any(w.get("error") == "spec_positions_gap" for w in warnings)


def test_specification_parser_stops_on_merged_table_crop_blob_without_warning(monkeypatch):
    parser = SpecificationParser()

    monkeypatch.setattr(
        parser,
        "_resolve_section_by_name",
        lambda _full_name: (SpecSection.PIPES, None),
    )
    monkeypatch.setattr(
        "backend.app.domain.parsing.specification_parser.log_pipeline_row",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "backend.app.domain.parsing.specification_parser.log_parsing_event",
        lambda **_kwargs: None,
    )

    merged_blob = (
        "Трубы Труба по EN ISO 1127, материал: EN 1.4404 по EN 10217-7, DN33,7x2 м 0.5 "
        "Труба по EN ISO 1127, материал: EN 1.4404 по EN 10217-7, DN114,3x3,2 м 16.1 "
        "Соединительные детали трубопроводов Заглушка фланцевая тип 05 по EN 1092-1 шт. 1 "
        "Колено 90° по EN 10253-4 3D, материал: EN 1.4404 6 по EN 10217-7, 33,7х2 шт. 1 "
        "Фланцы Фланец тип 02/35 по EN 1092-1, DN25 PN16 шт. 1 "
        "Опоры Опора хомутовая ОПХ2-150-114,3 шт. 2"
    )

    spec = parser.parse(
        rows=[
            ["1", "Труба EN 10217-7 60,3х3,2", "м", "10"],
            [merged_blob, "Трубы"],
            ["2", "Труба EN 10217-7 76,1х3,2", "м", "20"],
        ],
        page="2",
        pipeline_name="P-MERGE-BLOB",
    )
    warnings = parser.pop_warnings()

    assert len(spec.pipes) == 1
    assert not any(
        w.get("error") == "spec_position_missing_or_invalid" for w in warnings
    )


def test_specification_parser_stops_on_weld_joints_summary_without_warning(monkeypatch):
    parser = SpecificationParser()

    monkeypatch.setattr(
        parser,
        "_resolve_section_by_name",
        lambda _full_name: (SpecSection.PIPES, None),
    )
    monkeypatch.setattr(
        "backend.app.domain.parsing.specification_parser.log_pipeline_row",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "backend.app.domain.parsing.specification_parser.log_parsing_event",
        lambda **_kwargs: None,
    )

    spec = parser.parse(
        rows=[
            ["1", "Труба EN 10217-7 60,3х3,2", "м", "10"],
            ["Общее кол-во стыков, шт.", "5", "", ""],
            ["2", "Труба EN 10217-7 76,1х3,2", "м", "20"],
        ],
        page="4",
        pipeline_name="P-500",
    )
    warnings = parser.pop_warnings()

    assert len(spec.pipes) == 1
    assert not any(
        w.get("error") == "spec_position_missing_or_invalid" for w in warnings
    )


def test_specification_parser_warns_on_fragmented_non_numbered_row(monkeypatch):
    parser = SpecificationParser()

    monkeypatch.setattr(
        parser,
        "_resolve_section_by_name",
        lambda _full_name: (SpecSection.PIPES, None),
    )
    monkeypatch.setattr(
        "backend.app.domain.parsing.specification_parser.log_pipeline_row",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "backend.app.domain.parsing.specification_parser.log_parsing_event",
        lambda **_kwargs: None,
    )

    spec = parser.parse(
        rows=[
            ["1", "Колено 90° по EN 10253-4 3D, материал: EN 1.4541", "шт", "2"],
            ["по EN 10217-7, 60,3х3,2", "", "", ""],
            ["2", "Труба EN 10217-7 60,3х3,2", "м", "3"],
        ],
        page="2",
        pipeline_name="P-200",
    )
    warnings = parser.pop_warnings()

    assert len(spec.pipes) == 2
    assert any(
        w.get("error") == "spec_position_missing_or_invalid" for w in warnings
    )


def test_specification_parser_accepts_fractional_position_tokens(monkeypatch):
    parser = SpecificationParser()

    monkeypatch.setattr(
        parser,
        "_resolve_section_by_name",
        lambda _full_name: (SpecSection.PIPES, None),
    )
    monkeypatch.setattr(
        "backend.app.domain.parsing.specification_parser.log_pipeline_row",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "backend.app.domain.parsing.specification_parser.log_parsing_event",
        lambda **_kwargs: None,
    )

    spec = parser.parse(
        rows=[
            ["3.1", "Труба EN 10217-7 60,3х3,2", "м", "1.2"],
            ["3,2", "Труба EN 10217-7 76,1х3,2", "м", "2.5"],
        ],
        page="3",
        pipeline_name="P-300",
    )
    warnings = parser.pop_warnings()

    assert len(spec.pipes) == 2
    assert spec.pipes[0].position == 3
    assert spec.pipes[1].position == 3
    assert not any(
        w.get("error") == "spec_position_missing_or_invalid" for w in warnings
    )


def test_specification_parser_accepts_multi_level_position_tokens(monkeypatch):
    """Позиции вида 3.2.1, 14.2.1 — иерархические подномера в спецификации."""
    parser = SpecificationParser()

    monkeypatch.setattr(
        parser,
        "_resolve_section_by_name",
        lambda _full_name: (SpecSection.CONNECTION_PARTS, None),
    )
    monkeypatch.setattr(
        "backend.app.domain.parsing.specification_parser.log_pipeline_row",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "backend.app.domain.parsing.specification_parser.log_parsing_event",
        lambda **_kwargs: None,
    )

    spec = parser.parse(
        rows=[
            ["3.2.1", "Отвод 90 - 26.9 х 3.2", "шт", "4"],
            ["3.7.1", "Отвод 90 - 76.1 х 5", "шт", "2"],
            ["14.2.1", "Шаровой стальной кран фланцевый с рукояткой Dy 20 PN25", "шт", "2"],
        ],
        page="1",
        pipeline_name="№С",
    )
    warnings = parser.pop_warnings()

    assert len(spec.connection_parts) == 3
    assert spec.connection_parts[0].position == 3
    assert spec.connection_parts[1].position == 3
    assert spec.connection_parts[2].position == 14
    assert not any(
        w.get("error") == "spec_position_missing_or_invalid" for w in warnings
    )


def test_specification_parser_accepts_slash_subposition(monkeypatch):
    """Позиции вида 3/1 (как 3.1) — основной номер для группировки."""
    parser = SpecificationParser()

    monkeypatch.setattr(
        "backend.app.domain.parsing.specification_parser.log_pipeline_row",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "backend.app.domain.parsing.specification_parser.log_parsing_event",
        lambda **_kwargs: None,
    )

    spec = parser.parse(
        rows=[
            ["3/1", "Труба по EN 10217-7 DN50", "м", "1"],
            ["10/2", "Труба по EN 10217-7 DN80", "м", "2"],
        ],
        page="1",
        pipeline_name="P-SLASH",
    )
    warnings = parser.pop_warnings()

    assert len(spec.pipes) == 2
    assert spec.pipes[0].position == 3
    assert spec.pipes[1].position == 10
    assert not any(
        w.get("error") == "spec_position_missing_or_invalid" for w in warnings
    )


def test_specification_parser_warns_when_item_name_does_not_start_with_letter(monkeypatch):
    parser = SpecificationParser()

    monkeypatch.setattr(
        parser,
        "_resolve_section_by_name",
        lambda _full_name: (SpecSection.PIPES, None),
    )
    monkeypatch.setattr(
        "backend.app.domain.parsing.specification_parser.log_pipeline_row",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "backend.app.domain.parsing.specification_parser.log_parsing_event",
        lambda **_kwargs: None,
    )

    spec = parser.parse(
        rows=[
            ["1", "Труба EN 10217-7 60,3х3,2", "м", "1.0"],
            ["2", "123 Труба EN 10217-7 76,1х3,2", "м", "1.5"],
        ],
        page="4",
        pipeline_name="P-400",
    )
    warnings = parser.pop_warnings()

    assert len(spec.pipes) == 1
    assert any(
        w.get("error") == "spec_item_name_must_start_with_letter" for w in warnings
    )
