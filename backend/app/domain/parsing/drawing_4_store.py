from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from backend.app.domain.parsing.drawing_tag_normalize import instrument_tag_dedup_key

MERGED_PARSED_TEXTS_FILENAME = "merged.json"


@dataclass(frozen=True)
class Drawing4Entry:
    """Соответствие номера прибора и скриншота по JSON из data/ocr/parsed_texts (ключ = канонический номер группы)."""

    group_key: str
    path: str
    peer_tags: frozenset[str]


def _normalize_rel_path(raw: str) -> str:
    return (raw or "").strip().replace("\\", "/")


class Drawing4Store:
    """Карта номер→crop: *.json в parsed_texts_dir; group_key = ключ объекта в JSON.

    Если в каталоге есть merged.json — загружается только он (результат скрипта слияния).
    Иначе читаются все *.json кроме merged.json, по возрастанию mtime; при конфликте ключа
    сохраняется значение из более старого файла (как при merge_parsed_texts_dir.py).
    """

    def __init__(self, *, parsed_texts_dir: Path | None = None) -> None:
        self.parsed_texts_dir = parsed_texts_dir
        self._by_key: dict[str, Drawing4Entry] = {}
        self._load()

    def _ingest_dict(self, data: dict, *, skip_existing_keys: bool = False) -> None:
        if not isinstance(data, dict):
            return
        for key, raw in data.items():
            if not isinstance(key, str) or not key.strip():
                continue
            if not isinstance(raw, dict):
                continue
            k = key.strip()
            if skip_existing_keys and k in self._by_key:
                continue
            rel_path = _normalize_rel_path(raw.get("path") or "")
            aliases = raw.get("alias") or []
            peer_list: list[str] = [k]
            if isinstance(aliases, list):
                for a in aliases:
                    if isinstance(a, str) and a.strip():
                        peer_list.append(a.strip())
            peers = frozenset(peer_list)
            entry = Drawing4Entry(group_key=k, path=rel_path, peer_tags=peers)
            self._by_key[k] = entry

    def _load(self) -> None:
        self._by_key = {}
        pdir = self.parsed_texts_dir
        if pdir is not None and pdir.is_dir():
            merged = pdir / MERGED_PARSED_TEXTS_FILENAME
            if merged.is_file():
                json_files = [merged]
                skip_existing = False
            else:
                json_files = sorted(
                    (p for p in pdir.glob("*.json") if p.name != MERGED_PARSED_TEXTS_FILENAME),
                    key=lambda p: (p.stat().st_mtime_ns, p.name),
                )
                skip_existing = True
            for jpath in json_files:
                try:
                    data = json.loads(jpath.read_text(encoding="utf-8"))
                    self._ingest_dict(
                        data if isinstance(data, dict) else {},
                        skip_existing_keys=skip_existing,
                    )
                except Exception:
                    continue

    def resolve(self, instrument_tag: str) -> Drawing4Entry | None:
        raw = (instrument_tag or "").strip()
        if not raw:
            return None
        if raw in self._by_key:
            return self._by_key[raw]
        cf = instrument_tag_dedup_key(raw)
        if not cf:
            return None
        for key, entry in self._by_key.items():
            if instrument_tag_dedup_key(key) == cf:
                return entry
        for entry in self._by_key.values():
            if any(instrument_tag_dedup_key(p) == cf for p in entry.peer_tags):
                return entry
        return None


_store: Drawing4Store | None = None


def reset_drawing_4_store() -> None:
    """Сбросить кэш после изменения JSON в каталоге распознанных текстов (drawing_4)."""
    global _store
    _store = None


def get_drawing_4_store() -> Drawing4Store:
    global _store
    if _store is None:
        parsed_dir: Path | None = None
        try:
            from backend.app.config import load_config

            parsed_dir = Path(load_config().ocr.parsed_output_dir)
        except Exception:
            parsed_dir = Path("data/ocr/parsed_texts")
        _store = Drawing4Store(parsed_texts_dir=parsed_dir)
    return _store
