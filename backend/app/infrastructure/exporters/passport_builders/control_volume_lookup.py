from __future__ import annotations

import csv
import re
from functools import lru_cache
from pathlib import Path


class ControlVolumeLookup:
    """Достаёт проценты контроля из data/config/controle_volume.csv."""

    _DEFAULT_PATH = (
        Path(__file__).resolve().parents[5] / "data" / "config" / "controle_volume.csv"
    )

    _KIND_TO_COLUMN_KEY = {
        "УЗК": "uzk",
        "ПВК": "pvk",
        "СТИЛОСКОПИРОВАНИЕ": "styloscopy",
    }

    def __init__(self, csv_path: Path | None = None) -> None:
        self.csv_path = csv_path or self._DEFAULT_PATH

    def get_percent(self, gost_category: str, control_kind: str) -> str:
        rows = self._read_rows(str(self.csv_path))
        if not rows:
            return "---"

        kind_key = self._KIND_TO_COLUMN_KEY.get((control_kind or "").strip().upper())
        if not kind_key:
            return "---"

        group_candidates, category = self._parse_gost_category(gost_category)
        if not category:
            return "---"

        matched_row = self._find_row(rows, group_candidates=group_candidates, category=category)
        if not matched_row:
            return "---"

        value = (matched_row.get(kind_key) or "").strip()
        return value or "---"

    @classmethod
    @lru_cache(maxsize=2)
    def _read_rows(cls, csv_path: str) -> tuple[dict[str, str], ...]:
        path = Path(csv_path)
        if not path.exists():
            return tuple()

        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f, delimiter=";")
            if not reader.fieldnames:
                return tuple()

            field_map = cls._map_columns(reader.fieldnames)
            rows: list[dict[str, str]] = []
            for raw in reader:
                row = {key: (raw.get(col_name) or "").strip() for key, col_name in field_map.items()}
                if row["category"]:
                    rows.append(row)
            return tuple(rows)

    @staticmethod
    def _map_columns(fieldnames: list[str]) -> dict[str, str]:
        mapping: dict[str, str] = {
            "group": "",
            "category": "",
            "uzk": "",
            "pvk": "",
            "styloscopy": "",
        }
        for name in fieldnames:
            low = (name or "").strip().lower()
            if "группа среды" in low:
                mapping["group"] = name
            elif "group" in low:
                mapping["group"] = name
            elif low.startswith("кат"):
                mapping["category"] = name
            elif low.startswith("cat"):
                mapping["category"] = name
            elif "узк" in low:
                mapping["uzk"] = name
            elif "пвк" in low:
                mapping["pvk"] = name
            elif "стилоскоп" in low:
                mapping["styloscopy"] = name
        return mapping

    @classmethod
    def _parse_gost_category(cls, gost_category: str) -> tuple[set[str], str]:
        text = (gost_category or "").strip().upper()
        if not text:
            return set(), ""

        category = ""
        digit_match = re.search(r"\b([1-5])\b", text)
        if digit_match:
            category = cls._digit_to_roman(digit_match.group(1))
        if not category:
            # Без word-boundary: нужны кейсы вроде "ВV".
            category_match = re.search(r"(?:III|IV|II|V|I)", text)
            category = category_match.group(0) if category_match else ""

        group_candidates: set[str] = set()
        group_match = re.search(r"[АБВABV]", text)
        if group_match:
            group_candidates = cls._group_variants(group_match.group(0))

        return group_candidates, category

    @staticmethod
    def _digit_to_roman(digit: str) -> str:
        return {
            "1": "I",
            "2": "II",
            "3": "III",
            "4": "IV",
            "5": "V",
        }.get(digit, "")

    @classmethod
    def _find_row(
        cls,
        rows: tuple[dict[str, str], ...],
        *,
        group_candidates: set[str],
        category: str,
    ) -> dict[str, str] | None:
        by_category = [row for row in rows if cls._normalize_category(row.get("category", "")) == category]
        if not by_category:
            return None

        if not group_candidates:
            return by_category[0]

        for row in by_category:
            raw_group = row.get("group", "")
            if "любая" in raw_group.lower():
                return row
            row_groups = cls._extract_groups(raw_group)
            if group_candidates.intersection(row_groups):
                return row

        return by_category[0]

    @classmethod
    def _extract_groups(cls, group_cell: str) -> set[str]:
        groups: set[str] = set()
        for letter in re.findall(r"[A-ZА-Я]", (group_cell or "").upper()):
            groups.update(cls._group_variants(letter))
        return groups

    @staticmethod
    def _normalize_category(raw: str) -> str:
        text = (raw or "").strip().upper()
        match = re.search(r"(III|IV|II|V|I)", text)
        return match.group(1) if match else text

    @staticmethod
    def _normalize_group(raw: str) -> str:
        text = (raw or "").strip().upper()
        if text == "A":
            return "А"
        if text == "B":
            return "Б"
        if text == "V":
            return "В"
        return text

    @classmethod
    def _group_variants(cls, raw: str) -> set[str]:
        raw_text = (raw or "").strip().upper()
        normalized = cls._normalize_group(raw_text)
        if raw_text == "B":
            # Латинская B может встретиться вместо русской В.
            return {"Б", "В"}
        return {normalized}
