"""Кириллица → латиница в normalize_instrument_tag_label / normalize_instrument_number."""

from backend.app.domain.parsing.drawing_tag_normalize import (
    cyrillic_to_latin_for_instrument_tag,
    instrument_tag_dedup_key,
    normalize_embedment_auxiliary_text,
    normalize_instrument_tag_label,
)
from backend.app.domain.parsing.row_parsers.instrument_embedment_parser import normalize_instrument_number


def test_cyrillic_homoglyphs_to_latin():
    # Н (кирил.) + Р (кирил.) как на чертежах вместо латиницы
    assert cyrillic_to_latin_for_instrument_tag("НР-100") == "HP-100"
    assert cyrillic_to_latin_for_instrument_tag("ПТ-01") == "PT-01"


def test_normalize_instrument_tag_label_chain():
    assert normalize_instrument_tag_label("  НР\u2011100  ") == "HP-100"


def test_instrument_tag_dedup_key_unifies_cyrillic_latin():
    assert instrument_tag_dedup_key("НР-100") == instrument_tag_dedup_key("HP-100")


def test_normalize_instrument_number_strips_then_homoglyphs():
    assert (
        normalize_instrument_number(
            "НР-100 (см. шт. ПСИ00000-2-ТК1.2.КИП)"
        )
        == "HP-100"
    )


def test_normalize_embedment_auxiliary_text_no_homoglyphs():
    s = normalize_embedment_auxiliary_text("  НР\u2011100  ")
    assert s == "\u041d\u0420-100"  # кирил. НР, дефис ASCII


def test_non_homoglyph_cyrillic_unchanged():
    assert cyrillic_to_latin_for_instrument_tag("ЖЩ-1") == "ЖЩ-1"
    assert cyrillic_to_latin_for_instrument_tag("бгд-2") == "бгд-2"
