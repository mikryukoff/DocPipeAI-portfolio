def replace_in_all_headers_footers_with_partial(doc, mapping, verbose=True):
    """
    Замена текста с поддержкой частичных совпадений
    (например, если текст разделен на несколько XML элементов)
    """
    replacements = []
    
    for section_idx, section in enumerate(doc.sections):
        # Собираем все типы колонтитулов
        header_footer_pairs = [
            (section.header, 'header'),
            (section.footer, 'footer'),
        ]
        
        if hasattr(section, 'first_page_header') and section.first_page_header is not None:
            header_footer_pairs.append((section.first_page_header, 'first_page_header'))
        
        if hasattr(section, 'first_page_footer') and section.first_page_footer is not None:
            header_footer_pairs.append((section.first_page_footer, 'first_page_footer'))
        
        if hasattr(section, 'even_page_header') and section.even_page_header is not None:
            header_footer_pairs.append((section.even_page_header, 'even_page_header'))
        
        if hasattr(section, 'even_page_footer') and section.even_page_footer is not None:
            header_footer_pairs.append((section.even_page_footer, 'even_page_footer'))
        
        # Обрабатываем каждый колонтитул
        for header_footer, hf_type in header_footer_pairs:
            if header_footer is None:
                continue
            
            element = header_footer._element
            
            # Сначала попробуем собрать весь текст из параграфа
            for para_elem in element.xpath(".//w:p"):
                # Собираем весь текст из всех `w:t`-элементов этого абзаца.
                full_para_text = ''.join([t.text or '' for t in para_elem.xpath(".//w:t")])
                
                if full_para_text.strip():
                    # Проверяем все ключи из словаря замен.
                    for key, value in mapping.items():
                        if key in full_para_text:
                            # Если ключ найден на уровне абзаца, заменяем его во всех
                            # текстовых узлах абзаца.
                            for text_elem in para_elem.xpath(".//w:t"):
                                if text_elem.text and key in text_elem.text:
                                    original_text = text_elem.text
                                    text_elem.text = text_elem.text.replace(key, value)
                                    
                                    replacements.append({
                                        'section': section_idx,
                                        'type': hf_type,
                                        'old': key,
                                        'new': value,
                                        'original_text': original_text,
                                        'approach': 'paragraph_level'
                                    })
                                    
            # Также проверяем отдельные текстовые элементы (для случаев, когда нет параграфов)
            for text_elem in element.xpath(".//w:t"):
                text = text_elem.text
                if text:
                    for key, value in mapping.items():
                        if key in text:
                            original_text = text
                            text_elem.text = text.replace(key, value)
                            
                            replacements.append({
                                'section': section_idx,
                                'type': hf_type,
                                'old': key,
                                'new': value,
                                'original_text': original_text,
                                'approach': 'text_level'
                            })
    
    return replacements


def replace_in_headers_footers_comprehensive(doc, mapping, verbose=True):
    """
    Комплексная замена текста во всех колонтитулах
    Использует несколько методов для максимального покрытия
    """
    # Выполняем замену
    replacements = replace_in_all_headers_footers_with_partial(doc, mapping, verbose)
    
    if replacements:
        # Группируем замены по типу колонтитула
        by_type = {}
        for r in replacements:
            key = f"{r['type']} секция {r['section']}"
            if key not in by_type:
                by_type[key] = []
            by_type[key].append(r)
        
        # Проверяем, какие ключи вообще есть в документе
        for key in mapping.keys():
            found = False
            for section in doc.sections:
                # Проверяем все возможные колонтитулы
                for hf in [section.header, section.footer]:
                    if hf and key in hf._element.xml:
                        found = True
                        break
                if found:
                    break
            
    return replacements
