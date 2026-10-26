"""Единая нормализация номеров приборов (JSON drawing_4, спецификация, админ-список)."""

from __future__ import annotations

import unicodedata

# Только кириллица, визуально совпадающая с латиницей (чертежи/ОCR: Р→P, А→A, Н→H, …).
# Остальные русские буквы не трогаем.
_CYRILLIC_LATIN_HOMOGLYPH_MAP: dict[str, str] = {
    "А": "A",
    "а": "a",
    "В": "B",
    "в": "b",
    "С": "C",
    "с": "c",
    "Е": "E",
    "е": "e",
    "Ё": "E",
    "ё": "e",
    "Н": "H",
    "н": "h",
    "К": "K",
    "к": "k",
    "М": "M",
    "м": "m",
    "О": "O",
    "о": "o",
    "П": "P",
    "п": "p",
    "Р": "P",
    "р": "p",
    "Т": "T",
    "т": "t",
    "У": "U",
    "у": "u",
    "Х": "X",
    "х": "x",
    "І": "I",
    "і": "i",
}

_HOMOGLYPH_TRANSLATE = str.maketrans(_CYRILLIC_LATIN_HOMOGLYPH_MAP)

# Обратная подстановка: только строчная латиница → строчная кириллица (для восстановления описаний).
_LATIN_LOWER_TO_CYR_HOMOGLYPH: dict[str, str] = {}
for _cyr, _lat in _CYRILLIC_LATIN_HOMOGLYPH_MAP.items():
    if len(_cyr) == 1 and len(_lat) == 1 and _lat.isascii() and _lat.islower():
        _LATIN_LOWER_TO_CYR_HOMOGLYPH[_lat] = _cyr
# «e» и «p» заданы дважды в карте — фиксируем типичное для текста
_LATIN_LOWER_TO_CYR_HOMOGLYPH["e"] = "е"
_LATIN_LOWER_TO_CYR_HOMOGLYPH["p"] = "р"
_LATIN_LOWER_HOMOGLYPH_REVERSE_TRANSLATE = str.maketrans(_LATIN_LOWER_TO_CYR_HOMOGLYPH)


def cyrillic_to_latin_for_instrument_tag(text: str) -> str:
    """
    Заменяет только кириллические буквы, похожие на латинские, на соответствующую латиницу
    (например Р→P, А→A, Н→H, В→B). Прочая кириллица не меняется.
    """
    if not text:
        return text
    return text.translate(_HOMOGLYPH_TRANSLATE)


def latin_homoglyph_lowercase_to_cyrillic(text: str) -> str:
    """
    Обратная к омоглифам подстановка: **только строчные** латинские a–z из набора
    (a→а, b→в, …, как в _CYRILLIC_LATIN_HOMOGLYPH_MAP). Заглавные латинские и цифры не трогает.
    Для восстановления русских описаний в закладных; номера приборов не передавать в эту функцию.
    """
    if not text:
        return text
    return text.translate(_LATIN_LOWER_HOMOGLYPH_REVERSE_TRANSLATE)


# Типографские/полноширинные дефисы → ASCII (как в InstrumentEmbedmentService)
_INSTRUMENT_TAG_DASH_TRANSLATE = str.maketrans(
    {
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
        "\uFE58": "-",
        "\uFE63": "-",
        "\uFF0D": "-",
    }
)

# Невидимые символы из PDF/OCR/вставки из буфера — иначе «одинаковые» теги не схлопываются
_ZERO_WIDTH = ("\u200b", "\u200c", "\u200d", "\ufeff", "\u2060")


def normalize_instrument_tag_label(raw: object) -> str:
    """NFKC, кириллица «как латиница»→латиница, дефисы ASCII, убрать ZWSP/BOM, схлопнуть пробелы (без смены регистра)."""
    s = unicodedata.normalize("NFKC", str(raw or ""))
    s = cyrillic_to_latin_for_instrument_tag(s)
    s = s.translate(_INSTRUMENT_TAG_DASH_TRANSLATE)
    for ch in _ZERO_WIDTH:
        s = s.replace(ch, "")
    return " ".join(s.split()).strip()


def normalize_embedment_auxiliary_text(raw: object) -> str:
    """
    NFKC, дефисы ASCII, ZWSP/BOM, пробелы — **без** замены кириллицы на латиницу.
    Для описаний, dn/pn как в таблице и т.п.; номера приборов — только через normalize_instrument_tag_label.
    """
    s = unicodedata.normalize("NFKC", str(raw or ""))
    s = s.translate(_INSTRUMENT_TAG_DASH_TRANSLATE)
    for ch in _ZERO_WIDTH:
        s = s.replace(ch, "")
    return " ".join(s.split()).strip()


def instrument_tag_dedup_key(raw: object) -> str:
    """Ключ для сравнения и дедупа: как normalize + регистр не важен."""
    return normalize_instrument_tag_label(raw).casefold()
