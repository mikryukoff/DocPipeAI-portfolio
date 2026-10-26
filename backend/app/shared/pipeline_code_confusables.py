"""Нормализация кодов линий из актов испытаний / ВИК: похожие буквы → латиница, затем O → 0."""

from __future__ import annotations

import re
from typing import Final

# Двухбуквенный хвост линии (-IP, -IE и т.п.): в нём не заменяем O на 0.
_PIPELINE_OPTIONAL_SUFFIX: Final = re.compile(r"-[A-Za-z]{2}$")


def _build_lookalike_letter_to_latin_table() -> dict[int, str]:
    """
    Один символ → одна латинская буква/цифра (визуально похожие кириллица, греческие, fullwidth).
    Цель — привести «псевдолатинский» код из Excel к ASCII перед заменой O на ноль.
    """
    m: dict[int, str] = {}

    def add(pairs: dict[str, str]) -> None:
        for k, v in pairs.items():
            m[ord(k)] = v

    # Кириллица (типичные подмены в технических строках)
    add(
        {
            "А": "A",
            "а": "a",
            "Б": "B",
            "б": "b",
            "В": "B",
            "в": "b",
            "Г": "G",
            "г": "g",
            "Д": "D",
            "д": "d",
            "Е": "E",
            "е": "e",
            "Ё": "E",
            "ё": "e",
            "Ж": "X",
            "ж": "x",
            "З": "3",
            "з": "3",
            "И": "I",
            "и": "i",
            "Й": "J",
            "й": "j",
            "К": "K",
            "к": "k",
            "Л": "L",
            "л": "l",
            "М": "M",
            "м": "m",
            "Н": "H",
            "н": "h",
            "О": "O",
            "о": "o",
            "П": "n",
            "п": "n",
            "Р": "P",
            "р": "p",
            "С": "C",
            "с": "c",
            "Т": "T",
            "т": "t",
            "У": "Y",
            "у": "y",
            "Ф": "F",
            "ф": "f",
            "Х": "X",
            "х": "x",
            "Ц": "U",
            "ц": "u",
            "Ч": "4",
            "ч": "4",
            "Ш": "W",
            "ш": "w",
            "Щ": "W",
            "щ": "w",
            "Ъ": "b",
            "ъ": "b",
            "Ы": "Y",
            "ы": "y",
            "Ь": "b",
            "ь": "b",
            "Э": "E",
            "э": "e",
            "Ю": "U",
            "ю": "u",
            "Я": "A",
            "я": "a",
            "І": "I",
            "і": "i",
            "Є": "E",
            "є": "e",
            "Ґ": "G",
            "ґ": "g",
        }
    )

    # Греческие буквы, похожие на латиницу
    add(
        {
            "\u0391": "A",
            "\u03b1": "a",
            "\u0392": "B",
            "\u03b2": "b",
            "\u0393": "G",
            "\u03b3": "g",
            "\u0394": "D",
            "\u03b4": "d",
            "\u0395": "E",
            "\u03b5": "e",
            "\u0396": "Z",
            "\u03b6": "z",
            "\u0397": "H",
            "\u03b7": "h",
            "\u0398": "O",
            "\u03b8": "o",
            "\u0399": "I",
            "\u03b9": "i",
            "\u039a": "K",
            "\u03ba": "k",
            "\u039b": "L",
            "\u03bb": "l",
            "\u039c": "M",
            "\u03bc": "m",
            "\u039d": "N",
            "\u03bd": "n",
            "\u039e": "E",
            "\u03be": "e",
            "\u039f": "O",
            "\u03bf": "o",
            "\u03a0": "P",
            "\u03c0": "p",
            "\u03a1": "P",
            "\u03c1": "p",
            "\u03a3": "S",
            "\u03c3": "s",
            "\u03a4": "T",
            "\u03c4": "t",
            "\u03a5": "Y",
            "\u03c5": "y",
            "\u03a6": "F",
            "\u03c6": "f",
            "\u03a7": "X",
            "\u03c7": "x",
            "\u03a9": "O",
            "\u03c9": "o",
        }
    )

    # Fullwidth латиница и цифры
    for i in range(26):
        m[0xFF21 + i] = chr(ord("A") + i)
        m[0xFF41 + i] = chr(ord("a") + i)
    for i in range(10):
        m[0xFF10 + i] = str(i)

    return m


_LETTERS_LOOKALIKE_TO_LATIN = str.maketrans(_build_lookalike_letter_to_latin_table())

_O_LIKE_TO_ZERO = str.maketrans(
    {
        "O": "0",
        "o": "0",
        "О": "0",
        "о": "0",
        "\u0398": "0",  # Greek capital theta (часто вместо нуля)
        "\u03b8": "0",
        "\u039f": "0",
        "\u03bf": "0",
        "\uff2f": "0",
        "\uff4f": "0",
    }
)

# Если после этапа 1 остались смешанные суффиксы (лат. I + кирил. Е)
_SUFFIX_MIXED_FIXES: Final = (
    ("-IЕ", "-IE"),
    ("-iе", "-IE"),
    ("-ИЕ", "-IE"),
    ("-IП", "-IP"),
    ("-iп", "-IP"),
    ("-ИП", "-IP"),
)


def _letters_lookalike_to_latin(s: str) -> str:
    """Этап 1: каждая похожая буква → латинский эквивалент (один символ)."""
    if not s:
        return s
    return s.translate(_LETTERS_LOOKALIKE_TO_LATIN)


def _o_variants_to_zero_in_body_preserving_suffix(s: str) -> str:
    """Этап 2: O/О/омикрон/… → 0 в теле кода; двухбуквенный хвост -IP/-IE не трогаем."""
    m = _PIPELINE_OPTIONAL_SUFFIX.search(s)
    if m:
        body, tail = s[: m.start()], m.group(0)
    else:
        body, tail = s, ""
    out = body.translate(_O_LIKE_TO_ZERO) + tail
    for bad, good in _SUFFIX_MIXED_FIXES:
        if out.endswith(bad):
            return out[: -len(bad)] + good
    return out


def normalize_pipeline_code_confusable_o_to_zero(name: str) -> str:
    """
    Нормализация имени линии из документов испытаний.

    1. Похожие на латиницу символы (кириллица, греческие «двойники», fullwidth) → ASCII-буквы/цифры.
    2. В теле кода (до суффикса -IP/-IE) все варианты «O как ноль» → цифра 0.
    """
    s = (name or "").strip()
    if not s:
        return s
    s = _letters_lookalike_to_latin(s)
    return _o_variants_to_zero_in_body_preserving_suffix(s)
