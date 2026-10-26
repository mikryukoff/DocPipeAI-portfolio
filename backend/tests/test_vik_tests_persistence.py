from backend.app.application.imports.vik_tests_persistence import (
    normalize_vik_type,
    vik_pipeline_name_lookup_variants,
)
from backend.app.shared.strength_test_duration import format_strength_test_duration


def test_normalize_vik_type_supports_styloscopy():
    assert normalize_vik_type("стилоскопирование") == "СТИЛОСКОПИРОВАНИЕ"


def test_vik_pipeline_name_lookup_variants_replaces_underscore_for_db_lookup():
    raw = "ZZ04-25003-PSU-65_E010H4C03-IP"
    assert vik_pipeline_name_lookup_variants(raw) == [
        raw,
        "ZZ04-25003-PSU-65-E010H4C03-IP",
    ]


def test_vik_pipeline_name_lookup_variants_no_extra_when_only_hyphens():
    s = "ZZ04-25003-PSU-65-E010H4C03-IP"
    assert vik_pipeline_name_lookup_variants(s) == [s]


def test_format_strength_test_duration_from_minutes():
    assert format_strength_test_duration("30") == "0 ч. (30 мин.)"


def test_format_strength_test_duration_from_hours_and_minutes():
    assert format_strength_test_duration("1 ч 30 мин") == "1 ч. (90 мин.)"
