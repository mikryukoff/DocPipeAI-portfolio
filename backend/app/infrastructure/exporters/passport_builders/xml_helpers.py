from copy import deepcopy
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.table import Table


def _ensure_keep_next(paragraph_el) -> None:
    """Добавляет признак `w:keepNext` в свойства абзаца."""
    pPr = paragraph_el.find(qn("w:pPr"))
    if pPr is None:
        pPr = OxmlElement("w:pPr")
        paragraph_el.insert(0, pPr)
    # Удаляем принудительный разрыв страницы перед абзацем, иначе
    # заголовок может оторваться от таблицы даже при keepNext.
    page_break_before = pPr.find(qn("w:pageBreakBefore"))
    if page_break_before is not None:
        pPr.remove(page_break_before)
    if pPr.find(qn("w:keepNext")) is None:
        pPr.append(OxmlElement("w:keepNext"))


def _create_section_title_element(text: str) -> OxmlElement:
    """
    Создаёт XML-параграф с текстом, выровненным по центру,
    шрифтом Times New Roman, размер 12 pt (val=24 in half-points), жирный.
    Добавляет небольшой отступ сверху для отделения от предыдущей таблицы.
    """
    p = OxmlElement('w:p')

    # Свойства абзаца: выравнивание по центру + отступ сверху.
    pPr = OxmlElement('w:pPr')
    
    # Добавляем небольшой отступ сверху (4 пункта = 80 twips).
    spacing = OxmlElement('w:spacing')
    spacing.set(qn('w:before'), '80')  # 4 пункта = 80 twips
    pPr.append(spacing)
    
    # выравнивание по центру
    jc = OxmlElement('w:jc')
    jc.set(qn('w:val'), 'center')
    pPr.append(jc)

    # Не даём заголовку отрываться от следующего элемента (таблицы).
    keep_next = OxmlElement('w:keepNext')
    pPr.append(keep_next)
    
    p.append(pPr)

    # Текстовый фрагмент.
    r = OxmlElement('w:r')

    # Свойства текстового фрагмента.
    rPr = OxmlElement('w:rPr')

    # Жирное начертание.
    b = OxmlElement('w:b')
    rPr.append(b)

    # Шрифт Times New Roman для ascii и hAnsi.
    rFonts = OxmlElement('w:rFonts')
    rFonts.set(qn('w:ascii'), 'Times New Roman')
    rFonts.set(qn('w:hAnsi'), 'Times New Roman')
    rPr.append(rFonts)

    # Размер 12 пунктов -> 24 полупункта.
    sz = OxmlElement('w:sz')
    sz.set(qn('w:val'), '24')
    rPr.append(sz)

    r.append(rPr)

    # Текстовый узел.
    t = OxmlElement('w:t')
    t.text = text
    r.append(t)

    p.append(r)
    return p


def apply_keep_with_next_before_table(table: Table, max_paragraphs: int = 10) -> None:
    """
    Ставит `keepNext` для абзацев непосредственно перед таблицей.
    Это снижает риск «висячих» заголовков раздела/участка.
    """
    current = table._tbl.getprevious()
    applied = 0
    while current is not None and applied < max_paragraphs:
        if current.tag.endswith("}tbl"):
            break
        if current.tag.endswith("}p"):
            _ensure_keep_next(current)
            applied += 1
        current = current.getprevious()


def copy_table_after(prev_table: Table, spec_page: str, header_rows: int = 1) -> Table:
    """
    Копирует prev_table (xml) и вставляет после неё только копию таблицы.
    НЕ вставляет заголовок!
    """
    tbl = prev_table._tbl
    parent = tbl.getparent()
    index = parent.index(tbl)

    # Копируем таблицу и вставляем после предыдущей
    new_tbl = deepcopy(tbl)
    parent.insert(index + 1, new_tbl)

    # Получаем объект таблицы для новой XML-таблицы.
    new_table = Table(new_tbl, prev_table._parent)
    
    # Очищаем новую таблицу (удаляем все строки кроме строк заголовка)
    while len(new_table.rows) > header_rows:
        new_table._tbl.remove(new_table.rows[header_rows]._tr)
    
    return new_table
