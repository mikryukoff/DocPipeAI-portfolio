import json
from pathlib import Path

from backend.app.domain.parsing.drawing_4_store import Drawing4Store
from backend.app.domain.parsing.row_parsers.instrument_embedment_parser import (
    InstrumentEmbedmentRowParser,
    normalize_instrument_number,
)


def _parsed_dir(tmp_path: Path, name: str, cfg: dict) -> Path:
    pt = tmp_path / "parsed_texts"
    pt.mkdir(parents=True, exist_ok=True)
    (pt / name).write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return pt


def test_drawing4_store_resolves_key_and_alias(tmp_path: Path):
    """Ключ JSON — канонический group_key; alias только у основного ключа."""
    cfg = {
        "K-MAIN": {"alias": ["K-ALIAS"], "path": "data/ocr/crop_page/x.png"},
    }
    pt = _parsed_dir(tmp_path, "map.json", cfg)
    store = Drawing4Store(parsed_texts_dir=pt)

    e1 = store.resolve("K-MAIN")
    assert e1 is not None
    assert e1.group_key == "K-MAIN"
    assert e1.path == "data/ocr/crop_page/x.png"
    assert e1.peer_tags == frozenset({"K-ALIAS", "K-MAIN"})

    e2 = store.resolve("K-ALIAS")
    assert e2 is not None
    assert e2.group_key == "K-MAIN"
    assert e2.path == "data/ocr/crop_page/x.png"
    assert e2.peer_tags == e1.peer_tags


def test_instrument_embedment_parser_uses_store(tmp_path: Path, monkeypatch):
    cfg = {
        "HP41-X": {"alias": [], "path": "data/ocr/crop_page/d.png"},
    }
    pt = _parsed_dir(tmp_path, "x.json", cfg)

    from backend.app.domain.parsing import drawing_4_store as d4

    monkeypatch.setattr(d4, "_store", None)
    store = Drawing4Store(parsed_texts_dir=pt)
    monkeypatch.setattr(d4, "_store", store)

    parser = InstrumentEmbedmentRowParser()
    line = ["1", "Закладная для прибора HP41-X", "шт", "2"]
    row = parser.parse(line, "P-100")
    assert row is not None
    assert row.instrument_tag == "HP41-X"
    assert row.name == "HP41-X"
    assert row.embedment_group_key == "HP41-X"
    assert row.drawing_image_path == "data/ocr/crop_page/d.png"
    assert row.location == "---"
    assert row.unit == "---"
    assert row.quantity == 0.0


def test_instrument_embedment_parser_unknown_tag(tmp_path: Path, monkeypatch):
    pt = _parsed_dir(tmp_path, "empty.json", {})
    from backend.app.domain.parsing import drawing_4_store as d4

    monkeypatch.setattr(d4, "_store", None)
    store = Drawing4Store(parsed_texts_dir=pt)
    monkeypatch.setattr(d4, "_store", store)

    parser = InstrumentEmbedmentRowParser()
    line = ["2", "Закладная для прибора UNKNOWN", "шт", "1"]
    row = parser.parse(line, "P-1")
    assert row is not None
    assert row.instrument_tag == "UNKNOWN"
    assert row.name == "UNKNOWN"
    assert row.unit == "---"
    assert row.quantity == 0.0
    assert row.embedment_group_key == ""
    assert row.drawing_image_path == ""


def test_instrument_embedment_parser_cyrillic_tag_resolves_latin_json_key(tmp_path: Path, monkeypatch):
    """Номер с кириллическими буквами (П, Т) приводится к латинице и находится в Drawing4Store."""
    cfg = {"PT-1": {"alias": [], "path": "data/ocr/crop_page/pt.png"}}
    pt = _parsed_dir(tmp_path, "m.json", cfg)
    from backend.app.domain.parsing import drawing_4_store as d4

    monkeypatch.setattr(d4, "_store", None)
    monkeypatch.setattr(d4, "_store", Drawing4Store(parsed_texts_dir=pt))

    parser = InstrumentEmbedmentRowParser()
    # П (U+041F) и Т (U+0422) — кириллица
    line = ["1", "Закладная для прибора \u041f\u0422-1", "шт", "1"]
    row = parser.parse(line, "P-1")
    assert row is not None
    assert row.instrument_tag == "PT-1"
    assert row.name == "PT-1"
    assert row.drawing_image_path == "data/ocr/crop_page/pt.png"
    assert row.embedment_group_key == "PT-1"


def test_normalize_instrument_number_strips_tail():
    assert (
        normalize_instrument_number(
            "XX01-PU002-PG-P01 (см. шт. ПСИ00000-2-ТК1.2.КИП)"
        )
        == "XX01-PU002-PG-P01"
    )


def test_instrument_embedment_parser_stores_tag_only_in_name(tmp_path: Path, monkeypatch):
    pt = _parsed_dir(tmp_path, "e.json", {})
    from backend.app.domain.parsing import drawing_4_store as d4

    monkeypatch.setattr(d4, "_store", None)
    monkeypatch.setattr(d4, "_store", Drawing4Store(parsed_texts_dir=pt))

    parser = InstrumentEmbedmentRowParser()
    line = [
        "3",
        "Закладная для прибора XX01-PU002-PG-P01 (см. шт. ПСИ00000-2-ТК1.2.КИП)",
        "шт",
        "1",
    ]
    row = parser.parse(line, "P-9")
    assert row is not None
    assert row.instrument_tag == "XX01-PU002-PG-P01"
    assert row.name == "XX01-PU002-PG-P01"
    assert row.unit == "---"
    assert row.quantity == 0.0
