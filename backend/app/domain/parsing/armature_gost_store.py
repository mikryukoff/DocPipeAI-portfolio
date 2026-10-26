from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

from backend.app.shared.user_data_paths import config_store_json_path


def _tokens(text: str) -> set[str]:
    """Слова (кириллица/латиница), длина ≥ 2 — для пересечения «не меньше 2 слов»."""
    return {
        m.group(0).lower()
        for m in re.finditer(
            r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё0-9-]*",
            text or "",
        )
        if len(m.group(0)) >= 2
    }


class ArmatureGostStore:
    """Соответствие наименования арматуры и ГОСТ/ТУ из data/config/armature_gost.json."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config_store_json_path("armature_gost.json")
        self._exact: dict[str, str] = {}
        self._mono: dict[str, str] = {}
        self._bi: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        self._exact = {}
        self._mono = {}
        self._bi = {}
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(data, dict):
            return
        for key, value in data.items():
            k = str(key).strip()
            v = str(value).strip()
            if not k or not v:
                continue
            self._exact[k] = v
            if "/" in k:
                self._bi[k] = v
            else:
                self._mono[k] = v

    @staticmethod
    def _best_word_match(
        query: str,
        keys_gost: dict[str, str],
        text_from_key: Callable[[str], str],
    ) -> tuple[str, str] | None:
        """Возвращает (gost, matched_key) при пересечении ≥ 2 слов; иначе None."""
        qt = _tokens(query)
        best_key: str | None = None
        best_score: tuple[int, int, int] = (-1, 0, 0)
        for key in sorted(keys_gost.keys()):
            kt = _tokens(text_from_key(key))
            inter = qt & kt
            n = len(inter)
            if n < 2:
                continue
            score = (n, -len(kt - qt), -len(key))
            if score > best_score:
                best_score = score
                best_key = key
        if best_key is None:
            return None
        return keys_gost[best_key], best_key

    def _display_ru(self, russian_base: str, bilingual_head: str) -> str:
        ru = (russian_base or "").strip()
        if ru:
            return ru
        bi = (bilingual_head or "").strip()
        return bi.split("/", 1)[0].strip() if bi else ""

    def resolve(self, *, russian_base: str, bilingual_head: str = "") -> tuple[str, str]:
        """
        Возвращает (gost, русское_наименование_для_хранения).
        Наименование для хранения — из входящего russian_base (как в документе), не короткий ключ из JSON.
        """
        ru = (russian_base or "").strip()
        bi = (bilingual_head or "").strip()
        display_ru = self._display_ru(ru, bi)

        if "/" in bi:
            return self._resolve_bilingual_incoming(ru, bi, display_ru)
        return self._resolve_russian_only(ru, bi, display_ru)

    def _resolve_russian_only(
        self,
        ru: str,
        bi: str,
        display_ru: str,
    ) -> tuple[str, str]:
        q = (ru or bi).strip()
        if not q:
            return "", display_ru

        if q in self._mono:
            return self._mono[q], display_ru

        hit = self._best_word_match(q, self._mono, lambda k: k)
        if hit:
            return hit[0], display_ru

        for key in sorted(self._bi.keys()):
            key_ru = key.split("/", 1)[0].strip()
            if key_ru == q:
                return self._bi[key], display_ru

        hit = self._best_word_match(q, self._bi, lambda k: k.split("/", 1)[0].strip())
        if hit:
            return hit[0], display_ru

        return "", display_ru

    def _resolve_bilingual_incoming(
        self,
        ru: str,
        bi: str,
        display_ru: str,
    ) -> tuple[str, str]:
        q = bi.strip()
        if not q:
            return "", display_ru

        if q in self._bi:
            return self._bi[q], display_ru

        hit = self._best_word_match(q, self._bi, lambda k: k)
        if hit:
            return hit[0], display_ru

        return "", display_ru


_default_store: ArmatureGostStore | None = None


def reset_armature_gost_store() -> None:
    """Сбросить кэш после изменения armature_gost.json на диске."""
    global _default_store
    _default_store = None


def get_armature_gost_store() -> ArmatureGostStore:
    global _default_store
    if _default_store is None:
        _default_store = ArmatureGostStore()
    return _default_store
