"""Извлечение имени/номера трубопровода из ячеек PDF, Excel, Word."""

from __future__ import annotations

import re

# Код линии: буквы/цифры, дефисы, например XX01-41086-WSL-50-E010H2A00
PIPELINE_CODE_RE = re.compile(r"^[A-Z0-9]+-[A-Z0-9]+-.*\d.*$", re.IGNORECASE)
LINE_ID_AFTER_PREFIX_RE = re.compile(r"^линия\s+(\S+)", re.IGNORECASE)
LINE_IN_TEXT_RE = re.compile(r"линия\s*([^:;(\n\r,]+)", re.IGNORECASE)

BAD_PIPELINE_NAMES = frozenset(
    {"производственный", "поз", "лист", "листов", "стр", "стр.", "линия"}
)


def is_cyrillic_line_number(name: str) -> bool:
    """Номер с кириллицей — не прогонять через латинскую нормализацию кодов."""
    if looks_like_pipeline_code(name):
        return False
    return bool(re.search(r"[А-Яа-яЁё]", name or ""))


def is_plausible_line_designation(label: str) -> bool:
    """
    Отсекает короткие чисто цифровые индексы («Линия 1» → «1» в СоМТТ).
    Длинные номера вроде «41079» в актах испытаний допускаются.
    """
    s = (label or "").strip()
    if not s or s.lower() in BAD_PIPELINE_NAMES:
        return False
    if s.isdigit() and len(s) < 4:
        return False
    return True


def looks_like_pipeline_code(name: str) -> bool:
    if not name or not name.strip():
        return False
    n = name.strip()
    if n.lower() in BAD_PIPELINE_NAMES:
        return False
    if PIPELINE_CODE_RE.match(n):
        return True
    # Расширенные коды из DOCX (точки в сегментах): XX00-00000.00-ABC-01-NAME
    if (
        len(n) >= 12
        and n.count("-") >= 2
        and re.fullmatch(r"[A-Z0-9][A-Z0-9.\-]*", n, re.IGNORECASE)
    ):
        return True
    return False


def _first_line_id_token(raw_tail: str) -> str:
    """Первый токен после слова «Линия»; отрезает «(№110)» и описание установки."""
    token = (raw_tail or "").strip().split()[0] if raw_tail else ""
    if not token:
        return ""
    return re.split(r"[(,;:]", token, maxsplit=1)[0].strip().rstrip(".").strip()


def extract_line_id_token(text: str) -> str | None:
    """Номер сразу после «Линия» (ТТ5, 41079), без слова «Линия» и без хвоста описания."""
    raw = (text or "").strip()
    if not raw:
        return None
    match = LINE_ID_AFTER_PREFIX_RE.match(raw)
    if match:
        token = _first_line_id_token(match.group(1))
        return token or None
    match = LINE_IN_TEXT_RE.search(raw)
    if match:
        token = _first_line_id_token(match.group(1))
        return token or None
    return None


def extract_line_pipeline_name(text: str) -> str | None:
    """«Линия ТТ5 Выпарная установка» → «ТТ5»."""
    line_id = extract_line_id_token(text)
    if not line_id or not is_plausible_line_designation(line_id):
        return None
    return line_id


def extract_line_designation_after_prefix(text: str) -> str | None:
    return extract_line_id_token(text)


def extract_pipeline_name_after_line_keyword(text: str) -> str:
    return extract_line_pipeline_name(text) or ""


def extract_pipeline_name_from_cell(raw: str) -> str:
    """
    Имя линии из значения ячейки:
    - полный код (XX01-…);
    - «Линия ТТ5 …» → «ТТ5»;
    - иначе вся ячейка целиком.
    """
    text = (raw or "").strip()
    if not text:
        return ""
    if looks_like_pipeline_code(text):
        return text
    line_name = extract_line_pipeline_name(text)
    if line_name:
        return line_name
    return text


def collect_pipeline_names_from_cell(raw: str) -> set[str]:
    """Все кандидаты из одной ячейки: коды по шаблону и номера после «Линия»."""
    text = (raw or "").strip()
    if not text:
        return set()
    found: set[str] = set()
    upper = text.upper()
    for match in re.finditer(
        r"[A-Z]{2}\d{2}-\d{5}(?:\.\d+)?-[A-Z]{3}-\d{2,3}-[A-Z0-9-]+(?:-[A-Z]{2})?",
        upper,
    ):
        found.add(match.group(0))
    line_name = extract_line_pipeline_name(text)
    if line_name:
        found.add(line_name)
    for match in LINE_IN_TEXT_RE.finditer(text):
        token = _first_line_id_token(match.group(1))
        if is_plausible_line_designation(token):
            found.add(token)
    return found
