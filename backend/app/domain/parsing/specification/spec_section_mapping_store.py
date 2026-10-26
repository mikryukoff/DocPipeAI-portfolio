from __future__ import annotations

import json
import re
from pathlib import Path

from backend.app.domain.models.spec_section import SpecSection
from backend.app.shared.user_data_paths import config_store_json_path

UNDEFINED_SECTION_LABEL = "Не определен"
USER_UNDEFINED_SECTION_LABEL = "Не определен пользователем"

# Паспорт: таблицы 4.x (UI) ↔ внутренние разделы спецификации (хранение в JSON).
TABLE_SPEC_4_1 = "Таблица 4.1"
TABLE_SPEC_4_2 = "Таблица 4.2"
TABLE_SPEC_4_3 = "Таблица 4.3"
TABLE_SPEC_4_4 = "Таблица 4.4"

SPEC_TABLE_UI_ORDER: tuple[str, ...] = (
    TABLE_SPEC_4_1,
    TABLE_SPEC_4_2,
    TABLE_SPEC_4_3,
    TABLE_SPEC_4_4,
)

SECTION_LABEL_RU_BY_ENUM: dict[SpecSection, str] = {
    SpecSection.PIPELINE_ARMATURE: "Арматура",
    SpecSection.INSTRUMENT_EMBEDMENT: "Закладная",
    SpecSection.PIPES: "Трубы",
    SpecSection.CONNECTION_PARTS: "Соединительные детали",
    SpecSection.FLANGES: "Фланцы",
    SpecSection.SUPPORTS: "Опоры",
}
SECTION_ENUM_BY_RU_LABEL: dict[str, SpecSection] = {
    label: section for section, label in SECTION_LABEL_RU_BY_ENUM.items()
}

TABLE_TO_SECTION_LABELS_RU = {
    TABLE_SPEC_4_1: (
        SECTION_LABEL_RU_BY_ENUM[SpecSection.PIPES],
        SECTION_LABEL_RU_BY_ENUM[SpecSection.CONNECTION_PARTS],
    ),
    TABLE_SPEC_4_2: (SECTION_LABEL_RU_BY_ENUM[SpecSection.PIPELINE_ARMATURE],),
    TABLE_SPEC_4_3: (
        SECTION_LABEL_RU_BY_ENUM[SpecSection.FLANGES],
        SECTION_LABEL_RU_BY_ENUM[SpecSection.SUPPORTS],
    ),
    TABLE_SPEC_4_4: (SECTION_LABEL_RU_BY_ENUM[SpecSection.INSTRUMENT_EMBEDMENT],),
}

SECTION_RU_LABEL_TO_TABLE: dict[str, str] = {}
for _tbl, _labels in TABLE_TO_SECTION_LABELS_RU.items():
    for _lab in _labels:
        SECTION_RU_LABEL_TO_TABLE[_lab] = _tbl

# Таблица 4.1: наименование начинается с «Труба» / «Трубы» → трубы, иначе соединительные детали.
_FIRST_WORD_TRUBA = re.compile(r"^(труба|трубы)\b", re.IGNORECASE)
# Таблица 4.3: начинается с «Опора» / «Опоры» → опоры, иначе фланцы.
_FIRST_WORD_OPRA = re.compile(r"^(опора|опоры)\b", re.IGNORECASE)


class UndefinedSpecSectionError(Exception):
    def __init__(self, item_name: str, full_name: str, row: list[str], page: str | None = None):
        self.item_name = item_name
        self.full_name = full_name
        self.row = row
        self.page = page
        super().__init__(f"spec_section_not_defined: {item_name}")


def normalize_item_name(name: str) -> str:
    return " ".join((name or "").strip().split())


def extract_base_item_name(name: str) -> str:
    normalized = normalize_item_name(name)
    if not normalized:
        return ""
    return normalized.split()[0]


def enum_to_ru_label(section: SpecSection) -> str:
    return SECTION_LABEL_RU_BY_ENUM[section]


def parse_section_label(section_value: str | None) -> SpecSection | None:
    value = (section_value or "").strip()
    if not value:
        return None
    if value in SECTION_ENUM_BY_RU_LABEL:
        return SECTION_ENUM_BY_RU_LABEL[value]
    if value == "instrument_embedment":
        return SpecSection.INSTRUMENT_EMBEDMENT
    try:
        # Backward compatibility for old stored values (pipeline_armature, pipes, ...)
        return SpecSection(value)
    except Exception:
        return None


def normalize_section_for_storage(section_value: str | None) -> str | None:
    value = (section_value or "").strip()
    if value in {UNDEFINED_SECTION_LABEL, USER_UNDEFINED_SECTION_LABEL}:
        return value
    parsed = parse_section_label(value)
    if parsed is None:
        return None
    return enum_to_ru_label(parsed)


def table_to_sections_map_for_ui() -> dict[str, list[str]]:
    """Для UI: 4.1 и 4.3 — без выбора раздела (раздел выводится из наименования позиции)."""
    out: dict[str, list[str]] = {}
    for k, v in TABLE_TO_SECTION_LABELS_RU.items():
        if k in (TABLE_SPEC_4_1, TABLE_SPEC_4_3):
            out[k] = []
        else:
            out[k] = list(v)
    return out


def allowed_tables_for_ui() -> list[str]:
    return list(SPEC_TABLE_UI_ORDER)


def section_ru_label_to_spec_table(section_ru: str | None) -> str | None:
    """Русская подпись раздела (как в JSON) → подпись таблицы для UI."""
    v = (section_ru or "").strip()
    if not v:
        return None
    return SECTION_RU_LABEL_TO_TABLE.get(v)


def resolve_table_choice_to_section_ru(
    table_label: str,
    section_ru_override: str | None,
    *,
    item_name: str | None = None,
) -> str:
    """
    Таблица паспорта (и опционально явный раздел) → русская подпись раздела для spec_item_sections.json.

    Для 4.1 и 4.3 раздел определяется по наименованию позиции (item_name), если оно непустое:
    4.1 — первое слово «Труба» или «Трубы» → Трубы, иначе Соединительные детали;
    4.3 — первое слово «Опора» или «Опоры» → Опоры, иначе Фланцы.
    Если item_name пуст, для 4.1/4.3 сохраняется прежняя схема: нужен явный section_ru_override.

    Raises:
        ValueError: invalid_table | section_required | invalid_section_for_table
    """
    table = (table_label or "").strip()
    if table not in TABLE_TO_SECTION_LABELS_RU:
        raise ValueError("invalid_table")
    allowed = TABLE_TO_SECTION_LABELS_RU[table]
    section_ov = (section_ru_override or "").strip() or None
    nk = normalize_item_name(item_name or "")

    if table == TABLE_SPEC_4_1:
        if nk:
            if _FIRST_WORD_TRUBA.match(nk):
                return SECTION_LABEL_RU_BY_ENUM[SpecSection.PIPES]
            return SECTION_LABEL_RU_BY_ENUM[SpecSection.CONNECTION_PARTS]
        if not section_ov:
            raise ValueError("section_required")
        if section_ov not in allowed:
            raise ValueError("invalid_section_for_table")
        return section_ov

    if table == TABLE_SPEC_4_3:
        if nk:
            if _FIRST_WORD_OPRA.match(nk):
                return SECTION_LABEL_RU_BY_ENUM[SpecSection.SUPPORTS]
            return SECTION_LABEL_RU_BY_ENUM[SpecSection.FLANGES]
        if not section_ov:
            raise ValueError("section_required")
        if section_ov not in allowed:
            raise ValueError("invalid_section_for_table")
        return section_ov

    if len(allowed) == 1:
        only = allowed[0]
        if section_ov and section_ov != only:
            raise ValueError("invalid_section_for_table")
        return only
    if not section_ov:
        raise ValueError("section_required")
    if section_ov not in allowed:
        raise ValueError("invalid_section_for_table")
    return section_ov


class SpecSectionMappingStore:
    def __init__(self, path: Path | None = None):
        self.path = path or config_store_json_path("spec_item_sections.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._mapping: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._mapping = {}
            self._save()
            return
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8")) or {}
            self._mapping = loaded if isinstance(loaded, dict) else {}
            changed = False
            for key, value in list(self._mapping.items()):
                normalized_value = normalize_section_for_storage(value)
                if normalized_value is None:
                    continue
                if normalized_value != value:
                    self._mapping[key] = normalized_value
                    changed = True
            if changed:
                self._save()
        except Exception:
            self._mapping = {}

    def _save(self) -> None:
        self.path.write_text(
            json.dumps(self._mapping, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def resolve_section(self, item_name: str) -> SpecSection | None:
        key = normalize_item_name(item_name)
        if not key:
            return None
        value = self._mapping.get(key)
        if value == USER_UNDEFINED_SECTION_LABEL:
            return None
        parsed = parse_section_label(value)
        if parsed is not None:
            return parsed
        return self._resolve_by_prefix(key)

    def get_raw_value(self, item_name: str) -> str | None:
        key = normalize_item_name(item_name)
        if not key:
            return None
        return self._mapping.get(key)

    def ensure_item(self, item_name: str) -> bool:
        key = normalize_item_name(item_name)
        if not key:
            return False
        if key in self._mapping:
            return False
        self._mapping[key] = UNDEFINED_SECTION_LABEL
        self._save()
        return True

    def list_undefined(self) -> list[str]:
        return sorted(
            name for name, section in self._mapping.items()
            if section == UNDEFINED_SECTION_LABEL and self.is_pending(name)
        )

    def is_pending(self, item_name: str) -> bool:
        raw = self.get_raw_value(item_name)
        if raw == USER_UNDEFINED_SECTION_LABEL:
            return False
        if self.resolve_section(item_name) is not None:
            return False
        return raw == UNDEFINED_SECTION_LABEL

    def update_many(self, mapping: dict[str, str]) -> int:
        updated = 0
        for raw_name, raw_section in (mapping or {}).items():
            name = normalize_item_name(raw_name)
            section = normalize_section_for_storage(raw_section)
            if not name or section is None:
                continue
            self._mapping[name] = section
            self._drop_redundant_undefined_children(name)
            updated += 1
        if updated:
            self._save()
        return updated

    @staticmethod
    def allowed_sections_for_ui() -> list[str]:
        return [SECTION_LABEL_RU_BY_ENUM[s] for s in SpecSection]

    @staticmethod
    def allowed_tables_for_ui() -> list[str]:
        return allowed_tables_for_ui()

    @staticmethod
    def table_to_sections_map_for_ui() -> dict[str, list[str]]:
        return table_to_sections_map_for_ui()

    def _resolve_by_prefix(self, item_name: str) -> SpecSection | None:
        target = normalize_item_name(item_name).casefold()
        if not target:
            return None

        best_match: tuple[int, SpecSection] | None = None
        for raw_key, raw_value in self._mapping.items():
            section = parse_section_label(raw_value)
            if section is None:
                continue
            key = normalize_item_name(raw_key)
            if not key:
                continue
            key_folded = key.casefold()
            if target == key_folded or target.startswith(f"{key_folded} "):
                key_len = len(key_folded)
                if best_match is None or key_len > best_match[0]:
                    best_match = (key_len, section)

        return best_match[1] if best_match else None

    def has_user_undefined_template(self, item_name: str, *, min_words: int = 2) -> bool:
        """
        True, если для item_name есть пользовательский шаблон "Не определен пользователем"
        (обычно сокращённое полное имя из нескольких слов).
        """
        target = normalize_item_name(item_name).casefold()
        if not target:
            return False
        for raw_key, raw_value in self._mapping.items():
            if raw_value != USER_UNDEFINED_SECTION_LABEL:
                continue
            key = normalize_item_name(raw_key)
            if not key or len(key.split()) < min_words:
                continue
            key_folded = key.casefold()
            if target == key_folded or target.startswith(f"{key_folded} "):
                return True
        return False

    def _drop_redundant_undefined_children(self, name: str) -> None:
        """
        После сохранения шаблона убираем дочерние полные ключи с "Не определен",
        чтобы словарь не разрастался и не провоцировал повторные запросы.
        """
        prefix = normalize_item_name(name).casefold()
        if not prefix:
            return
        to_delete: list[str] = []
        for raw_key, raw_value in self._mapping.items():
            if raw_key == name or raw_value != UNDEFINED_SECTION_LABEL:
                continue
            key = normalize_item_name(raw_key).casefold()
            if key == prefix or key.startswith(f"{prefix} "):
                to_delete.append(raw_key)
        for key in to_delete:
            self._mapping.pop(key, None)
