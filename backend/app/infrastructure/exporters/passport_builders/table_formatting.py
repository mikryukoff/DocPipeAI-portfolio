from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_ALIGN_VERTICAL, WD_ROW_HEIGHT_RULE
from docx.oxml.ns import qn
from docx.oxml import OxmlElement


def _set_row_cant_split(row) -> None:
    """Запрещает Word разрывать одну строку таблицы между страницами."""
    tr = row._tr
    trPr = tr.get_or_add_trPr()
    existing = trPr.findall(qn("w:cantSplit"))
    if not existing:
        trPr.append(OxmlElement("w:cantSplit"))


def _set_row_auto_height(row) -> None:
    """
    Убирает риск обрезания текста в строках, которые могли унаследовать
    фиксированную высоту из шаблона.
    Режим AT_LEAST позволяет Word увеличивать высоту строки по содержимому.
    """
    row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
    row.height = None

def _set_cell_borders(cell, color: str = "000000") -> None:
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    # удаляем старые
    existing = tcPr.findall(qn('w:tcBorders'))
    for el in existing:
        tcPr.remove(el)

    tcBorders = OxmlElement('w:tcBorders')
    for border_name in ('top', 'left', 'bottom', 'right'):
        border = OxmlElement(f'w:{border_name}')
        border.set(qn('w:val'), 'single')
        border.set(qn('w:sz'), '4')
        border.set(qn('w:space'), '0')
        border.set(qn('w:color'), color)
        tcBorders.append(border)
    tcPr.append(tcBorders)


def _set_cell_margins(cell, top: int = 60, bottom: int = 60, left: int = 80, right: int = 80) -> None:
    """
    Добавляет внутренние отступы в ячейке (twips),
    чтобы короткие значения не выглядели «прижатыми».
    20 twips = 1 pt.
    """
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    existing = tcPr.findall(qn("w:tcMar"))
    for el in existing:
        tcPr.remove(el)

    tcMar = OxmlElement("w:tcMar")
    for side, value in (("top", top), ("bottom", bottom), ("left", left), ("right", right)):
        side_el = OxmlElement(f"w:{side}")
        side_el.set(qn("w:w"), str(value))
        side_el.set(qn("w:type"), "dxa")
        tcMar.append(side_el)
    tcPr.append(tcMar)


def _set_table_borders(table, color: str = "000000") -> None:
    tbl = table._tbl
    tblPr = tbl.tblPr
    existing = tblPr.findall(qn('w:tblBorders'))
    for el in existing:
        tblPr.remove(el)

    tblBorders = OxmlElement('w:tblBorders')
    for border_name in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'):
        border = OxmlElement(f'w:{border_name}')
        border.set(qn('w:val'), 'single')
        border.set(qn('w:sz'), '4')
        border.set(qn('w:space'), '0')
        border.set(qn('w:color'), color)
        tblBorders.append(border)
    tblPr.append(tblBorders)

def format_table(table):
    """Единое форматирование таблицы: центрирование и чёрные границы."""
    for row in table.rows:
        _set_row_cant_split(row)
        _set_row_auto_height(row)
        for cell in row.cells:
            for paragraph in cell.paragraphs:
                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                paragraph.paragraph_format.space_before = 0
                paragraph.paragraph_format.space_after = 0
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            _set_cell_margins(cell)
            _set_cell_borders(cell, "000000")
    _set_table_borders(table, "000000")
