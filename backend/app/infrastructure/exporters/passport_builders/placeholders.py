from docx import Document
from docx.enum.text import WD_COLOR_INDEX
from typing import Optional


def get_full_paragraph_text(paragraph) -> str:
    """Получает полный текст параграфа из всех runs"""
    return ''.join(run.text for run in paragraph.runs)


def _apply_char_style_from_template(dest, template_run, *, force_bold: bool | None = None) -> None:
    """Копирует шрифт/начертание с образца; force_bold переопределяет жирность."""
    if template_run is None:
        dest.font.name = "Times New Roman"
        if force_bold is not None:
            dest.bold = force_bold
        return
    dest.font.name = template_run.font.name or "Times New Roman"
    dest.font.size = template_run.font.size
    if force_bold is not None:
        dest.bold = force_bold
    else:
        dest.bold = template_run.bold
    dest.italic = template_run.italic
    dest.underline = template_run.underline


def replace_in_paragraph_bold_token(paragraph, old: str, new: str) -> bool:
    """
    Заменяет первое вхождение old на new; вставленный фрагмент всегда жирный.
    Префикс и суффикс сохраняют начертание первого run шаблона.
    """
    full_text = get_full_paragraph_text(paragraph)
    if old not in full_text:
        return False
    idx = full_text.index(old)
    prefix = full_text[:idx]
    suffix = full_text[idx + len(old) :]
    template_run = paragraph.runs[0] if paragraph.runs else None
    for run in list(paragraph.runs):
        paragraph._p.remove(run._r)
    if prefix:
        r = paragraph.add_run(prefix)
        _apply_char_style_from_template(r, template_run, force_bold=None)
    r_mid = paragraph.add_run(new)
    _apply_char_style_from_template(r_mid, template_run, force_bold=True)
    if suffix:
        r = paragraph.add_run(suffix)
        _apply_char_style_from_template(r, template_run, force_bold=None)
    return True


def replace_placeholder_in_cell_bold(cell, old: str, new: str) -> bool:
    """Ищет плейсхолдер в ячейке и заменяет с жирным начертанием у подставленного текста."""
    for paragraph in cell.paragraphs:
        if old in get_full_paragraph_text(paragraph):
            return replace_in_paragraph_bold_token(paragraph, old, new)
    return False


def replace_in_paragraph(paragraph, old: str, new: str):
    """
    Заменяет текст, сохраняя форматирование run'а
    Возвращает список замен в формате [(old, new), ...]
    """
    replacements = []

    # Сначала пробуем простую замену в каждом текстовом фрагменте.
    for run in paragraph.runs:
        if old in run.text:
            replacements.append((old, new))
            run.text = run.text.replace(old, new)
            run.font.highlight_color = WD_COLOR_INDEX.WHITE

    # Если не нашли замены, проверяем весь текст параграфа
    if not replacements:
        full_text = get_full_paragraph_text(paragraph)
        if old in full_text:
            # Если текст найден в полном абзаце, но не в отдельных фрагментах,
            # значит ключ разбит на несколько фрагментов.
            # Сохраняем форматирование первого фрагмента, чтобы не терять стиль шаблона.
            template_run = paragraph.runs[0] if paragraph.runs else None

            # Создаём новый фрагмент с заменённым текстом.
            new_text = full_text.replace(old, new)
            
            # Удаляем старые текстовые фрагменты.
            for run in paragraph.runs:
                paragraph._p.remove(run._r)
            
            # Добавляем новый текстовый фрагмент.
            new_run = paragraph.add_run(new_text)
            new_run.font.highlight_color = WD_COLOR_INDEX.WHITE
            if template_run is not None:
                new_run.bold = template_run.bold
                new_run.italic = template_run.italic
                new_run.underline = template_run.underline
                new_run.font.size = template_run.font.size
                new_run.font.name = template_run.font.name or 'Times New Roman'
            else:
                new_run.font.name = 'Times New Roman'
            
            replacements.append((old, new))


def replace_in_doc(doc: Document, mapping: dict[str, str]):
    """
    Заменяет ключи из mapping в параграфах, ячейках таблиц и колонтитулах
    Возвращает словарь с информацией о заменах
    """
    
    def process_element(element, element_type: str, section_idx: Optional[int] = None):
        """Обрабатывает элемент (параграфы и таблицы)"""
        # Обработка параграфов
        if hasattr(element, 'paragraphs'):
            for paragraph in element.paragraphs:
                full_text = get_full_paragraph_text(paragraph)
                for key, value in mapping.items():
                    if key in full_text:
                        replace_in_paragraph(paragraph, key, value)
        
        # Обработка таблиц
        if hasattr(element, 'tables'):
            for table in element.tables:
                for row in table.rows:
                    for cell in row.cells:
                        process_element(cell, element_type, section_idx)
    
    # 1. Замена в основном теле документа
    process_element(doc, 'paragraphs')
    
    # 2. Замена в колонтитулах
    for section_idx, section in enumerate(doc.sections):
        # Верхний колонтитул
        if section.header is not None:
            process_element(section.header, 'headers', section_idx)
        
        # Нижний колонтитул
        if section.footer is not None:
            process_element(section.footer, 'footers', section_idx)
        
        # Верхний колонтитул первой страницы
        if hasattr(section, 'first_page_header') and section.first_page_header is not None:
            process_element(section.first_page_header, 'first_page_headers', section_idx)
        
        # Нижний колонтитул первой страницы
        if hasattr(section, 'first_page_footer') and section.first_page_footer is not None:
            process_element(section.first_page_footer, 'first_page_footers', section_idx)
    
