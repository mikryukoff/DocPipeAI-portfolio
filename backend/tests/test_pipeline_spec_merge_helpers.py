"""Поведение merge spec_items при повторном PDF после Excel (ключ без name, extra)."""

from backend.app.infrastructure.repositories.pipeline_repository import _merge_spec_item_extra


def test_merge_extra_keeps_gost_when_incoming_is_placeholder():
    existing = {"gost": "ТУ 3741-001", "dn": "50"}
    incoming = {"gost": "---", "dn": "50", "location": "т-д №X"}
    merged = _merge_spec_item_extra(existing, incoming)
    assert merged["gost"] == "ТУ 3741-001"
    assert merged["location"] == "т-д №X"


def test_merge_extra_incoming_overwrites_meaningful_values():
    existing = {"gost": "---"}
    incoming = {"gost": "ГОСТ 1"}
    merged = _merge_spec_item_extra(existing, incoming)
    assert merged["gost"] == "ГОСТ 1"
