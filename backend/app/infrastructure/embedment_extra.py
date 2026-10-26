"""Проверка заполненности extra у закладных (общее для репозитория пайплайна и черновиков)."""


def embedment_draft_dedup_key(drawing_path: str, use_key: str) -> str:
    """Один черновик на скрин (path) или на канонический ключ группы."""
    p = (drawing_path or "").strip().replace("\\", "/")
    if p:
        return f"path:{p}"
    gk = (use_key or "").strip()
    return f"gk:{gk}" if gk else "gk:default"


def element_row_filled(el: dict) -> bool:
    nm = (el.get("name") or "").strip()
    return bool(nm and nm != "---")


def instrument_embedment_extra_enriched(extra: dict | None) -> bool:
    ex = extra or {}
    if ex.get("source_manual_embedment"):
        return True
    raw_el = ex.get("embedment_elements")
    if isinstance(raw_el, list) and len(raw_el) > 0:
        tag = str(ex.get("instrument_tag") or "").strip()
        if len(raw_el) == 1 and tag:
            one = raw_el[0]
            if isinstance(one, dict):
                nm = str(one.get("name") or "").strip()
                if nm == tag:
                    return True
        for item in raw_el:
            if not isinstance(item, dict) or not element_row_filled(item):
                return False
        return True
    dn = (ex.get("dn") or "").strip()
    mg = (ex.get("material_grade") or "").strip()
    gost = (ex.get("gost") or "").strip()
    return bool(dn and dn != "---" and mg and mg != "---" and gost and gost != "---")
