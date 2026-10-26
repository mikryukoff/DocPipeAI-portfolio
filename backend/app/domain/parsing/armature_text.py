"""Общие правила выделения русского наименования арматуры и головы до DN/PN."""

from __future__ import annotations

import re


def _find_first_non_decimal_comma(text: str) -> int:
    for idx, ch in enumerate(text):
        if ch != ",":
            continue
        left = idx - 1
        while left >= 0 and text[left].isspace():
            left -= 1
        right = idx + 1
        while right < len(text) and text[right].isspace():
            right += 1
        left_is_digit = left >= 0 and text[left].isdigit()
        right_is_digit = right < len(text) and text[right].isdigit()
        if left_is_digit and right_is_digit:
            continue
        return idx
    return -1


def bilingual_head_before_dn(description: str) -> str:
    """Строка вида «Рус / English …» до первого DN/PN — для точного совпадения с ключами JSON."""
    text = str(description or "").strip()
    text = text.split("(", 1)[0].strip()
    for pat in (r"\bDN\s*[0-9]", r"\bPN\s*[0-9]"):
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            text = text[: m.start()].strip()
    return re.sub(r"\s+", " ", text).strip(" -,\t'\"«»")


def extract_russian_base_name(description: str) -> str:
    """Русская часть наименования (без английского хвоста после «/» и пр.)."""
    base = str(description or "").strip()
    base = base.split("/", 1)[0]
    base = base.split("(", 1)[0]
    comma_idx = _find_first_non_decimal_comma(base)
    if comma_idx >= 0:
        base = base[:comma_idx]
    base = re.sub(r"\s*мпа\.?\s*$", "", base, flags=re.IGNORECASE)
    base = re.sub(
        r"^[\"'«»\s]*[A-ZА-ЯЁ]{2,12}\s*№\s*[A-ZА-ЯЁ0-9._/-]+\s*",
        "",
        base,
        flags=re.IGNORECASE,
    )
    base = re.sub(r"\s+", " ", base).strip(" -\t'\"«»")
    return base
