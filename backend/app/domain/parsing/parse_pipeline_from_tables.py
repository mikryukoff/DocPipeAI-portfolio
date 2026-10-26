import re
from pathlib import Path
from typing import Iterable

from loguru import logger

from backend.app.domain.parsing.csv_block_splitter import CSVBlockSplitter
from backend.app.domain.parsing.pipeline_factory import PipelineFactory
from backend.app.domain.parsing.pipeline_parameters_parser import (
    PipelineParametersParser,
)
from backend.app.domain.parsing.specification_parser import SpecificationParser
from backend.app.domain.parsing.pipe_length_calculator import PipeLengthCalculator
from backend.app.domain.models.pipeline import Pipeline
from backend.app.domain.models.specification import Specification
from backend.app.domain.models.table_block import TableBlock
from backend.app.shared.pipeline_number_format import normalize_pipeline_name


# Хвост вида ...5.7 / ...1,2 / ...1.2.3 в конце stem (после префикса с буквами/цифрами).
_DOT_COMMA_NUMERIC_SUFFIX_RE = re.compile(r"(\d+(?:[.,]\d+)+)$")


def _page_token_from_digit_dot_segment(segment: str) -> str | None:
    """
    Как последний сегмент после «-» / «,»: если сегмент только цифры — он и есть страница;
    если сегмент вида 5.7 / 5,7 / 1.2.3 (все части по «.» или «,» — цифры) — страница = последняя часть.
    """
    s = segment.strip()
    if not s:
        return None
    if "." not in s and "," not in s:
        return s if s.isdigit() else None
    parts = re.split(r"[.,]", s)
    if parts and all(p.isdigit() for p in parts):
        return parts[-1]
    return None


def _filename_stem_for_page(path_or_name: str) -> str:
    """
    stem для извлечения номера страницы. Учитывает, что Path('5.7').stem == '5',
    т.к. '.7' воспринимается как расширение; для имён вида 5.7 без .pdf возвращаем '5.7'.
    """
    p = Path(path_or_name.strip())
    stem, suff = p.stem, p.suffix
    if stem.isdigit() and suff.startswith(".") and suff[1:].isdigit():
        return f"{stem}{suff}"
    return stem.strip()


def page_from_filename(path_or_name: str) -> str:
    """
    Извлекает номер страницы из имени файла, если в таблице он не найден.
    - "12" или "12.pdf" → "1"
    - "12-4" или "12-4.pdf" → "4" (после «-» последний сегмент: только цифры или 5.7 → 7)
    - "1-1" → "1"
    - "export_7.pdf" → "7" (после «_» тот же принцип, что после «-»)
    - "5.7.pdf" → "7" (после «.» последняя числовая часть, как после «-»)
    - "5,7.pdf" → "7" (запятая — как точка)
    - "prefix_5.7.pdf" → "7"
    - "1.2.3.pdf" → "3"
    """
    if not path_or_name or not path_or_name.strip():
        return "1"
    stem = _filename_stem_for_page(path_or_name)
    if not stem:
        return "1"
    if "-" in stem:
        tok = _page_token_from_digit_dot_segment(stem.split("-")[-1])
        if tok is not None:
            return tok
    if "," in stem:
        tok = _page_token_from_digit_dot_segment(stem.split(",")[-1])
        if tok is not None:
            return tok
    if "_" in stem:
        tok = _page_token_from_digit_dot_segment(stem.split("_")[-1])
        if tok is not None:
            return tok
    m = _DOT_COMMA_NUMERIC_SUFFIX_RE.search(stem)
    if m:
        tok = _page_token_from_digit_dot_segment(m.group(1))
        if tok is not None:
            return tok
    if "." in stem or "," in stem:
        tok = _page_token_from_digit_dot_segment(stem)
        if tok is not None:
            return tok
    return "1"


class ParsePipelineFromTables:
    """
    Инкрементальный парсер таблиц:
    tables batch -> агрегированные Pipeline[]
    """

    def __init__(
        self,
        job_id: int | None = None,
        source: str | None = None,
        user_log_key: str | None = None,
    ):
        # Парсеры и фабрики состояния на время одной сессии чтения.
        self.splitter = CSVBlockSplitter()
        self.factory = PipelineFactory()
        self.param_parser = PipelineParametersParser(
            job_id=job_id, source=source, user_log_key=user_log_key
        )
        self.spec_parser = SpecificationParser(
            job_id=job_id, source=source, user_log_key=user_log_key
        )
        self.length_calc = PipeLengthCalculator()
        self._pipelines: dict[str, Pipeline] = {}
        self._spec_items_total = 0
        self._warnings: list[dict] = []
        # Контекст импорта (для логирования строк).
        self.job_id = job_id
        self.source = source
        self.user_log_key = user_log_key

    def set_context(
        self,
        job_id: int | None,
        source: str | None,
        user_log_key: str | None = None,
    ) -> None:
        """
        Обновляет контекст импорта (job_id, source) на лету.
        Используется PDFPipelineImporter, который создаёт parser без аргументов
        из-за тестовых double-классов, но позже может передать актуальные значения.
        """
        self.job_id = job_id
        self.source = source
        if user_log_key is not None:
            self.user_log_key = user_log_key
        # Пробрасываем контекст во вложенные парсеры, если у них есть соответствующие поля.
        if hasattr(self.param_parser, "job_id"):
            self.param_parser.job_id = job_id
            self.param_parser.source = source
            self.param_parser.user_log_key = self.user_log_key
        if hasattr(self.spec_parser, "job_id"):
            self.spec_parser.job_id = job_id
            self.spec_parser.source = source
            self.spec_parser.user_log_key = self.user_log_key

    def reset(self) -> None:
        self._pipelines.clear()
        self.length_calc = PipeLengthCalculator()
        self._spec_items_total = 0
        logger.debug("Parsing session reset")

    def process_tables(self, tables: list) -> dict[str, set[str]]:
        # touched: какие трубопроводы и страницы затронуты в этой пачке.
        touched: dict[str, set[str]] = {}
        logger.debug("Processing tables batch. tables={}", len(tables))

        # Имена линий из таблиц параметров на этой же странице (порядок сохраняем).
        params_pipeline_names: list[str] = []
        seen_params: set[str] = set()
        for table in tables:
            pk = getattr(table, "kind", None) or "both"
            if pk not in ("params", "both"):
                continue
            for block in self.splitter.split(table):
                pn = normalize_pipeline_name(block.pipeline_name or "")
                if pn and pn not in seen_params:
                    seen_params.add(pn)
                    params_pipeline_names.append(pn)

        spec_attach_to_params: str | None = (
            params_pipeline_names[0] if len(params_pipeline_names) == 1 else None
        )
        if len(params_pipeline_names) > 1:
            logger.debug(
                "Several params pipelines on one page; spec uses name from spec table. names={}",
                params_pipeline_names,
            )

        for table in tables:
            # kind позволяет различать таблицу параметров и таблицу спецификации,
            # которые мы теперь извлекаем раздельно по crop-боксам.
            page_kind = getattr(table, "kind", None) or "both"

            if page_kind == "spec" and spec_attach_to_params:
                blocks = self.splitter.split_spec_for_params_pipeline(
                    table, spec_attach_to_params
                )
                logger.debug(
                    "Spec table attached to params pipeline. pipeline={}",
                    spec_attach_to_params,
                )
            else:
                blocks = self.splitter.split(table)
            logger.debug("blocks={} page_kind={}", blocks, page_kind)

            # Если это таблица спецификации и по каким‑то причинам не удалось
            # вытащить имя трубопровода (например, pdfplumber отрезал шапку),
            # но при этом в текущей сессии уже есть ровно один трубопровод,
            # считаем, что вся таблица относится к нему.
            if (
                not blocks
                and page_kind == "spec"
                and len(self._pipelines) == 1
            ):
                only_name = next(iter(self._pipelines.keys()))
                logger.debug(
                    "Fallback: attach spec table to the only known pipeline. name={}",
                    only_name,
                )
                blocks = [
                    TableBlock(
                        pipeline_name=only_name,
                        page="",
                        rows=table.rows,
                    )
                ]

            for block in blocks:
                pipeline_name = normalize_pipeline_name(block.pipeline_name or "")
                if not pipeline_name:
                    continue

                pipeline = self._pipelines.get(pipeline_name)
                if pipeline is None:
                    # Создаём агрегат трубопровода один раз и дальше дополняем его.
                    pipeline = self.factory.create(pipeline_name)
                    self._pipelines[pipeline_name] = pipeline

                # Пропускаем строку заголовка: параметры и спецификация идут в data-строках.
                data_rows = block.rows[1:] if len(block.rows) > 1 else list(block.rows)
                if page_kind in ("both", "params"):
                    self.param_parser.parse(data_rows, pipeline)

                if page_kind in ("both", "spec"):
                    # Если номер страницы не найден или это подпись "стр." — берём из имени файла.
                    raw_block_page = (block.page or "").strip()
                    if not raw_block_page or raw_block_page.lower() in ("стр.", "стр"):
                        block_page = page_from_filename(self.source) if self.source else "1"
                    else:
                        block_page = raw_block_page
                    spec = self.spec_parser.parse(data_rows, block_page, pipeline.name)
                    self._warnings.extend(self.spec_parser.pop_warnings())
                    pipeline.specifications.append(spec)
                    self._spec_items_total += self._count_spec_items(spec)
                    page = spec.page or block_page or ""
                    logger.debug("page={}", page)
                    # Всегда добавляем трубопровод в touched, иначе при пустом page он не сохраняется в БД.
                    touched.setdefault(pipeline.name, set()).add(page)

                    self.length_calc.accumulate(pipeline.name, spec)
        logger.debug("Tables batch processed. pipelines={}", len(self._pipelines))
        logger.debug("touched={}", touched)
        return touched

    def snapshot(self, pipeline_names: Iterable[str] | None = None) -> list[Pipeline]:
        # Возвращаем "снимок" текущего состояния без очистки внутреннего кэша.
        if pipeline_names is None:
            names = list(self._pipelines.keys())
        else:
            names = [name for name in pipeline_names if name in self._pipelines]

        logger.debug("Snapshot pipeline names. names={}", names)

        result = []
        for name in names:
            pipeline = self._pipelines[name]
            pipeline.pipelines_len = self.length_calc.finalize(name)
            result.append(pipeline)

        logger.debug("Parsing snapshot built. pipelines={}", len(result))
        return result

    def get_pipeline(self, name: str) -> Pipeline | None:
        pipeline = self._pipelines.get(name)
        if pipeline is None:
            return None
        pipeline.pipelines_len = self.length_calc.finalize(name)
        return pipeline

    def pipelines_count(self) -> int:
        return len(self._pipelines)

    def pipeline_names(self) -> list[str]:
        return list(self._pipelines.keys())

    def spec_items_count(self) -> int:
        return self._spec_items_total

    def warnings(self) -> list[dict]:
        return list(self._warnings)

    def pop_warnings(self) -> list[dict]:
        warnings = self._warnings
        self._warnings = []
        return warnings

    @staticmethod
    def _count_spec_items(spec: Specification) -> int:
        return (
            len(spec.connection_parts)
            + len(spec.pipeline_armature)
            + len(spec.instrument_embedments)
            + len(spec.pipes)
            + len(spec.flanges)
            + len(spec.supports)
        )

