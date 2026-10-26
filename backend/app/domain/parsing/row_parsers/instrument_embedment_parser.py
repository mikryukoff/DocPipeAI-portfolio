import re

from loguru import logger

from backend.app.domain.models.specification import InstrumentEmbedment
from backend.app.domain.parsing.drawing_4_store import get_drawing_4_store
from backend.app.domain.parsing.drawing_tag_normalize import normalize_instrument_tag_label

from .base import SpecRowParser

_INSTRUMENT_RE = re.compile(
    r"закладная\s+для\s+прибора\s+(.+)",
    re.IGNORECASE | re.DOTALL,
)


def normalize_instrument_number(fragment: str) -> str:
    """Оставляет только обозначение прибора, без хвоста «(см. шт. …)», «см. …» и т.п."""
    s = (fragment or "").strip().rstrip(".,;")
    if not s:
        return ""
    if "(" in s:
        s = s.split("(", 1)[0].strip()
    low = s.lower()
    for marker in (" см.", " см "):
        idx = low.find(marker)
        if idx != -1:
            s = s[:idx].strip()
            break
    s = s.rstrip(".,;")
    return normalize_instrument_tag_label(s)


# Колонка spec_items.unit — String(10); ед. изм. и количество для закладных
# заполняются с фронта после ручного ввода, из PDF не переносим (часто съезжают колонки).
_EMBEDMENT_PLACEHOLDER_UNIT = "---"
_EMBEDMENT_PLACEHOLDER_QTY = 0.0


class InstrumentEmbedmentRowParser(SpecRowParser):
    def parse(self, line: list[str], _pipeline_name: str):
        if not line or not line[0].isdigit():
            return None

        position = int(line[0])
        # При классической таблице (№, наименование, ед., кол.) не склеиваем ед./кол-во в имя.
        # Если колонок мало — всё после номера в одну строку (частый случай PDF).
        if len(line) >= 4:
            raw_name = " ".join((c or "").strip() for c in line[1:-2]).strip()
        else:
            tail = [((c or "").strip()) for c in line[1:] if (c or "").strip()]
            raw_name = " ".join(tail).strip()
        if not raw_name:
            return None

        m = _INSTRUMENT_RE.search(raw_name)
        instrument_tag = normalize_instrument_number(m.group(1)) if m else ""

        store = get_drawing_4_store()
        entry = store.resolve(instrument_tag) if instrument_tag else None
        drawing_path = entry.path if entry else ""
        group_key = entry.group_key if entry else ""
        if instrument_tag and entry is None:
            logger.warning(
                "Instrument embedment: tag not in data/ocr/parsed_texts JSON. tag={} name={}",
                instrument_tag,
                raw_name[:120],
            )

        # В БД и домене храним только номер прибора; полный текст из PDF не дублируем.
        display_name = instrument_tag or raw_name.strip()

        return InstrumentEmbedment(
            position=position,
            name=display_name,
            unit=_EMBEDMENT_PLACEHOLDER_UNIT,
            quantity=_EMBEDMENT_PLACEHOLDER_QTY,
            location="---",
            instrument_tag=instrument_tag,
            drawing_image_path=drawing_path,
            embedment_group_key=group_key,
        )
