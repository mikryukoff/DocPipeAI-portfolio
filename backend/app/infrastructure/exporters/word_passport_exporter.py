import re
from functools import lru_cache
from datetime import datetime

from pathlib import Path
from docx import Document
from pymorphy3 import MorphAnalyzer
from loguru import logger

from backend.app.domain.models.pipeline import Pipeline
from backend.app.shared.pipeline_number_format import format_with_number_sign
from .passport_builders.spec_tables_builder import SpecTablesBuilder
from .passport_builders.sections import fill_sections_table
from .passport_builders.placeholders import replace_in_doc
from .passport_builders.headers_footers import replace_in_headers_footers_comprehensive

class WordPassportExporter:
    def __init__(self, template_path: str | Path):
        self.template_path = Path(template_path)
        if not self.template_path.exists():
            raise FileNotFoundError(self.template_path)

        self.morph = MorphAnalyzer()

    def export(self, pipeline: Pipeline, output_path: str | Path) -> None:
        doc = Document(self.template_path)

        medium_genitive = self.decline_to_genitive(pipeline.medium)
        start_direction_genitive = self.clean_direction_string(self.decline_to_genitive(pipeline.flow_direction.start))
        end_direction_genitive = self.clean_direction_string(self.decline_to_genitive(pipeline.flow_direction.end))

        if pipeline.flow_direction.end:
            pipeline_purpose_str = f"Прокладка трубопроводов с {medium_genitive.lower()} от {start_direction_genitive} до {end_direction_genitive}"
        else:
            pipeline_purpose_str = f"Прокладка трубопроводов {pipeline.flow_direction.start}"

        # 1. Текстовые плейсхолдеры.
        mapping = {
            "РАБОЧАЯ СРЕДА (ТИТУЛЬНИК)": medium_genitive.upper(),
            "РАБОЧАЯ СРЕДА (КОЛОНТИТУЛ)": medium_genitive.upper(),
            "РАБОЧАЯ СРЕДА (ПЕРВАЯ ТАБЛИЦА)": pipeline.medium,
            "РАБОЧАЯ СРЕДА (ЗАКЛЮЧЕНИЕ)": medium_genitive.lower(),
            "ЗАВОДСКОЙ НОМЕР": format_with_number_sign(pipeline.name),
            "НАИМЕНОВАНИЕ ТРУБОПРОВОДА": f"Трубопровод для транспортирования {medium_genitive.lower()}",
            "НАЗНАЧЕНИЕ ТРУБОПРОВОДА": pipeline_purpose_str,
            "РАБОЧЕЕ ДАВЛЕНИЕ": pipeline.parameters.working_pressure,
            "РАСЧЕТНОЕ ДАВЛЕНИЕ": pipeline.parameters.calculated_pressure,
            "РАСЧЕТНАЯ ТЕМПЕРАТУРА": pipeline.parameters.calculated_temperature,
            "РАБОЧАЯ ТЕМПЕРАТУРА": pipeline.parameters.working_temperature,
            "ГОСТ КАТЕГОРИЯ": pipeline.parameters.gost_category,
            "СРОК СЛУЖБЫ": "не менее 20 лет",
            "текущий год г.": f"{pipeline.year} г.",
            "ПРОЕКТ": pipeline.mounting_scheme,
            "ДАТА МОНТАЖА": pipeline.parameters.installation_date,
            "РОД СВАРКИ": pipeline.parameters.welding_type,
            "МАТЕРИАЛ СВАРКИ": pipeline.parameters.welding_material,
        }
        mapping.update(self._build_strength_test_mapping(pipeline))

        replace_in_doc(doc, mapping)
        
        replace_in_headers_footers_comprehensive(doc, mapping, verbose=True)
        
        fill_sections_table(doc, pipeline)

        builder = SpecTablesBuilder()
        builder.build(doc, pipeline, medium_genitive=medium_genitive)

        # сохраняем документ
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        doc.save(output_path)

    def _build_strength_test_mapping(self, pipeline: Pipeline) -> dict[str, str]:
        """
        Подготовка плейсхолдеров испытаний.
        - гидравлическим -> гидроплейсхолдеры;
        - пневматическим -> пневмоплейсхолдеры;
        - оба -> оба набора.
        """
        pressure = self._format_strength_test_pressure(pipeline.parameters.strength_test_pressure)
        method = pipeline.parameters.strength_test_method
        duration = pipeline.parameters.strength_test_duration
        test_type = (getattr(pipeline.parameters, "strength_test_type", "") or "").lower()
        strength_test_result = pipeline.parameters.strength_test_result

        has_hydro = "гидравл" in test_type
        has_pneumo = "пневмат" in test_type
        if not has_hydro and not has_pneumo:
            # Backward-compatible: если тип не передан, не теряем текущую гидро-логику.
            has_hydro = True
            logger.warning(
                "Word export: strength_test_type is empty/unknown for pipeline={}, fallback=hydraulic",
                pipeline.name,
            )

        mapping: dict[str, str] = {
            "ДАВЛЕНИЕ ГИДРАВЛИЧЕСКОГО ИСПЫТАНИЯ": "---",
            "СРЕДА ГИДРАВЛИЧЕСКОГО ИСПЫТАНИЯ": "---",
            "ПРОДОЛЖИТЕЛЬНОСТЬ ГИДРАВЛИЧЕСКОЙ ВЫДЕРЖКИ": "---",
            "ДАВЛЕНИЕ ПНЕВМАТИЧЕСКОГО ИСПЫТАНИЯ": "---",
            "СРЕДА ПНЕВМАТИЧЕСКОГО ИСПЫТАНИЯ": "---",
            "ПРОДОЛЖИТЕЛЬНОСТЬ ПНЕВМАТИЧЕСКОЙ ВЫДЕРЖКИ": "---",
            "РЕЗУЛЬТАТ ГИДРАВЛИЧЕСКОГО ИСПЫТАНИЯ": "---",
            "РЕЗУЛЬТАТ ПНЕВМАТИЧЕСКОГО ИСПЫТАНИЯ": "---",
        }
        if has_hydro:
            mapping.update(
                {
                    "ДАВЛЕНИЕ ГИДРАВЛИЧЕСКОГО ИСПЫТАНИЯ": pressure or "---",
                    "СРЕДА ГИДРАВЛИЧЕСКОГО ИСПЫТАНИЯ": method or "---",
                    "ПРОДОЛЖИТЕЛЬНОСТЬ ГИДРАВЛИЧЕСКОЙ ВЫДЕРЖКИ": duration or "---",
                    "РЕЗУЛЬТАТ ГИДРАВЛИЧЕСКОГО ИСПЫТАНИЯ": strength_test_result or "Выдержал",
                }
            )
        if has_pneumo:
            mapping.update(
                {
                    "ДАВЛЕНИЕ ПНЕВМАТИЧЕСКОГО ИСПЫТАНИЯ": pressure or "---",
                    "СРЕДА ПНЕВМАТИЧЕСКОГО ИСПЫТАНИЯ": method or "---",
                    "ПРОДОЛЖИТЕЛЬНОСТЬ ПНЕВМАТИЧЕСКОЙ ВЫДЕРЖКИ": duration or "---",
                    "РЕЗУЛЬТАТ ПНЕВМАТИЧЕСКОГО ИСПЫТАНИЯ": strength_test_result or "Выдержал",
                }
            )
        return mapping

    @staticmethod
    def _format_strength_test_pressure(raw_pressure: str) -> str:
        """
        Нормализует давление к виду: `X,YY МПа (Y,YY кгс/см²)`.
        Поддерживает входы:
        - `1.17 МПа (11.70 кгс/см²)`
        - `1,17 МПа`
        - `1.17`
        """
        text = (raw_pressure or "").strip()
        if not text:
            return ""

        nums = re.findall(r"\d+(?:[.,]\d+)?", text)
        if not nums:
            return text

        try:
            mpa = float(nums[0].replace(",", "."))
        except ValueError:
            return text

        # Если второе значение отсутствует, используем принятый в проектных шаблонах коэффициент 10.
        kgf = None
        if len(nums) > 1:
            try:
                kgf = float(nums[1].replace(",", "."))
            except ValueError:
                kgf = None
        if kgf is None:
            kgf = mpa * 10.0

        mpa_text = f"{mpa:.2f}".replace(".", ",")
        kgf_text = f"{kgf:.2f}".replace(".", ",")
        return f"{mpa_text} МПа ({kgf_text} кгс/см²)"

    def clean_direction_string(self, text: str) -> str:
        """Простая очистка строки направления"""
        if not text:
            return ""
        
        # Разбиваем на слова
        words = text.split()
        cleaned_words = []
        
        # Список предлогов для исключения
        prepositions = {'от', 'до', 'в', 'на', 'из', 'с', 'по', 'под', 'за', 'над'}
        
        # Пропускаем предлоги в начале
        start_index = 0
        for i, word in enumerate(words):
            if word.lower() in prepositions:
                start_index = i + 1
            else:
                break
        
        # Обрабатываем оставшиеся слова
        for word in words[start_index:]:
            # Проверяем, содержит ли слово русские буквы
            has_russian = False
            has_english_or_digits = False
            
            for char in word:
                if 'а' <= char <= 'я' or 'А' <= char <= 'Я' or char in 'ёЁ':
                    has_russian = True
                elif 'a' <= char <= 'z' or 'A' <= char <= 'Z' or char.isdigit() or char in '-_/()№.':
                    has_english_or_digits = True
            
            # Если есть русские буквы и нет английских, приводим к нижнему регистру
            if has_russian and not has_english_or_digits:
                cleaned_words.append(word.lower())
            else:
                # Оставляем как есть (коды, английские слова и т.д.)
                cleaned_words.append(word)
        
        # Фильтруем слова длиной более 1 символа
        final_words = [w for w in cleaned_words if len(w.strip()) > 1]
        
        return " ".join(final_words)
     
    def decline_to_genitive(self, phrase: str) -> str:
        """
        Склоняет словосочетание в родительный падеж.
        - Сохраняет пунктуацию и пробелы.
        - Обрабатывает дефисные составные слова (a-b -> a-б).
        - Использует кеш для ускорения многократных вызовов.
        """
        if not phrase:
            return ""

        # Разбиваем на токены: слова, знаки препинания и пробелы.
        tokens = re.findall(r'\w+|[^\w\s]+|\s+', phrase, re.UNICODE)

        @lru_cache(maxsize=10000)
        def _decline_word(word: str) -> str:
            """Пытается склонить одно слово, иначе возвращает исходное."""
            # Сохраняем информацию о регистре.
            is_title = word.istitle()
            is_upper = word.isupper()

            # Обработка дефисных слов: склоняем каждую часть отдельно.
            if "-" in word:
                parts = word.split("-")
                declined_parts = []
                for p in parts:
                    declined_parts.append(_decline_word(p) if p else p)
                res = "-".join(declined_parts)
                return res.upper() if is_upper else (res.capitalize() if is_title else res)

            # Основной цикл по вариантам разбора.
            parses = self.morph.parse(word)
            if not parses:
                return word

            # Предпочитаемые части речи для склонения.
            GOOD_POS = {"NOUN", "ADJF", "PRTF", "NPRO"}

            # Сначала ищем подходящий вариант среди предпочитаемых частей речи,
            # затем среди всех вариантов.
            for prefer in (True, False):
                for parse in parses:
                    pos = getattr(parse.tag, "POS", None)
                    if prefer and pos not in GOOD_POS:
                        continue
                    form = parse.inflect({"gent"})  # родительный падеж
                    if form:
                        candidate = form.word
                        # Восстанавливаем исходный регистр.
                        if is_upper:
                            return candidate.upper()
                        if is_title:
                            return candidate.capitalize()
                        return candidate
            # Если склонение не удалось, возвращаем исходное слово.
            return word

        result_tokens = []
        for t in tokens:
            # Пробелы и чистую пунктуацию оставляем как есть.
            if t.isspace() or re.match(r'^[^\w-]+$', t, re.UNICODE):
                result_tokens.append(t)
                continue

            # Обычное слово склоняем (с кешированием).
            declined = _decline_word(t)
            result_tokens.append(declined)

        return "".join(result_tokens)
