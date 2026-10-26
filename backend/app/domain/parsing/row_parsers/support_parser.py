import re

from backend.app.domain.models.specification import Support
from backend.app.domain.parsing.support_gost_search_yandex import SupportGostSearch
from .base import SpecRowParser

# Хвост «, ПСИ…» в наименовании опоры (номер монтажной схемы), без обрезки по другим запятым (60,3; 42,4).
_PSI_TAIL_RE = re.compile(r",\s*ПСИ[\w.-]+$", re.IGNORECASE)
# Хвост ячейки «(примечание…).» — не часть наименования; иначе split('. ') режет примечание на «вторую опору».
_TRAILING_PARENS_NOTE_RE = re.compile(r"\(([^)]+)\)\s*\.?\s*$")


def _strip_trailing_support_note_parentheses(name: str) -> str:
    """
    Убирает заключительные скобки с пояснением (марка/изготовление/монтаж/упор),
    чтобы не плодить лишние записи при разборе по «. ».
    Короткие скобки вроде «(кр.)» не трогаем.
    """
    s = (name or "").strip()
    while True:
        m = _TRAILING_PARENS_NOTE_RE.search(s)
        if not m:
            return s
        inner = m.group(1).strip()
        low = inner.lower()
        if len(inner) < 12:
            return s
        is_note = (
            "изготавлива" in low
            or "трубопровод" in low
            or ("на месте" in low and "монтаж" in low)
            or ("упор" in low and "поз" in low)
            or ("марки" in low and "стал" in low)
            or len(inner) >= 60
        )
        if not is_note:
            return s
        s = s[: m.start()].rstrip()


class SupportRowParser(SpecRowParser):
    def __init__(self, gost_search: SupportGostSearch | None = None):
        self._gost_search = gost_search or SupportGostSearch.from_env()

    def parse(self, line: list[str], audit_ctx: dict | None = None):
        if not line[0].isdigit():
            return None

        position = int(line[0])
        unit = line[-2]
        quantity = float(line[-1].replace(",", "."))

        name_str = _strip_trailing_support_note_parentheses(line[1])

        # Разделяем строку на отдельные опоры по точке и пробелу
        parts = name_str.split(". ")
        
        supports = []
        
        for part in parts:
            if not part.strip():
                continue
                
            # Убираем возможные лишние пробелы
            part = part.strip()
            
            # Убираем только хвост ", ПСИ…" (не первую «, » в строке — иначе теряется марка вроде "42, 4-120").
            support_name = _PSI_TAIL_RE.sub("", part).strip() or part.strip()

            support_audit_ctx = dict(audit_ctx or {})
            support_audit_ctx["support_name"] = support_name
            support_audit_ctx["position"] = position
            try:
                gost = self._gost_search.find_gost(support_name, audit_ctx=support_audit_ctx)
            except TypeError:
                # Backward-compatible with test doubles that accept only support_name.
                gost = self._gost_search.find_gost(support_name)

            # Создаем объект Support
            support = Support(
                position=position,
                name=support_name,
                unit=unit,
                quantity=quantity,
                gost=gost,
            )
            supports.append(support)
        
        # Если только одна опора, возвращаем её, а не список
        if len(supports) == 1:
            return supports[0]
        return supports
