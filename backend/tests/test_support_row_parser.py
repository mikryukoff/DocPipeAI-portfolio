from backend.app.domain.parsing.row_parsers.support_parser import SupportRowParser


class _FakeGostSearch:
    def __init__(self, mapping: dict[str, str]):
        self.mapping = mapping

    def find_gost(self, support_name: str) -> str:
        return self.mapping.get(support_name, "")


def test_support_parser_sets_gost_for_single_support():
    parser = SupportRowParser(
        gost_search=_FakeGostSearch(
            {"Опора хомутовая ОПХ2-150-60,3-09Г2С": "ГОСТ 14911-82"}
        )
    )

    row = [
        "1",
        "Опора хомутовая ОПХ2-150-60,3-09Г2С, ПСИ00000-ТК.Н02",
        "шт",
        "2",
    ]
    result = parser.parse(row)

    assert result is not None
    assert result.name == "Опора хомутовая ОПХ2-150-60,3-09Г2С"
    assert result.gost == "ГОСТ 14911-82"


def test_support_parser_single_support_when_cell_has_parenthetical_note_with_dot_space():
    """Примечание в скобках с «. » внутри не должно давать вторую опору после split('. ')."""
    cell = (
        "Опора хомутовая ОПХ3-150-406,4-09Г2С, ПСИ00000-ТК.Н03 (упор поз. 6 изготавливается. "
        "На месте монтажа)."
    )
    parser = SupportRowParser(
        gost_search=_FakeGostSearch(
            {"Опора хомутовая ОПХ3-150-406,4-09Г2С": "ГОСТ 14911-82"},
        ),
    )
    result = parser.parse(["3", cell, "шт.", "1"])
    assert result is not None
    assert not isinstance(result, list)
    assert result.name == "Опора хомутовая ОПХ3-150-406,4-09Г2С"
    assert result.gost == "ГОСТ 14911-82"


def test_support_parser_preserves_name_when_comma_space_is_not_psi_tail():
    """Раньше brали split(', ')[0] — при «42, 4-120» терялась вторая часть марки."""
    parser = SupportRowParser(
        gost_search=_FakeGostSearch(
            {"Подвеска ПХУ-42, 4-120-09Г2С": "ГОСТ 14911-82"},
        ),
    )
    row = [
        "5",
        "Подвеска ПХУ-42, 4-120-09Г2С, ПСИ00000-ТК.Н07",
        "шт.",
        "2",
    ]
    result = parser.parse(row)
    assert result is not None
    assert result.name == "Подвеска ПХУ-42, 4-120-09Г2С"
    assert result.gost == "ГОСТ 14911-82"


def test_support_parser_sets_gost_for_multiple_supports():
    parser = SupportRowParser(
        gost_search=_FakeGostSearch(
            {
                "Опора подвижная ОПП1-100": "ГОСТ 14911-82",
                "Опора неподвижная ОПН2-100": "ГОСТ 30732-2020",
            }
        )
    )

    row = [
        "2",
        "Опора подвижная ОПП1-100. Опора неподвижная ОПН2-100",
        "шт",
        "4",
    ]
    result = parser.parse(row)

    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0].gost == "ГОСТ 14911-82"
    assert result[1].gost == "ГОСТ 30732-2020"
