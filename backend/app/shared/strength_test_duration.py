from __future__ import annotations

import re


_PAIR_HOURS_MIN_RE = re.compile(
    r"(?P<h>\d+(?:[.,]\d+)?)\s*ч(?:ас(?:а|ов)?)?[^0-9]*(?P<m>\d+(?:[.,]\d+)?)\s*мин",
    re.IGNORECASE,
)
_HOURS_ONLY_RE = re.compile(
    r"(?P<h>\d+(?:[.,]\d+)?)\s*ч(?:ас(?:а|ов)?)?",
    re.IGNORECASE,
)
_FIRST_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
_CANONICAL_RE = re.compile(r"^\d+\s*ч\.\s*\(\d+\s*мин\.\)$", re.IGNORECASE)


def _to_float(raw: str) -> float | None:
    text = (raw or "").strip().replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def format_strength_test_duration(raw_value: str | None) -> str | None:
    """
    Приводит длительность испытания к виду: `X ч. (Y мин.)`.
    Базовый источник — минуты (число), но также поддерживаются варианты
    с явными `ч/мин`.
    """
    text = (raw_value or "").strip()
    if not text:
        return None
    if _CANONICAL_RE.match(text):
        return text

    total_minutes: int | None = None

    pair = _PAIR_HOURS_MIN_RE.search(text)
    if pair:
        h = _to_float(pair.group("h"))
        m = _to_float(pair.group("m"))
        if h is not None and m is not None:
            total_minutes = int(round(h * 60 + m))
    elif "мин" not in text.lower():
        # Если указаны только часы — конвертируем в минуты.
        h_only = _HOURS_ONLY_RE.search(text)
        if h_only:
            h = _to_float(h_only.group("h"))
            if h is not None:
                total_minutes = int(round(h * 60))

    if total_minutes is None:
        number = _FIRST_NUMBER_RE.search(text)
        if number:
            num = _to_float(number.group(0))
            if num is not None:
                total_minutes = int(round(num))

    if total_minutes is None:
        return text
    if total_minutes < 0:
        return text

    hours = total_minutes // 60
    return f"{hours} ч. ({total_minutes} мин.)"
