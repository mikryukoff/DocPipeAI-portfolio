import json
from types import SimpleNamespace
from docx.table import Table
from docx.shared import Pt
from loguru import logger
from .xml_helpers import (
    copy_table_after,
    _create_section_title_element,
    apply_keep_with_next_before_table,
)
from .control_volume_lookup import ControlVolumeLookup
from .table_formatting import format_table
from backend.app.shared.pipeline_number_format import format_with_number_sign

class SpecTablesBuilder:
    """
    Класс, который формирует таблицы разделов 4.1–4.7 в документе.
    """

    def __init__(self):
        self.format_table = format_table
        self.control_volume = ControlVolumeLookup()

    # ---------- публичный интерфейс ----------
    def build(self, doc, pipeline, *, medium_genitive: str | None = None) -> None:
        """Главная точка: создаёт/копирует/заполняет таблицы 4.1–4.7 в doc по pipeline.

        medium_genitive — рабочая среда в родительном падеже (как в титуле); для 4.5 (ВИК).
        """
        # Собираем спецификации по странице
        specs = getattr(pipeline, "specifications", []) or []
        
        # Группируем спецификации по страницам
        specs_by_page = {}
        for spec in specs:
            page = getattr(spec, "page", "") or ""
            if page:
                if page not in specs_by_page:
                    specs_by_page[page] = []
                specs_by_page[page].append(spec)
        
        # Сортируем страницы по номеру
        sorted_pages = self._sort_pages(list(specs_by_page.keys()))
        
        # Находим индексы шаблонных таблиц
        template_tables = {}
        
        for i, table in enumerate(doc.tables):
            for row in table.rows:
                for cell in row.cells:
                    text = cell.text.strip()
                    for section_num in [1, 2, 3, 4, 5, 6, 7]:
                        placeholder = f"[4_{section_num}]"
                        if placeholder in text:
                            template_tables[section_num] = table
                            # Заменяем плейсхолдер без cell.text=… (оно сбрасывает run-форматирование).
                            self._replace_placeholder_in_cell_with_bold(cell, placeholder, "№ п/п")
                            break
        
        # Обрабатываем разделы 4.1, 4.2, 4.3 и 4.4 (закладные — по страницам, как 4.2)
        for section_num in [1, 2, 3, 4]:
            if section_num in template_tables:
                self._process_section_for_all_pages(
                    doc=doc,
                    template_table=template_tables[section_num],
                    sorted_pages=sorted_pages,
                    specs_by_page=specs_by_page,
                    section_number=section_num,
                    pipeline_name=getattr(pipeline, "name", "") or "",
                )

        # Раздел 4.5: ВИК/УЗК/ПВК в одной таблице. Раздел 4.6: стилоскопирование.
        if 5 in template_tables:
            self._process_section_45(doc, template_tables[5], pipeline, medium_genitive=medium_genitive)
        if 6 in template_tables:
            self._process_section_46(doc, template_tables[6], pipeline, medium_genitive=medium_genitive)
    
    def _process_section_for_all_pages(
        self,
        doc,
        template_table,
        sorted_pages,
        specs_by_page,
        section_number,
        pipeline_name: str = "",
    ):
        """Обрабатывает один раздел для всех участков (4.1, 4.2 или 4.3)"""
        # Сохраняем ссылку на шаблонную таблицу
        original_template = template_table

        # Определяем количество строк заголовка для разных таблиц
        header_rows = {
            1: 1,  # 4.1 - одна строка заголовка
            2: 1,  # 4.2 - одна строка заголовка
            3: 2,  # 4.3 - две строки заголовка (основной и подзаголовки)
            4: 1,  # 4.4 закладные — как 4.2
        }
        
        rows_to_keep = header_rows.get(section_number, 1)
        
        # Очищаем шаблонную таблицу (удаляем все строки кроме заголовка)
        while len(original_template.rows) > rows_to_keep:
            original_template._tbl.remove(original_template.rows[rows_to_keep]._tr)
        
        # Для первого участка используем шаблонную таблицу
        first_page = sorted_pages[0] if sorted_pages else ""

        # Привязываем заголовки раздела/участка к таблице, чтобы не отрывались при переносе.
        apply_keep_with_next_before_table(original_template, max_paragraphs=20)

        # Добавляем заголовок для первого участка
        self._add_section_title_before_table(original_template, first_page)
        
        # Заполняем первую таблицу
        if sorted_pages:
            specs_for_page = specs_by_page.get(first_page, [])
            merged_spec = self._merge_specs_for_page(specs_for_page)
            
            filled = False
            if section_number == 1:
                filled = self._fill_table_4_1(original_template, merged_spec)
            elif section_number == 2:
                filled = self._fill_table_4_2(original_template, merged_spec)
            elif section_number == 3:
                filled = self._fill_table_4_3(original_template, merged_spec)
            elif section_number == 4:
                filled = self._fill_table_4_4_embedments(
                    original_template,
                    merged_spec,
                    pipeline_name=pipeline_name,
                )
            
            if not filled:
                self._fill_with_placeholders(original_template, header_rows=rows_to_keep)
            
            if self.format_table:
                try:
                    self.format_table(original_template)
                except Exception as e:
                    logger.warning("Table formatting error. section={} page={} error={}", section_number, first_page, e)
        
        current_table = original_template
        
        # Обрабатываем остальные участки
        for idx, page in enumerate(sorted_pages[1:], 1):
            # Копируем таблицу
            new_table = copy_table_after(current_table, page, header_rows=rows_to_keep)
            
            # Добавляем заголовок участка перед новой таблицей
            self._add_section_title_before_table(new_table, page)
            apply_keep_with_next_before_table(new_table, max_paragraphs=20)
            
            # Заполняем новую таблицу
            specs_for_page = specs_by_page.get(page, [])
            merged_spec = self._merge_specs_for_page(specs_for_page)
            
            filled = False
            if section_number == 1:
                filled = self._fill_table_4_1(new_table, merged_spec)
            elif section_number == 2:
                filled = self._fill_table_4_2(new_table, merged_spec)
            elif section_number == 3:
                filled = self._fill_table_4_3(new_table, merged_spec)
            elif section_number == 4:
                filled = self._fill_table_4_4_embedments(
                    new_table,
                    merged_spec,
                    pipeline_name=pipeline_name,
                )
            
            if not filled:
                self._fill_with_placeholders(new_table, header_rows=rows_to_keep)
            
            # Форматируем таблицу
            if self.format_table:
                try:
                    self.format_table(new_table)
                except Exception as e:
                    logger.warning("Table formatting error. section={} page={} error={}", section_number, page, e)
            
            current_table = new_table
    
    def _process_section_45(self, doc, template_table, pipeline, *, medium_genitive: str | None = None):
        """Обрабатывает раздел 4.5: ВИК/УЗК/ПВК в одной таблице."""
        apply_keep_with_next_before_table(template_table, max_paragraphs=20)
        medium = (getattr(pipeline, "medium", None) or "").strip()
        gost_category = getattr(getattr(pipeline, "parameters", None), "gost_category", "")
        if not self._fill_table_4_5_combined(
            template_table,
            getattr(pipeline, "vik_entries", []),
            medium,
            gost_category,
            medium_genitive=medium_genitive,
        ):
            self._fill_with_placeholders(template_table, header_rows=1)

        if self.format_table:
            try:
                self.format_table(template_table)
            except Exception as e:
                logger.warning("Table formatting error in section 4.5. error={}", e)

    def _process_section_46(self, doc, template_table, pipeline, *, medium_genitive: str | None = None):
        """Обрабатывает раздел 4.6: стилоскопирование."""
        apply_keep_with_next_before_table(template_table, max_paragraphs=20)
        medium = (getattr(pipeline, "medium", None) or "").strip()
        gost_category = getattr(getattr(pipeline, "parameters", None), "gost_category", "")
        if not self._fill_table_4_6_styloscopy(
            template_table,
            getattr(pipeline, "vik_entries", []),
            medium,
            gost_category,
            medium_genitive=medium_genitive,
        ):
            self._fill_with_placeholders(template_table, header_rows=1)

        if self.format_table:
            try:
                self.format_table(template_table)
            except Exception as e:
                logger.warning("Table formatting error in section 4.6. error={}", e)

    @staticmethod
    def _filter_vik_rows_by_type(vik_rows, expected_type: str):
        out = []
        for row in list(vik_rows or []):
            row_type = (getattr(row, "type", "ВИК") or "ВИК").strip().upper()
            if row_type == expected_type.upper():
                out.append(row)
        return out

    def _latest_vik_row_by_type(self, vik_rows, expected_type: str):
        rows = self._filter_vik_rows_by_type(vik_rows, expected_type)
        return rows[-1] if rows else None
    
    def _sort_pages(self, pages):
        """Сортирует страницы как целые номера: 1, 2, 3, ..."""
        def page_key(page):
            text = (str(page) if page is not None else "").strip()
            if text.isdigit():
                return (0, int(text))
            # 1 - нечисловые страницы в конец, в лексикографическом порядке.
            return (1, text.lower())
        
        return sorted(pages, key=page_key)
    
    @staticmethod
    def _merge_specs_for_page(specs_list: list):
        """Собирает несколько Specification для одной страницы в единый merged-объект."""
        if not specs_list:
            return SimpleNamespace(
                page="",
                pipes=[],
                connection_parts=[],
                pipeline_armature=[],
                instrument_embedments=[],
                flanges=[],
                supports=[]
            )
        
        merged = SimpleNamespace(
            page=specs_list[0].page if specs_list else "",
            pipes=[],
            connection_parts=[],
            pipeline_armature=[],
            instrument_embedments=[],
            flanges=[],
            supports=[]
        )
        
        for s in specs_list:
            merged.pipes.extend(getattr(s, "pipes", []) or [])
            merged.connection_parts.extend(getattr(s, "connection_parts", []) or [])
            merged.pipeline_armature.extend(getattr(s, "pipeline_armature", []) or [])
            merged.instrument_embedments.extend(getattr(s, "instrument_embedments", []) or [])
            merged.flanges.extend(getattr(s, "flanges", []) or [])
            merged.supports.extend(getattr(s, "supports", []) or [])
        
        return merged
    
    def _fill_with_placeholders(self, table: Table, header_rows: int = 1):
        """Заполняет таблицу символами '---' если нет данных с правильным шрифтом"""
        self._clear_data_rows(table, header_rows=header_rows)
        
        # Добавляем одну строку с прочерками
        table.add_row()
        row = table.rows[header_rows]
        
        for cell in row.cells:
            # Очищаем ячейку
            cell.text = ""
            
            # Добавляем текст с нужным форматированием
            paragraph = cell.paragraphs[0]
            run = paragraph.add_run('---')
            run.font.name = 'Times New Roman'
            run.font.size = Pt(11)
        
        if self.format_table:
            try:
                self.format_table(table)
            except Exception:
                pass

    @staticmethod
    def _display_value(value) -> str:
        """Нормализует значения для отображения в таблице."""
        if value is None:
            return "---"
        if isinstance(value, str):
            stripped = value.strip()
            return stripped if stripped else "---"
        return str(value)

    @staticmethod
    def _paragraph_runs_full_text(paragraph) -> str:
        return "".join(run.text for run in paragraph.runs)

    @staticmethod
    def _copy_run_format_from_template(template_run, dst_run) -> None:
        """Копирует начертание с образцового run (кроме случая, когда template_run отсутствует)."""
        if template_run is None:
            return
        dst_run.bold = template_run.bold
        dst_run.italic = template_run.italic
        dst_run.underline = template_run.underline
        try:
            if template_run.font.name:
                dst_run.font.name = template_run.font.name
            if template_run.font.size:
                dst_run.font.size = template_run.font.size
        except Exception:
            pass

    @staticmethod
    def _apply_template_font_size_name_only(template_run, dst_run) -> None:
        if template_run is None:
            return
        try:
            if template_run.font.name:
                dst_run.font.name = template_run.font.name
            if template_run.font.size:
                dst_run.font.size = template_run.font.size
        except Exception:
            pass

    @staticmethod
    def _replace_placeholder_in_paragraph_with_bold(paragraph, placeholder: str, replacement: str) -> bool:
        full = SpecTablesBuilder._paragraph_runs_full_text(paragraph)
        if placeholder not in full:
            return False
        template_run = paragraph.runs[0] if paragraph.runs else None
        parts = full.split(placeholder)
        for run in list(paragraph.runs):
            paragraph._p.remove(run._r)
        for i, part in enumerate(parts):
            if part:
                run = paragraph.add_run(part)
                SpecTablesBuilder._copy_run_format_from_template(template_run, run)
            if i < len(parts) - 1:
                run = paragraph.add_run(replacement)
                SpecTablesBuilder._apply_template_font_size_name_only(template_run, run)
                run.bold = True
        return True

    @classmethod
    def _replace_placeholder_in_cell_with_bold(cls, cell, placeholder: str, replacement: str) -> bool:
        """Заменяет текст плейсхолдера в ячейке; вставленный replacement всегда жирный."""
        changed = False
        for paragraph in cell.paragraphs:
            if cls._replace_placeholder_in_paragraph_with_bold(paragraph, placeholder, replacement):
                changed = True
        return changed

    @staticmethod
    def _clear_data_rows(table: Table, header_rows: int = 1):
        """Удаляет только строки данных, сохраняя заданное число строк заголовка."""
        while len(table.rows) > header_rows:
            table._tbl.remove(table.rows[header_rows]._tr)
    
    @staticmethod
    def _add_section_title_before_table(table: Table, page_number: str):
        """Добавляет заголовок 'Участок X (Схема сварных соединений №X)' перед таблицей"""
        # Проверяем, нет ли уже заголовка перед этой таблицей
        if not SpecTablesBuilder._has_section_title_before_table(table):
            # Находим элемент таблицы
            tbl = table._tbl
            parent = tbl.getparent()
            
            # Добавляем заголовок участка
            title_el = _create_section_title_element(f"Участок {page_number} (Схема сварных соединений №{page_number})")
            
            # Вставляем перед таблицей
            parent.insert(parent.index(tbl), title_el)

    @staticmethod
    def _has_section_title_before_table(tbl: Table) -> bool:
        """Проверяет, есть ли заголовок участка перед таблицей"""
        prev = tbl._tbl.getprevious()
        if prev is None:
            return False
        for node in prev.iter():
            if (
                node.tag.endswith('}t')
                and node.text
                and "Участок" in node.text
                and "Схема сварных соединений" in node.text
            ):
                return True
        return False
    
    # Методы заполнения таблиц (по логике близки к функциям из `spec_tables`).
    def _fill_table_4_1(self, table, spec):
        """Заполняет таблицу 4.1 (Трубы, отводы, элементы)"""
        if not hasattr(spec, 'pipes') and not hasattr(spec, 'connection_parts'):
            return False
        
        all_elements = []
        
        # Трубы
        if hasattr(spec, 'pipes'):
            for pipe in spec.pipes:
                all_elements.append({
                    "name": getattr(pipe, 'name', '---'),
                    "quantity": f"{str(float(getattr(pipe, 'quantity', 0)))}",
                    "dimensions": getattr(pipe, 'dimensions', '---'),
                    "steel_grade": getattr(pipe, 'steel_grade', '---'),
                    "gost": getattr(pipe, 'gost', '---')
                })
        
        # Соединительные детали
        if hasattr(spec, 'connection_parts'):
            for conn in spec.connection_parts:
                all_elements.append({
                    "name": getattr(conn, 'name', '---'),
                    "quantity": f"{str(int(getattr(conn, 'quantity', 0)))}",
                    "dimensions": getattr(conn, 'dimensions', '---'),
                    "steel_grade": getattr(conn, 'steel_grade', '---'),
                    "gost": getattr(conn, 'gost', '---')
                })
        
        if not all_elements:
            return False
        
        self._clear_data_rows(table, header_rows=1)
        
        # Заполняем таблицу
        for i, element in enumerate(all_elements, 1):
            if i + 1 > len(table.rows) - 1:
                table.add_row()
            
            row = table.rows[i]
            if len(row.cells) >= 6:
                # Заполняем каждую ячейку с правильным форматированием
                cells_data = [
                    str(i),  # № п/п
                    element["name"],  # Наименование
                    element["quantity"],  # Количество
                    element["dimensions"],  # Размеры
                    element["steel_grade"],  # Марка стали
                    element["gost"]  # ГОСТ или ТУ
                ]
                
                for j, text in enumerate(cells_data):
                    # Очищаем ячейку
                    cell = row.cells[j]
                    cell.text = ""
                    
                    # Добавляем текст с нужным форматированием
                    paragraph = cell.paragraphs[0]
                    run = paragraph.add_run(self._display_value(text))
                    run.font.name = 'Times New Roman'
                    run.font.size = Pt(11)
        
        return True

    def _fill_armature_like_table(self, table, items) -> bool:
        """Общее заполнение таблицы в формате 4.2 (7 колонок)."""
        if not items:
            return False

        self._clear_data_rows(table, header_rows=1)

        for i, item in enumerate(items, 1):
            if i > len(table.rows) - 1:
                table.add_row()

            row = table.rows[i]
            if len(row.cells) >= 7:
                cells_data = [
                    str(i),
                    getattr(item, "name", "---"),
                    getattr(item, "location", "---"),
                    getattr(item, "dn", "---"),
                    getattr(item, "pn", "---"),
                    getattr(item, "material_grade", "---"),
                    getattr(item, "gost", "---"),
                ]

                for j, text in enumerate(cells_data):
                    cell = row.cells[j]
                    cell.text = ""
                    paragraph = cell.paragraphs[0]
                    run = paragraph.add_run(self._display_value(text))
                    run.font.name = "Times New Roman"
                    run.font.size = Pt(11)

        return True

    def _fill_table_4_2(self, table, spec):
        """Заполняет таблицу 4.2 (Арматура)"""
        if not hasattr(spec, "pipeline_armature"):
            return False
        return self._fill_armature_like_table(table, spec.pipeline_armature)

    def _fallback_embedment_location(self, pipeline_name: str) -> str:
        pipeline_name_disp = self._display_value(pipeline_name)
        if pipeline_name_disp == "---":
            return "---"
        return f"т-д {pipeline_name_disp}"

    def _flatten_instrument_embedments(self, items, *, pipeline_name: str):
        """Одна закладная в БД может содержать несколько строк таблицы (embedment_elements)."""
        if not items:
            return []
        out: list = []
        for item in items:
            subs = getattr(item, "embedment_elements", None)
            if isinstance(subs, list) and len(subs) > 0:
                pname = getattr(item, "name", "---")
                for el in subs:
                    if not isinstance(el, dict):
                        continue
                    row_nm = str(el.get("name") or "").strip()
                    disp_name = (
                        row_nm
                        if row_nm and row_nm != "---"
                        else pname
                    )
                    out.append(
                        SimpleNamespace(
                            name=disp_name,
                            location=self._fallback_embedment_location(pipeline_name),
                            dn=el.get("dn", "---") or "---",
                            pn=el.get("pn", "---") or "---",
                            material_grade=el.get("material_grade", "---") or "---",
                            gost=el.get("gost", "---") or "---",
                        )
                    )
            else:
                out.append(
                    SimpleNamespace(
                        name=getattr(item, "name", "---"),
                        location=self._fallback_embedment_location(pipeline_name),
                        dn=getattr(item, "dn", "---"),
                        pn=getattr(item, "pn", "---"),
                        material_grade=getattr(item, "material_grade", "---"),
                        gost=getattr(item, "gost", "---"),
                    )
                )
        return out

    def _fill_table_4_4_embedments(self, table, spec, *, pipeline_name: str = ""):
        """Заполняет таблицу 4.4 (Закладные для приборов), структура как 4.2."""
        if not hasattr(spec, "instrument_embedments"):
            return False
        flat = self._flatten_instrument_embedments(
            spec.instrument_embedments,
            pipeline_name=pipeline_name,
        )
        return self._fill_armature_like_table(table, flat)

    def _fill_table_4_5_combined(
        self,
        table,
        vik_rows,
        medium: str,
        gost_category: str,
        *,
        medium_genitive: str | None = None,
    ) -> bool:
        self._ensure_data_rows(table, needed_rows=3, header_rows=1)
        while len(table.rows) > 4:
            table._tbl.remove(table.rows[4]._tr)

        row_specs = [
            ("ВИК", self._latest_vik_row_by_type(vik_rows, "ВИК")),
            ("УЗК", self._latest_vik_row_by_type(vik_rows, "УЗК")),
            ("ПВК", self._latest_vik_row_by_type(vik_rows, "ПВК")),
        ]

        for index, (control_type, item) in enumerate(row_specs):
            row = table.rows[index + 1]
            if len(row.cells) < 7:
                continue

            preserved = [row.cells[col].text for col in range(7)]
            pipe_num = getattr(item, "pipe_num", None) if item else None
            first_cell_text = self._build_pipe_scheme_text(
                medium=medium,
                medium_genitive=medium_genitive,
                pipe_num=pipe_num,
            )
            if item:
                raw_statement = self._display_value(getattr(item, "statement_text", None))
                if control_type in {"УЗК", "ПВК"}:
                    statement_text = raw_statement
                else:
                    statement_text = f"№{raw_statement}"
            else:
                statement_text = "---"

            if item and control_type == "ВИК":
                percent = "100%"
            elif item:
                percent = self.control_volume.get_percent(gost_category, control_type)
            else:
                percent = "---"

            cells_data = [
                preserved[0],  # Не трогаем первую ячейку у всех НК-строк.
                first_cell_text if item else "---",
                statement_text,
                preserved[3],  # Не трогаем четвёртую ячейку у всех НК-строк.
                percent,
                "Не обнаружено" if item else "---",
                "Годен" if item else "---",
            ]

            for col_index, text in enumerate(cells_data):
                self._set_cell_text(row.cells[col_index], text)

        return True

    def _fill_table_4_6_styloscopy(
        self,
        table,
        vik_rows,
        medium: str,
        gost_category: str,
        *,
        medium_genitive: str | None = None,
    ) -> bool:
        self._ensure_data_rows(table, needed_rows=1, header_rows=1)
        while len(table.rows) > 2:
            table._tbl.remove(table.rows[2]._tr)

        row = table.rows[1]
        if len(row.cells) < 6:
            return False

        item = self._latest_vik_row_by_type(vik_rows, "СТИЛОСКОПИРОВАНИЕ")
        preserved = [row.cells[col].text for col in range(6)]
        first_cell_text = self._build_pipe_scheme_text(
            medium=medium,
            medium_genitive=medium_genitive,
            pipe_num=getattr(item, "pipe_num", None) if item else None,
        )
        protocol_after_no, steel_mark_data = self._decode_styloscopy_statement(
            getattr(item, "statement_text", None)
        )
        percent = self.control_volume.get_percent(gost_category, "СТИЛОСКОПИРОВАНИЕ") if item else "---"

        cells_data = [
            preserved[0],  # Не трогаем первую ячейку.
            first_cell_text if item else "---",
            f"№{protocol_after_no}" if item and protocol_after_no else "---",
            preserved[3],  # Не трогаем четвёртую ячейку.
            percent,
            steel_mark_data if item else "---",
        ]
        for col_index, text in enumerate(cells_data):
            self._set_cell_text(row.cells[col_index], text)
        return True

    @staticmethod
    def _decode_styloscopy_statement(raw_statement) -> tuple[str, str]:
        text = (raw_statement or "").strip()
        if not text:
            return "", "---"
        if text.startswith("{") and text.endswith("}"):
            try:
                payload = json.loads(text)
                if isinstance(payload, dict):
                    protocol = str(payload.get("protocol_after_no") or "").strip()
                    steel_marks = str(payload.get("steel_marks") or "").strip()
                    return protocol, steel_marks or "---"
            except Exception:
                pass
        return "", text

    def _ensure_data_rows(self, table: Table, *, needed_rows: int, header_rows: int = 1) -> None:
        if needed_rows <= 0:
            return
        if len(table.rows) <= header_rows:
            table.add_row()
        seed_values = [cell.text for cell in table.rows[header_rows].cells]
        while len(table.rows) < header_rows + needed_rows:
            table.add_row()
            new_row = table.rows[-1]
            for idx, text in enumerate(seed_values):
                if idx < len(new_row.cells):
                    self._set_cell_text(new_row.cells[idx], text)

    def _build_pipe_scheme_text(
        self,
        *,
        medium: str,
        medium_genitive: str | None,
        pipe_num,
    ) -> str:
        pipe_num_disp = self._display_value(pipe_num)
        pipe_num_label = format_with_number_sign(pipe_num_disp) if pipe_num_disp != "---" else "---"
        mg = (medium_genitive or "").strip()
        plain = (medium or "").strip()
        if mg:
            medium_in_sentence = mg.lower()
        elif plain:
            medium_in_sentence = plain.lower()
        else:
            medium_in_sentence = ""
        if medium_in_sentence:
            return f"Схема сварных стыков трубопровода {medium_in_sentence} {pipe_num_label}"
        return f"Схема сварных стыков трубопровода {pipe_num_label}"

    @staticmethod
    def _set_cell_text(cell, text) -> None:
        cell.text = ""
        paragraph = cell.paragraphs[0]
        run = paragraph.add_run(SpecTablesBuilder._display_value(text))
        run.font.name = "Times New Roman"
        run.font.size = Pt(11)

    def _fill_table_4_3(self, table, spec):
        """Заполняет таблицу 4.3 (Фланцы, крепежные детали и прокладки)"""
        all_elements = []
        
        # Фланцы
        if hasattr(spec, 'flanges'):
            for flange in spec.flanges:
                all_elements.append({
                    "name": getattr(flange, 'name', '---'),
                    "quantity": f"{str(int(getattr(flange, 'quantity', 0)))}",
                    "gost": getattr(flange, 'flange_gost', '---'),
                    "passage": getattr(flange, 'dn', '---'),
                    "pressure": getattr(flange, 'pn', '---'),
                    "flange_material": getattr(flange, 'steel_grade', '---'),
                    "flange_gost": getattr(flange, 'flange_gost', '---'),
                    "bolt_material": getattr(flange, 'bolt_grade', '---'),
                    "bolt_gost": getattr(flange, 'bolt_gost', '---')
                })
        
        # Опоры
        if hasattr(spec, 'supports'):
            for support in spec.supports:
                all_elements.append({
                    "name": getattr(support, 'name', '---'),
                    "quantity": f"{str(int(getattr(support, 'quantity', 0)))}",
                    "gost": getattr(support, 'gost', '---'),
                    "passage": "---",
                    "pressure": "---",
                    "flange_material": "---",
                    "flange_gost": "---",
                    "bolt_material": "---",
                    "bolt_gost": "---"
                })
        
        if not all_elements:
            return False
        
        # Для 4.3 сохраняем двухстрочный заголовок с подстолбцами.
        self._clear_data_rows(table, header_rows=2)
        
        # Заполняем таблицу
        for i, element in enumerate(all_elements, 1):
            if i + 1 > len(table.rows) - 1:
                table.add_row()
            
            row = table.rows[i + 1]
            if len(row.cells) >= 10:
                # Заполняем каждую ячейку с правильным форматированием
                cells_data = [
                    str(i),  # № п/п
                    element["name"],  # Наименование
                    element["quantity"],  # Количество
                    element["gost"],  # ГОСТ или ТУ
                    element["passage"],  # Условный проход
                    element["pressure"],  # Условное давление
                    element["flange_material"],  # Материал фланцев - марка стали
                    element["flange_gost"],  # Материал фланцев - ГОСТ/ТУ
                    element["bolt_material"],  # Материал шпилек - марка стали
                    element["bolt_gost"]  # Материал шпилек - ГОСТ/ТУ
                ]
                
                for j, text in enumerate(cells_data):
                    # Очищаем ячейку
                    cell = row.cells[j]
                    cell.text = ""
                    
                    # Добавляем текст с нужным форматированием
                    paragraph = cell.paragraphs[0]
                    run = paragraph.add_run(self._display_value(text))
                    run.font.name = 'Times New Roman'
                    run.font.size = Pt(11)
        
        return True
