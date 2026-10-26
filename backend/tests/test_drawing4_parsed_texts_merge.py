import json
from pathlib import Path

from backend.app.domain.parsing.drawing_4_store import Drawing4Store
from backend.scripts.merge_parsed_texts_dir import merge_parsed_texts_dir


def test_drawing4_store_loads_only_parsed_texts_merges_files(tmp_path: Path):
    """Несколько *.json без merged.json: более ранний по mtime файл задаёт значение ключа."""
    pt = tmp_path / "parsed_texts"
    pt.mkdir()
    (pt / "one.json").write_text(
        json.dumps(
            {
                "B": {"alias": [], "path": "b.png"},
                "A": {"alias": [], "path": "a.png"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (pt / "two.json").write_text(
        json.dumps(
            {
                "A": {"alias": ["X"], "path": "a2.png"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    store = Drawing4Store(parsed_texts_dir=pt)
    assert store.resolve("A") is not None
    assert store.resolve("A").path == "a.png"
    assert store.resolve("A").peer_tags == frozenset({"A"})
    assert store.resolve("B") is not None
    assert store.resolve("B").path == "b.png"


def test_drawing4_store_alias_only_on_primary_key(tmp_path: Path):
    pt = tmp_path / "parsed_texts"
    pt.mkdir()
    (pt / "m.json").write_text(
        json.dumps(
            {
                "TAG-A": {"alias": ["TAG-B", "TAG-C"], "path": "shared/crop.png"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store = Drawing4Store(parsed_texts_dir=pt)
    assert store.resolve("TAG-A").group_key == "TAG-A"
    assert store.resolve("TAG-A").peer_tags == frozenset({"TAG-A", "TAG-B", "TAG-C"})
    assert store.resolve("TAG-B").group_key == "TAG-A"
    assert store.resolve("TAG-B").peer_tags == frozenset({"TAG-A", "TAG-B", "TAG-C"})
    assert store.resolve("TAG-C") is not None
    assert store.resolve("TAG-C").peer_tags == frozenset({"TAG-A", "TAG-B", "TAG-C"})


def test_drawing4_resolve_matches_casefold_and_zero_width(tmp_path: Path):
    pt = tmp_path / "parsed_texts"
    pt.mkdir()
    (pt / "m.json").write_text(
        '{"TAG-A": {"alias": ["TAG-B"], "path": "x.png"}}',
        encoding="utf-8",
    )
    store = Drawing4Store(parsed_texts_dir=pt)
    assert store.resolve("tag-a") == store.resolve("TAG-A")
    assert store.resolve("TAG-B\u200b") is not None
    assert store.resolve("TAG-B\u200b").group_key == "TAG-A"


def test_drawing4_store_uses_only_merged_json_when_present(tmp_path: Path):
    """При наличии merged.json остальные *.json в каталоге не читаются."""
    pt = tmp_path / "parsed_texts"
    pt.mkdir()
    (pt / "merged.json").write_text(
        json.dumps({"ONLY": {"alias": [], "path": "m.png"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (pt / "other.json").write_text(
        json.dumps({"OTHER": {"alias": [], "path": "o.png"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    store = Drawing4Store(parsed_texts_dir=pt)
    assert store.resolve("ONLY") is not None
    assert store.resolve("ONLY").path == "m.png"
    assert store.resolve("OTHER") is None


def test_merge_parsed_texts_dir_script_prefers_older_file(tmp_path: Path):
    """Скрипт merge: при одинаковом ключе остаётся значение из файла с меньшим mtime."""
    pt = tmp_path / "parsed_texts"
    pt.mkdir()
    (pt / "a.json").write_text(
        json.dumps({"K": {"alias": [], "path": "old.png"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (pt / "b.json").write_text(
        json.dumps({"K": {"alias": ["X"], "path": "new.png"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    out = merge_parsed_texts_dir(pt)
    assert out.name == "merged.json"
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["K"]["path"] == "old.png"
