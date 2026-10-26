import re

from loguru import logger

from backend.app.domain.models.specification import Specification
from backend.app.domain.models.spec_section import SpecSection
from backend.app.domain.parsing.specification.row_parser_registry import SpecRowParserRegistry
from backend.app.domain.parsing.specification.spec_section_mapping_store import (
    SpecSectionMappingStore,
    UndefinedSpecSectionError,
    extract_base_item_name,
    normalize_item_name,
    USER_UNDEFINED_SECTION_LABEL,
    UNDEFINED_SECTION_LABEL,
)
from backend.app.shared.pipeline_row_logger import log_pipeline_row
from backend.app.shared.parsing_audit_logger import log_parsing_event


class SpecificationParser:
    # Маркеры "чужой" нижней таблицы (сварка/стыки), после которых
    # спецификацию нужно завершать, чтобы не забирать лишние строки.
    NON_SPEC_TABLE_MARKERS = (
        "ф.и.о. сварщика",
        "номер удостоверения",
        "клеймо сварщика",
        "количество стыков",
        "кол-во стыков",
        "общее кол-во стыков",
        "общее количество стыков",
        "№ соединения",
        "длина шва",
        "толщина стенки",
        "сварных соединений",
        "№",
        "№п/п",
        "№ п / п",
    )
    _FRAGMENTED_ROW_RE = re.compile(
        r"("
        r"\bпо\s+en\b|"
        r"\ben\s*\d{2,}(?:-\d+)*\b|"
        r"\bdn\s*\d+\b|"
        r"\bpn\s*\d+\b|"
        r"\bматериал\b|"
        r"\bшт\.?\b|"
        r"\d+[,.]?\d*\s*[xх]\s*\d+[,.]?\d*"
        r")",
        flags=re.IGNORECASE,
    )
    # Целая позиция, опционально с подномерами: 3, 3.1, 3.2.1, 3,1, 3/1 (как на чертежах).
    _POSITION_RE = re.compile(r"^\s*(\d+)(?:[.,]\d+)*(?:/\s*\d+)?\s*$")
    _FIRST_WORD_TRUBA_RE = re.compile(r"^(труба|трубы)\b", re.IGNORECASE)
    _FIRST_WORD_OPORA_RE = re.compile(r"^(опора|опоры)\b", re.IGNORECASE)
    _WORD_PODVESKA_RE = re.compile(r"\bподвес\w*\b", re.IGNORECASE)
    # Заголовки разделов паспорта внутри одной «простыни» (кроп всей таблицы как одна строка).
    _SPEC_SECTION_TITLE_MARKERS = (
        "соединительные детали",
        "арматура",
        "закладн",
        "фланцы",
        "опоры",
    )
    _SPEC_ITEM_HEAD_RE = re.compile(
        r"\b(труба|трубы|колено|фланец|заглушка|тройник|задвижка|опора|опоры)\b",
        re.IGNORECASE,
    )
    _MERGED_TABLE_BLOB_MIN_CHARS = 180

    def __init__(
        self,
        job_id: int | None = None,
        source: str | None = None,
        user_log_key: str | None = None,
    ):
        self.registry = SpecRowParserRegistry()
        self.mapping_store = SpecSectionMappingStore()
        self._warnings: list[dict] = []
        self.job_id = job_id
        self.source = source
        self.user_log_key = user_log_key

    @classmethod
    def _is_non_spec_table_row(cls, row: list[str]) -> bool:
        row_text = " ".join((c or "").strip().lower() for c in row if c)
        if not row_text:
            return False
        return any(marker in row_text for marker in cls.NON_SPEC_TABLE_MARKERS)

    @classmethod
    def _is_merged_spec_table_blob(cls, row: list[str]) -> bool:
        """
        PDF/OCR иногда отдаёт весь кроп спецификации одной строкой (2–3 ячейки,
        без номера позиции в col0). Это не элемент спецификации.
        """
        cells = [str(c).strip() for c in row if str(c).strip()]
        if not cells:
            return False
        if len(cells) == 4 and cls._parse_position(cells[0]) is not None:
            return False
        row_text = " ".join(cells)
        row_lower = row_text.lower()
        if len(row_text) < 80:
            return False
        if cls._parse_position(cells[0]) is not None:
            return False
        section_titles = sum(
            1 for marker in cls._SPEC_SECTION_TITLE_MARKERS if marker in row_lower
        )
        if section_titles >= 2:
            return True
        if len(cls._SPEC_ITEM_HEAD_RE.findall(row_text)) >= 3:
            return True
        if len(row_text) >= cls._MERGED_TABLE_BLOB_MIN_CHARS and len(cells) <= 3:
            return True
        if len(row_text) >= 320:
            return True
        return False

    @classmethod
    def _should_stop_spec_parse(cls, row: list[str]) -> bool:
        return cls._is_non_spec_table_row(row) or cls._is_merged_spec_table_blob(row)

    def parse(self, rows: list[list[str]], page: str, pipeline_name: str) -> Specification:
        spec = Specification(
            pipeline_armature=[],
            instrument_embedments=[],
            pipes=[],
            connection_parts=[],
            flanges=[],
            supports=[],
            page=page,
        )

        has_parsed_data = False

        for row in rows:
            if not row:
                continue

            # Внизу листа часто есть таблица сварных соединений с похожей
            # структурой колонок (№, наименование/значения, ед., кол-во).
            # Это не часть спецификации, поэтому останавливаем разбор.
            if self._should_stop_spec_parse(row) and has_parsed_data:
                logger.debug("Stop specification parse on non-spec or merged-table row: {}", row)
                break

            first_cell_raw = (row[0] or "").strip()
            first_cell = first_cell_raw.lower()
            # Строка заголовка спецификации (№п/п, №) не является концом таблицы.
            # Её нужно пропустить и продолжить разбор следующих строк.
            if "№п/п" in first_cell or first_cell == "№":
                continue

            # Заголовки разделов больше не управляют маршрутизацией строк:
            # раздел определяем по имени элемента через словарь.
            if len(row) == 1 and all(c.isalpha() or c.isspace() for c in row[0]):
                continue

            position = self._parse_position(first_cell_raw)
            if position is None:
                if has_parsed_data and self._looks_like_fragmented_spec_row(row):
                    self._warnings.append(
                        {
                            "kind": "warning",
                            "pipeline": pipeline_name,
                            "page": page,
                            "section": "specification",
                            "item_name": None,
                            "full_name": None,
                            "row": row,
                            "error": "spec_position_missing_or_invalid",
                        }
                    )
                    log_parsing_event(
                        job_id=self.job_id,
                        user_log_key=self.user_log_key,
                        source_type=self._source_type(),
                        source_file=self.source or "unknown",
                        parser="SpecificationParser",
                        entity="spec_item",
                        entity_id=pipeline_name,
                        field="specification",
                        value="spec_position_missing_or_invalid",
                        status="warning",
                        note="spec_item_row_must_start_with_numeric_position",
                        origin={
                            "page": page,
                            "row_text": " | ".join(str(x) for x in row if str(x).strip()),
                        },
                    )
                continue

            normalized_row = list(row)
            normalized_row[0] = str(position)

            full_name = normalize_item_name(self._extract_item_name(row))
            if not full_name:
                continue
            if not self._starts_with_letter(full_name):
                self._warnings.append(
                    {
                        "kind": "warning",
                        "pipeline": pipeline_name,
                        "page": page,
                        "section": "specification",
                        "item_name": full_name,
                        "full_name": full_name,
                        "row": row,
                        "error": "spec_item_name_must_start_with_letter",
                    }
                )
                log_parsing_event(
                    job_id=self.job_id,
                    user_log_key=self.user_log_key,
                    source_type=self._source_type(),
                    source_file=self.source or "unknown",
                    parser="SpecificationParser",
                    entity="spec_item",
                    entity_id=pipeline_name,
                    field="specification",
                    value="spec_item_name_must_start_with_letter",
                    status="warning",
                    note="spec_item_name_should_start_with_letter",
                    origin={
                        "page": page,
                        "row_text": " | ".join(str(x) for x in row if str(x).strip()),
                    },
                )
                continue

            section, unresolved_name = self._resolve_section_by_name(full_name)
            if section is None:
                # Пользователь дважды пометил элемент как "Не определен пользователем":
                # не сохраняем в БД и не блокируем дальнейший парсинг.
                if unresolved_name is None:
                    has_parsed_data = True
                    continue
                self._warnings.append(
                    {
                        "kind": "section_undefined",
                        "pipeline": pipeline_name,
                        "page": page,
                        "section": "not_defined",
                        "item_name": unresolved_name,
                        "full_name": full_name,
                        "row": row,
                        "error": "spec_section_not_defined",
                    }
                )
                raise UndefinedSpecSectionError(
                    item_name=unresolved_name,
                    full_name=full_name,
                    row=row,
                    page=page,
                )

            parser = self.registry.get(section)
            if not parser:
                continue

            # Логируем все строки спецификации для последующего анализа.
            log_pipeline_row(
                job_id=self.job_id,
                user_log_key=self.user_log_key,
                source=self.source,
                pipeline=pipeline_name,
                page=page,
                row_type=str(section),
                row=row,
            )

            try:
                if section in (
                    SpecSection.PIPELINE_ARMATURE,
                    SpecSection.INSTRUMENT_EMBEDMENT,
                ):
                    result = parser.parse(normalized_row, pipeline_name)
                elif section == SpecSection.SUPPORTS:
                    result = parser.parse(
                        normalized_row,
                        audit_ctx={
                            "job_id": self.job_id,
                            "user_log_key": self.user_log_key,
                            "source_type": self._source_type(),
                            "source_file": self.source or "unknown",
                            "pipeline_name": pipeline_name,
                            "page": page,
                            "row_text": " | ".join(str(x) for x in row if str(x).strip()),
                        },
                    )
                else:
                    result = parser.parse(normalized_row)
            except Exception as exc:  # noqa: BLE001 - хотим перехватывать любые парсинговые ошибки
                self._warnings.append(
                    {
                        "pipeline": pipeline_name,
                        "page": page,
                        "section": getattr(section, "name", str(section)),
                        "item_name": full_name,
                        "full_name": full_name,
                        "row": row,
                        "error": str(exc),
                    }
                )
                log_parsing_event(
                    job_id=self.job_id,
                    user_log_key=self.user_log_key,
                    source_type=self._source_type(),
                    source_file=self.source or "unknown",
                    parser="SpecificationParser",
                    entity="spec_item",
                    entity_id=pipeline_name,
                    field=str(section.value),
                    value="parse_error",
                    status="warning",
                    note=str(exc),
                    origin={
                        "page": page,
                        "row_text": " | ".join(str(x) for x in row if str(x).strip()),
                        "item_name": full_name,
                    },
                )
                continue

            if not result:
                continue

            if not isinstance(result, list):
                result = [result]

            getattr(spec, section.value).extend(result)
            has_parsed_data = True
            for parsed_item in result:
                item_name = getattr(parsed_item, "name", "") or full_name
                log_parsing_event(
                    job_id=self.job_id,
                    user_log_key=self.user_log_key,
                    source_type=self._source_type(),
                    source_file=self.source or "unknown",
                    parser="SpecificationParser",
                    entity="spec_item",
                    entity_id=pipeline_name,
                    field=str(section.value),
                    value=item_name,
                    origin={
                        "page": page,
                        "row_text": " | ".join(str(x) for x in row if str(x).strip()),
                        "item_name": full_name,
                    },
                )

        return spec

    @classmethod
    def _looks_like_fragmented_spec_row(cls, row: list[str]) -> bool:
        cells = [str(c).strip() for c in row if str(c).strip()]
        if not cells:
            return False
        row_text = " ".join(cells)
        if len(row_text) < 6:
            return False
        return bool(cls._FRAGMENTED_ROW_RE.search(row_text))

    @classmethod
    def _parse_position(cls, value: str) -> int | None:
        match = cls._POSITION_RE.match(value or "")
        if not match:
            return None
        return int(match.group(1))

    @staticmethod
    def _starts_with_letter(value: str) -> bool:
        text = (value or "").strip()
        if not text:
            return False
        return text[0].isalpha()

    def _source_type(self) -> str:
        source = (self.source or "").lower()
        if source.endswith(".pdf"):
            return "pdf"
        if source.endswith(".xlsx") or source.endswith(".xls"):
            return "excel"
        if source.endswith(".csv"):
            return "csv"
        return "other"

    def pop_warnings(self) -> list[dict]:
        warnings = self._warnings
        self._warnings = []
        return warnings

    @staticmethod
    def _extract_item_name(row: list[str]) -> str:
        if len(row) >= 4:
            return " ".join((c or "").strip() for c in row[1:-2]).strip()
        if len(row) >= 2:
            return (row[1] or "").strip()
        return ""

    def _resolve_section_by_name(
        self,
        full_name: str,
    ) -> tuple[SpecSection | None, str | None]:
        # Защитное правило: базовые категории 4.1/4.3 определяем по первому слову.
        # Это предотвращает ошибки от случайно испорченных пользовательских маппингов.
        normalized_full_name = normalize_item_name(full_name)
        if self._FIRST_WORD_TRUBA_RE.match(normalized_full_name):
            return SpecSection.PIPES, None
        if self._FIRST_WORD_OPORA_RE.match(normalized_full_name) or self._WORD_PODVESKA_RE.search(normalized_full_name):
            return SpecSection.SUPPORTS, None

        # 1) Точное совпадение полного имени.
        full_value = self.mapping_store.get_raw_value(full_name)
        if full_value == USER_UNDEFINED_SECTION_LABEL:
            return None, None
        full_section = self.mapping_store.resolve_section(full_name)
        if full_section is not None:
            return full_section, None
        # Если есть пользовательский сокращённый шаблон "Не определен пользователем"
        # (например "Электромагнитный расходомер фланцевый"), все совпадающие полные
        # имена молча пропускаем без повторного запроса.
        if self.mapping_store.has_user_undefined_template(full_name, min_words=2):
            return None, None

        # 2) Базовый ключ для инженеров: первое слово имени (например "Арматура", "Колено").
        base_name = extract_base_item_name(full_name)
        if not base_name:
            return None, full_name
        base_value = self.mapping_store.get_raw_value(base_name)
        if base_value == USER_UNDEFINED_SECTION_LABEL:
            # Пользователь явно попросил уточнять по полному имени.
            full_value = self.mapping_store.get_raw_value(full_name)
            if full_value is None:
                self.mapping_store.ensure_item(full_name)
                return None, full_name
            if full_value == USER_UNDEFINED_SECTION_LABEL:
                return None, None
            if full_value == UNDEFINED_SECTION_LABEL:
                return None, full_name
            full_section = self.mapping_store.resolve_section(full_name)
            return full_section, None

        if full_value == UNDEFINED_SECTION_LABEL:
            # Для полного имени уже есть "Не определен", но инженеры могли добавить
            # сокращённый шаблон (префикс). Если resolve_section выше не нашёл секцию,
            # тогда действительно ждём уточнение по полному имени.
            return None, full_name

        if base_value == UNDEFINED_SECTION_LABEL:
            return None, base_name

        base_section = self.mapping_store.resolve_section(base_name)
        if base_section is not None:
            return base_section, None

        self.mapping_store.ensure_item(base_name)
        return None, base_name
