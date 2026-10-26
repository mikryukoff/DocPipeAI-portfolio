"""Проверка правил «закладная уже обогащена» (не просить дозаполнение)."""

from backend.app.infrastructure.embedment_extra import instrument_embedment_extra_enriched


def test_enriched_single_element_name_equals_instrument_tag():
    ex = {
        "instrument_tag": "TT-01",
        "embedment_elements": [
            {
                "name": "TT-01",
                "location": "---",
                "dn": "---",
                "pn": "---",
                "material_grade": "---",
                "gost": "---",
            }
        ],
    }
    assert instrument_embedment_extra_enriched(ex) is True


def test_enriched_single_element_numeric_tag_coercion():
    ex = {"instrument_tag": 12, "embedment_elements": [{"name": "12"}]}
    assert instrument_embedment_extra_enriched(ex) is True


def test_not_enriched_single_element_placeholder_name_not_tag():
    ex = {
        "instrument_tag": "TT-01",
        "embedment_elements": [
            {
                "name": "---",
                "location": "---",
            }
        ],
    }
    assert instrument_embedment_extra_enriched(ex) is False


def test_not_enriched_two_elements_even_if_first_matches_tag():
    ex = {
        "instrument_tag": "TT-01",
        "embedment_elements": [
            {"name": "TT-01"},
            {"name": "---"},
        ],
    }
    assert instrument_embedment_extra_enriched(ex) is False
