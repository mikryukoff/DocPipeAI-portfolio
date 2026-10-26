from backend.app.domain.parsing.row_parsers.flange_parser import FlangeRowParser


def test_flange_parser_extracts_bolt_fields_from_kit_section():
    parser = FlangeRowParser()
    row = [
        "1",
        (
            "Фланец тип 02/35 по EN 1092-1, материал: EN 1.4462 = X2CrNiMoN 22-5-3 по EN 10217-7, "
            "DN150 PN16. В комплекте: Шпилька DIN 976-1 – M20×140 – B, материал 1.4462 по EN 10217-7 - 8 шт.; "
            "Гайка DIN 934 – М20, материал 1.4462 по EN 10217-7 - 16 шт.;"
        ),
        "шт",
        "1",
    ]

    result = parser.parse(row)

    assert result is not None
    assert result.bolt_grade == "EN 1.4462"
    assert result.bolt_gost == "EN 10217-7"


def test_flange_parser_does_not_fill_bolt_fields_without_kit_marker():
    parser = FlangeRowParser()
    row = [
        "1",
        "Фланец тип 02/35 по EN 1092-1, материал: EN 1.4462 = X2CrNiMoN 22-5-3 по EN 10217-7, DN150 PN16",
        "шт",
        "1",
    ]

    result = parser.parse(row)

    assert result is not None
    assert result.bolt_grade == ""
    assert result.bolt_gost == ""
