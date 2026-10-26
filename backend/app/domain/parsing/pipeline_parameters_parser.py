import re
from backend.app.domain.models.pipeline import Pipeline
from decimal import Decimal, getcontext
from loguru import logger

from backend.app.shared.pipeline_row_logger import log_pipeline_row
from backend.app.shared.parsing_audit_logger import log_parsing_event


class PipelineParametersParser:
    """
    Domain-service.
    Отвечает ТОЛЬКО за извлечение параметров трубопровода из строк таблицы.
    """

    def __init__(
        self,
        job_id: int | None = None,
        source: str | None = None,
        user_log_key: str | None = None,
    ):
        self.job_id = job_id
        self.source = source
        self.user_log_key = user_log_key

    def parse(self, rows: list[list[str]], pipeline: Pipeline) -> None:
        for row_index, row in enumerate(rows, start=1):
            # Логируем все строки параметров, привязанные к трубопроводу.
            log_pipeline_row(
                job_id=self.job_id,
                user_log_key=self.user_log_key,
                source=self.source,
                pipeline=pipeline.name,
                page=None,
                row_type="parameters",
                row=row,
            )
            try:
                self._parse_row(row, pipeline, row_index=row_index)
            except Exception as exc:  # noqa: BLE001
                # Нефатальная ошибка при разборе параметров — логируем подробности.
                logger.warning(
                    "Parameter parsing error. error={} row={}",
                    str(exc),
                    row,
                )

    def _parse_row(self, line: list[str], pipeline: Pipeline, *, row_index: int) -> None:
        self._format_incorrect_line(line)

        self._extract_mounting_scheme_by_psi(line, pipeline, row_index=row_index)
        self._extract_simple(line, "Наименование среды", pipeline, "medium", pipeline.name, row_index)
        self._extract_simple(line, "Материал трубопровода", pipeline.parameters, "material", pipeline.name, row_index)

        self._extract_pressure_temp(line, "P раб.", pipeline.parameters, "working_pressure", pipeline.name, row_index)
        self._extract_pressure_temp(line, "T раб.", pipeline.parameters, "working_temperature", pipeline.name, row_index, temp=True)
        self._extract_pressure_temp(line, "T расч.", pipeline.parameters, "working_temperature", pipeline.name, row_index, temp=True)
        self._extract_pressure_temp(line, "P расч.", pipeline.parameters, "calculated_pressure", pipeline.name, row_index)
        self._extract_temp_calc(line, pipeline.parameters, pipeline.name, row_index)
        self._extract_pressure_temp(
            line,
            "P испытания на прочность/плотность",
            pipeline.parameters,
            "strength_test_pressure",
            pipeline.name,
            row_index,
        )
        self._extract_simple(
            line,
            "Способ испытаний на прочность/плотность",
            pipeline.parameters,
            "strength_test_method",
            pipeline.name,
            row_index,
        )

        self._extract_flow_direction(line, pipeline, row_index=row_index)
        self._extract_gost_category(line, pipeline, row_index=row_index)

    # ==========================================================
    # ИЗВЛЕЧЕНИЕ ПОЛЕЙ
    # ==========================================================

    def _extract_simple(self, line, key, target, attr, pipeline_name: str, row_index: int):
        if getattr(target, attr):
            return

        for i, item in enumerate(line):
            if key in item and i + 1 < len(line):
                value = line[i + 1]
                if key == "Материал трубопровода":
                    value = value.split()[0]
                setattr(target, attr, value)
                self._audit_field(
                    pipeline_name=pipeline_name,
                    field=attr,
                    value=value,
                    row_index=row_index,
                    line=line,
                    marker=key,
                )

    def _extract_pressure_temp(self, line, key, target, attr, pipeline_name: str, row_index: int, temp=False):
        if getattr(target, attr):
            return

        for i, item in enumerate(line):
            if key in item and i + 1 < len(line):
                value = line[i + 1]

                if not temp:
                    value = self._format_pressure(value, line, i)
                else:
                    value += " °С"

                setattr(target, attr, value)
                self._audit_field(
                    pipeline_name=pipeline_name,
                    field=attr,
                    value=value,
                    row_index=row_index,
                    line=line,
                    marker=key,
                )

    def _extract_temp_calc(self, line, target, pipeline_name: str, row_index: int):
        if target.calculated_temperature:
            return

        for i, item in enumerate(line):
            if "T расч." in item and i + 1 < len(line):
                target.calculated_temperature = self._process_temp_calc(line[i + 1])
                self._audit_field(
                    pipeline_name=pipeline_name,
                    field="calculated_temperature",
                    value=target.calculated_temperature,
                    row_index=row_index,
                    line=line,
                    marker="T расч.",
                )

    def _extract_flow_direction(self, line, pipeline: Pipeline, *, row_index: int):
        for i, item in enumerate(line):
            if item == "Начало" and not pipeline.flow_direction.start:
                pipeline.flow_direction.start = line[i + 1]
                self._audit_field(
                    pipeline_name=pipeline.name,
                    field="flow_direction.start",
                    value=pipeline.flow_direction.start,
                    row_index=row_index,
                    line=line,
                    marker="Начало",
                )
            if item == "Конец" and not pipeline.flow_direction.end:
                pipeline.flow_direction.end = line[i + 1]
                self._audit_field(
                    pipeline_name=pipeline.name,
                    field="flow_direction.end",
                    value=pipeline.flow_direction.end,
                    row_index=row_index,
                    line=line,
                    marker="Конец",
                )

    def _extract_gost_category(self, line, pipeline: Pipeline, *, row_index: int):
        if pipeline.parameters.gost_category:
            return

        for i, item in enumerate(line):
            if "ГОСТ 32569" in item and i + 1 < len(line):
                pipeline.parameters.gost_category = line[i + 1]
                self._audit_field(
                    pipeline_name=pipeline.name,
                    field="gost_category",
                    value=pipeline.parameters.gost_category,
                    row_index=row_index,
                    line=line,
                    marker="ГОСТ 32569",
                )

    def _extract_mounting_scheme_by_psi(self, line: list[str], pipeline: Pipeline, *, row_index: int):
        if pipeline.mounting_scheme:
            return

        first_non_empty = next((str(x).strip() for x in line if str(x).strip()), "")
        if not first_non_empty.upper().startswith("ПСИ"):
            return

        match = re.match(r"^(ПСИ[^\s,;:]*)", first_non_empty, flags=re.IGNORECASE)
        if not match:
            return

        pipeline.mounting_scheme = match.group(1)
        self._audit_field(
            pipeline_name=pipeline.name,
            field="mounting_scheme",
            value=pipeline.mounting_scheme,
            row_index=row_index,
            line=line,
            marker="ПСИ*",
        )

    def _audit_field(
        self,
        *,
        pipeline_name: str,
        field: str,
        value: str,
        row_index: int,
        line: list[str],
        marker: str,
    ) -> None:
        log_parsing_event(
            job_id=self.job_id,
            user_log_key=self.user_log_key,
            source_type=self._source_type(),
            source_file=self.source or "unknown",
            parser="PipelineParametersParser",
            entity="pipeline",
            entity_id=pipeline_name,
            field=field,
            value=value,
            origin={
                "row_index": row_index,
                "row_text": " | ".join(str(x) for x in line if str(x).strip()),
                "marker": marker,
            },
        )

    def _source_type(self) -> str:
        source = (self.source or "").lower()
        if source.endswith(".pdf"):
            return "pdf"
        if source.endswith(".xlsx") or source.endswith(".xls"):
            return "excel"
        if source.endswith(".csv"):
            return "csv"
        return "other"

    # ==========================================================
    # ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ
    # ==========================================================

    @staticmethod
    def _format_incorrect_line(line):
        strings = [
            "ВV P", "ВV P р", "ВV P ра",
            "Нет T", "Нет T р", "Нет T ра",
            "Нет P", "Нет P р", "Нет P ра",
            "— P", "— P и", "— P ис",
            "— С", "IP Спо", "I С", "IP Спос", "IP С",
        ]
        for string in strings:
            if string in line:
                idx = line.index(string)
                parts = string.split()
                line[idx] = parts[0]
                line[idx + 1] = " ".join(parts[1:]) + " " + line[idx + 1]

    @staticmethod
    def _process_temp_calc(value: str) -> str:
        """
        Преобразует строку вида '5 / 85' в человекочитаемый формат диапазона температур.
        При некорректном формате не выбрасывает исключение, а возвращает исходное значение.
        """
        try:
            first, second = value.split(" / ")

            def fmt(v: str) -> str:
                v = v.strip()
                return f"Минус {v[1:]} °С" if v.startswith("-") else f"Плюс {v} °С"

            second_fmt = fmt(second)
            # Делаем первую букву второй части маленькой: 'Плюс' → 'плюс'
            if second_fmt:
                second_fmt = second_fmt[0].lower() + second_fmt[1:]

            return f"{fmt(first)} ... {second_fmt}"
        except Exception as e:
            logger.warning(f"Ошибка при форматировании диапазона температур '{value}': {e}")
            return value

    @staticmethod
    def _format_pressure(value: str, line: list[str], idx: int) -> str:
        """
        Форматирует давление.
        Количество знаков в результате (кгс/см²) = количество знаков в исходном (МПа) - 1, но не менее 2.
        Лишние знаки отбрасываются (без округления).
        
        Примеры:
            1,6731 → 1,6731 МПа (16,731 кгс/см²)  (4 знака → 3 знака)
            0,118 → 0,118 МПа (1,18 кгс/см²)      (3 знака → 2 знака)
            1,6 → 1,6 МПа (16,00 кгс/см²)         (1 знак → 2 знака, минимум)
            1,67 → 1,67 МПа (16,70 кгс/см²)       (2 знака → 2 знака, минимум)
            1 → 1 МПа (10,00 кгс/см²)             (0 знаков → 2 знака, минимум)
        """

        # Собираем дробную часть, если есть
        if idx + 2 < len(line) and line[idx + 2].isdigit():
            value = f"{value},{line[idx + 2]}"

        try:
            getcontext().prec = 28
            
            # Преобразуем исходное значение
            mpa_decimal = Decimal(value.replace(",", "."))
            
            # Определяем количество знаков после запятой в исходном
            if "," in value:
                src_places = len(value.split(",")[1])
            elif "." in value:
                src_places = len(value.split(".")[1])
            else:
                src_places = 0
            
            # Вычисляем результат (без округления)
            kg_decimal = mpa_decimal * Decimal(10)
            
            # Определяем количество знаков для результата
            # Количество знаков в результате: исходные знаки - 1, но не менее 2.
            dst_places = max(src_places - 1, 2) if src_places > 0 else 2
            
            # Преобразуем в строку и обрабатываем вручную
            kg_str_full = format(kg_decimal, 'f')
            
            # Разделяем на целую и дробную части
            if "." in kg_str_full:
                int_part, frac_part = kg_str_full.split(".")
            else:
                int_part, frac_part = kg_str_full, ""
            
            # Обрезаем дробную часть до нужного количества знаков.
            if len(frac_part) > dst_places:
                frac_part = frac_part[:dst_places]  # Отбрасываем лишние
            else:
                frac_part = frac_part.ljust(dst_places, "0")  # Дополняем нулями
            
            kg_str = f"{int_part},{frac_part}"

        except Exception as e:
            logger.warning(f"Ошибка при форматировании давления '{value}': {e}\nline={line}")
            return value

        return f"{value} МПа ({kg_str} кгс/см²)"

