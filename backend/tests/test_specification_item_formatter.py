from types import SimpleNamespace

from backend.app.domain.parsing.specification.specification_item_formatter import (
    SpecificationPartsFormatter,
)


def test_format_extracts_en_steel_grade_and_en_gost_by_pattern():
    item = SimpleNamespace(material="", steel_grade="", gost="", dimensions="")
    name = (
        "Колено 90 по EN 10253-4, материал: EN 1.4404 = X2CrNiMo 17-12-2 "
        "по EN 10217-7, 60,3х3,2"
    )

    SpecificationPartsFormatter.format(name, item)

    assert item.steel_grade == "EN 1.4404"
    assert item.gost == "EN 10217-7"


def test_format_extracts_en_codes_even_without_equal_separator():
    item = SimpleNamespace(material="", steel_grade="", gost="", dimensions="")
    name = "Переход материал: сталь EN 1.4541 по EN 1092-1, DN50"

    SpecificationPartsFormatter.format(name, item)

    assert item.steel_grade == "EN 1.4541"
    assert item.gost == "EN 1092-1"


def test_format_extracts_gost_when_po_en_has_no_space():
    item = SimpleNamespace(material="", steel_grade="", gost="", dimensions="")
    name = "Труба по EN ISO 1127, материал: EN 1.4404 = X2CrNiMo 17-12-2 поEN 10217-7, DN219,1x3,6"

    SpecificationPartsFormatter.format(name, item)

    assert item.steel_grade == "EN 1.4404"
    assert item.gost == "EN 10217-7"


def test_format_extracts_dimensions_from_dn_with_space_and_decimal():
    item = SimpleNamespace(material="", steel_grade="", gost="", dimensions="")
    name = "Труба по EN ISO 1127, материал: EN 1.4404 = X2CrNiMo 17-12-2 по EN DN 114,3"

    SpecificationPartsFormatter.format(name, item)

    assert item.steel_grade == "EN 1.4404"
    assert item.gost == ""
    assert item.dimensions == "Ø114,3"
