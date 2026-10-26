from __future__ import annotations

import json
import re
from pathlib import Path

from backend.app.shared.user_data_paths import config_store_json_path


class SupportGostMappingStore:
    """
    Persistent-словарь ГОСТов опор.

    Формат файла:
    {
      "exact": {"Опора ...": "ГОСТ ..."},
      "family": {"ОПОРА СТОЙКА ОПС О": "ГОСТ ..."}
    }
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config_store_json_path("support_gost_mapping.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._exact: dict[str, str] = {}
        self._family: dict[str, str] = {}
        self._exact_normalized: dict[str, str] = {}
        self._family_normalized: dict[str, str] = {}
        self._load()

    def get_exact(self, support_name: str) -> str:
        return self._exact.get((support_name or "").strip(), "")

    def get_exact_relaxed(self, support_name: str) -> str:
        key = self._normalize_key(support_name)
        if not key:
            return ""
        return self._exact_normalized.get(key, "")

    def get_family(self, family_key: str) -> str:
        return self._family.get((family_key or "").strip(), "")

    def get_family_relaxed(self, family_key: str) -> str:
        key = self._normalize_key(family_key)
        if not key:
            return ""
        return self._family_normalized.get(key, "")

    def set_exact(self, support_name: str, gost: str) -> None:
        key = (support_name or "").strip()
        value = (gost or "").strip()
        if not key or not value:
            return
        self._exact[key] = value
        self._exact_normalized[self._normalize_key(key)] = value
        self._save()

    def set_family(self, family_key: str, gost: str) -> None:
        key = (family_key or "").strip()
        value = (gost or "").strip()
        if not key or not value:
            return
        self._family[key] = value
        self._family_normalized[self._normalize_key(key)] = value
        self._save()

    def _load(self) -> None:
        if not self.path.exists():
            self._save()
            return

        try:
            payload = json.loads(self.path.read_text(encoding="utf-8")) or {}
            if isinstance(payload, dict):
                exact = payload.get("exact", {})
                family = payload.get("family", {})
                self._exact = exact if isinstance(exact, dict) else {}
                self._family = family if isinstance(family, dict) else {}
                self._rebuild_indexes()
            else:
                self._exact = {}
                self._family = {}
                self._exact_normalized = {}
                self._family_normalized = {}
        except Exception:
            self._exact = {}
            self._family = {}
            self._exact_normalized = {}
            self._family_normalized = {}

    def _save(self) -> None:
        payload = {
            "exact": self._exact,
            "family": self._family,
        }
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def _rebuild_indexes(self) -> None:
        self._exact_normalized = {}
        self._family_normalized = {}
        for key, value in self._exact.items():
            norm = self._normalize_key(key)
            if norm and value:
                self._exact_normalized[norm] = value
        for key, value in self._family.items():
            norm = self._normalize_key(key)
            if norm and value:
                self._family_normalized[norm] = value

    @staticmethod
    def _normalize_key(value: str) -> str:
        text = (value or "").strip().upper().replace("Ё", "Е")
        text = re.sub(r"[^A-ZА-Я0-9]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text.replace(" ", "")
