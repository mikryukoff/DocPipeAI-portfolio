"""План удаления / слияния закладных после нормализации омоглифов (скрипт БД)."""

from backend.scripts.normalize_embedment_cyrillic_tags import (
    _merge_clean_template_into_dirty_plans,
    _norm_dedup_key,
    _plan_spec_embedment_deletions,
)


class _FakeRow:
    def __init__(self, row_id: int, pipeline_id: int, extra: dict, *, name="n", unit="---", quantity=0.0) -> None:
        self.id = row_id
        self.pipeline_id = pipeline_id
        self.extra = extra
        self.name = name
        self.unit = unit
        self.quantity = quantity


def _e(row: _FakeRow, new_ex: dict, ch: bool, new_it: str) -> dict:
    return {
        "row": row,
        "new_ex": new_ex,
        "ch": ch,
        "new_it": new_it,
        "merged_from_clean": False,
    }


def test_norm_dedup_key_path_vs_gk():
    assert _norm_dedup_key("path:data/ocr/\u041d.png") == "path:data/ocr/\u041d.png"
    assert _norm_dedup_key("gk:\u041d\u0420-1") == "gk:HP-1"


def test_plan_does_not_delete_when_clean_present():
    clean = _FakeRow(2, 10, {"instrument_tag": "HP-1"})
    dirty = _FakeRow(1, 10, {"instrument_tag": "\u041d\u0420-1"})  # НР-1
    plans = [
        _e(dirty, {"instrument_tag": "HP-1"}, True, "HP-1"),
        _e(clean, {"instrument_tag": "HP-1"}, False, "HP-1"),
    ]
    assert _plan_spec_embedment_deletions(plans) == set()


def test_plan_does_not_delete_clean_on_other_pipeline():
    clean = _FakeRow(100, 99, {"instrument_tag": "HP-1"})
    dirty = _FakeRow(1, 5, {"instrument_tag": "\u041d\u0420-1"})
    plans = [
        _e(dirty, {"instrument_tag": "HP-1"}, True, "HP-1"),
        _e(clean, {"instrument_tag": "HP-1"}, False, "HP-1"),
    ]
    assert _plan_spec_embedment_deletions(plans) == set()


def test_merge_copies_extra_and_display_from_best_clean():
    clean_sparse = _FakeRow(
        10,
        1,
        {"instrument_tag": "HP-1"},
        name="HP-1",
        unit="шт",
        quantity=2.0,
    )
    clean_rich = _FakeRow(
        11,
        2,
        {
            "instrument_tag": "HP-1",
            "drawing_image_path": "data/crop/a.png",
            "dn": "50",
        },
        name="HP-1",
        unit="шт",
        quantity=1.0,
    )
    dirty = _FakeRow(1, 3, {"instrument_tag": "\u041d\u0420-1"}, name="bad", unit="---", quantity=0.0)
    plans = [
        _e(dirty, {"instrument_tag": "HP-1"}, True, "HP-1"),
        _e(clean_sparse, {"instrument_tag": "HP-1"}, False, "HP-1"),
        _e(clean_rich, {"instrument_tag": "HP-1", "drawing_image_path": "data/crop/a.png", "dn": "50"}, False, "HP-1"),
    ]
    n = _merge_clean_template_into_dirty_plans(plans)
    assert n == 1
    d0 = next(p for p in plans if p["row"] is dirty)
    assert d0["new_ex"]["drawing_image_path"] == "data/crop/a.png"
    assert d0["new_ex"]["dn"] == "50"
    assert d0["merged_from_clean"] is True
    assert d0["tpl_name"] == "HP-1"
    assert d0["tpl_unit"] == "шт"
    assert d0["tpl_qty"] == 1.0


def test_plan_keeps_two_clean_same_dedup():
    a = _FakeRow(1, 10, {"instrument_tag": "HP-1"})
    b = _FakeRow(2, 20, {"instrument_tag": "hp-1"})
    plans = [
        _e(a, {"instrument_tag": "HP-1"}, False, "HP-1"),
        _e(b, {"instrument_tag": "hp-1"}, False, "hp-1"),
    ]
    assert _plan_spec_embedment_deletions(plans) == set()


def test_plan_all_dirty_deletes_every_row_across_pipelines():
    a = _FakeRow(5, 7, {"instrument_tag": "\u041d\u0420-1"})
    b = _FakeRow(9, 8, {"instrument_tag": "\u041d\u0420-1"})
    plans = [
        _e(a, {"instrument_tag": "HP-1"}, True, "HP-1"),
        _e(b, {"instrument_tag": "HP-1"}, True, "HP-1"),
    ]
    assert _plan_spec_embedment_deletions(plans) == {5, 9}


def test_plan_single_row_no_delete():
    r = _FakeRow(1, 1, {"instrument_tag": "\u041d\u0420-1"})
    plans = [_e(r, {"instrument_tag": "HP-1"}, True, "HP-1")]
    assert _plan_spec_embedment_deletions(plans) == set()
