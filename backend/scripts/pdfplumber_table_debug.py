"""
Интерактивное тестовое окружение для подбора настроек pdfplumber при извлечении таблиц.

Запуск из корня проекта:
    uv run python -m backend.scripts.pdfplumber_table_debug --pdf data/raw/pdf/28-2.pdf

Также можно запускать файл напрямую (корень репозитория добавляется в sys.path автоматически):
    python backend/scripts/pdfplumber_table_debug.py --pdf ...

Что делает скрипт:
  - Открывает PDF и для выбранных страниц прогоняет несколько наборов настроек pdfplumber.
  - Для каждой комбинации:
      * Сохраняет PNG c page.to_image().debug_tablefinder(table_settings).
      * Печатает извлечённые таблицы в консоль (до и после слияния строк).
  - Позволяет быстро менять конфигурации table_settings и логику merge_table_rows.

Полезно для ручного подбора:
  - snap_x_tolerance / snap_y_tolerance — как далеко «схлопываются» почти совпадающие линии.
  - join_x_tolerance / join_y_tolerance — как далеко можно «дотянуть» линии, чтобы соединить ячейки.
  - min_words_horizontal / min_words_vertical и другие параметры — см. документацию pdfplumber.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable, Iterable, List

# Running as `python path/to/pdfplumber_table_debug.py` puts `backend/scripts` on sys.path;
# `backend` package lives at repo root — add it before importing.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pdfplumber

from backend.app.infrastructure.files.pdf.pdf_table_debug_render import render_pdf_table_debug_png


# --- Ручные настройки области интереса ----------------------------------------
# Эти координаты мы «подсмотрели» на варианте snap2 для листа со спецификацией.
# Система координат pdfplumber:
#   (x0, top, x1, bottom)
#   x0/x1 — слева направо, top/bottom — сверху вниз, в единицах PDF (пункты).
#
# Ты можешь:
#   - включить/выключить обрезку SPEC_TABLE_CROP_ENABLED;
#   - двигать границы SPEC_TABLE_CROP_BOX и сразу видеть эффект;
#   - при необходимости завести ещё один bbox для нижней строки параметров и т.п.
SPEC_TABLE_CROP_ENABLED: bool = False
SPEC_TABLE_CROP_BOX: tuple[float, float, float, float] = (
    790.0,  # x0 — левая граница области спецификации
    40.0,   # top — верхняя граница
    1181.0, # x1 — правая граница
    680.0,  # bottom — нижняя граница
)
# PARAMS_TABLE_CROP_BOX: tuple[float, float, float, float] = (
#     55.0,  # x0 — левая граница области спецификации
#     660.0,   # top — верхняя граница
#     655.0, # x1 — правая граница
#     830.0,  # bottom — нижняя граница
# )
# MAIN_TABLE_CROP_BOX: tuple[float, float, float, float] = (
#     680.0,  # x0 — левая граница области спецификации
#     675.0,   # top — верхняя граница
#     1181.0, # x1 — правая граница
#     830.0,  # bottom — нижняя граница
# )


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_table_settings_configs() -> list[dict]:
    """
    Генерирует множество пресетов настроек pdfplumber для перебора.

    Идея:
      - Базовые варианты snap_x/y_tolerance (0, 2, 4, 6, 8).
      - Для части вариантов — добавляем join_x/y_tolerance (0, 4, 8).
      - Отдельные «особые» пресеты: vertical_words, explicit_edges.

    Итого получается 10+ комбинаций, не захламляя код вручную выписанными словарями.
    """
    configs: list[dict] = []

    # Основной пресет сетки: snap1 (как тебе понравился).
    configs.append(
        {
            "name": "snap1",
            "table_settings": {
                "snap_x_tolerance": 5,
                "snap_y_tolerance": 5,
            },
        }
    )

    return configs


def merge_table_rows(
    rows: list[list[str]],
    expected_cols: int,
    is_start_func: Callable[[list[str]], bool] | None = None,
) -> list[list[str]]:
    """
    Объединяет "разорванные" строки таблицы.

    Идея:
      - Строка, которая начинается с номера позиции (первая ячейка — цифра), считается
        началом логической строки (is_start_func).
      - Если следующая строка короче expected_cols и НЕ является стартовой,
        её ячейки "приклеиваются" к предыдущей (чаще всего это продолжение наименования).

    Параметры:
      - rows: результат page.extract_tables(...) / clean_table(...)
      - expected_cols: ожидаемое количество колонок (например, 4: поз., наименование, ед., кол-во).
      - is_start_func: функция, определяющая, считается ли строка началом новой позиции.
                       По умолчанию: первая ячейка — целое число.
    """

    def default_is_start(row: list[str]) -> bool:
        if not row:
            return False
        first = (row[0] or "").strip()
        return first.isdigit()

    start_predicate = is_start_func or default_is_start

    merged: list[list[str]] = []
    current: list[str] | None = None

    for row in rows:
        # Нормализуем длину строки, чтобы было проще анализировать
        normalized = list(row)

        if current is None:
            # Первая логическая строка
            current = normalized
            continue

        if start_predicate(normalized):
            # Это начало новой позиции — закрываем предыдущую.
            merged.append(current)
            current = normalized
            continue

        # Продолжение предыдущей строки: приклеиваем ячейки к current.
        # Простейшая стратегия: поэлементно дописывать текст через пробел.
        for idx, cell in enumerate(normalized):
            if not cell:
                continue
            if idx < len(current):
                cur_val = current[idx] or ""
                current[idx] = (cur_val + " " + cell).strip() if cur_val else cell
            else:
                current.append(cell)

    if current is not None:
        merged.append(current)

    return merged


def debug_pdf_tables(
    pdf_path: Path,
    output_dir: Path,
    pages: Iterable[int] | None = None,
) -> None:
    """
    Основная функция:
      - Перебирает TABLE_SETTINGS_CONFIGS.
      - Для выбранных страниц сохраняет PNG с debug_tablefinder и печатает таблицы.
    """
    ensure_dir(output_dir)

    print(f"Opening PDF: {pdf_path}")
    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
        if pages is None:
            pages_to_process = range(1, total_pages + 1)
        else:
            pages_to_process = [p for p in pages if 1 <= p <= total_pages]

        configs = build_table_settings_configs()

        for page_num in pages_to_process:
            page = pdf.pages[page_num - 1]
            # При необходимости обрезаем страницу до области спецификации.
            # Это делается ОДИН раз на страницу, дальше работаем только с crop_page.
            if SPEC_TABLE_CROP_ENABLED:
                crop_box = SPEC_TABLE_CROP_BOX
                print(f"Using crop box for page {page_num}: {crop_box}")
                work_page = page.crop(crop_box)
            else:
                work_page = page

            print("=" * 80)
            print(f"PAGE {page_num}/{total_pages}")

            for cfg in configs:
                name = cfg["name"]
                table_settings = dict(cfg["table_settings"])

                # Для режима explicit_edges нужно подставить линии конкретной страницы.
                if name == "explicit_edges":
                    edges = work_page.curves + work_page.edges
                    table_settings["explicit_vertical_lines"] = edges
                    table_settings["explicit_horizontal_lines"] = edges
                print("-" * 40)
                print(f"Config: {name}  table_settings={table_settings}")

                # --- Визуализация границ таблиц (общий рендер с API) ---
                crop_flag = "spec" if SPEC_TABLE_CROP_ENABLED else "full"
                png_bytes = render_pdf_table_debug_png(
                    pdf_path,
                    page_num=page_num,
                    crop=crop_flag,
                    resolution=150,
                    table_settings=table_settings,
                )
                img_path = output_dir / f"page_{page_num:03d}_{name}.png"
                img_path.write_bytes(png_bytes)
                print(f"Saved debug image: {img_path}")

                # --- Извлечение таблиц ---
                raw_tables = work_page.extract_tables(table_settings=table_settings) or []
                print(f"Extracted {len(raw_tables)} raw tables.")

                for t_idx, table in enumerate(raw_tables, start=1):
                    print(f"  Table #{t_idx} raw:")
                    for r in table:
                        print("    RAW:", r)

                    # Пробуем слить строки с ожидаемыми 4 колонками (позиция, имя, ед., кол-во).
                    merged = merge_table_rows(table, expected_cols=4, is_start_func=None)
                    print(f"  Table #{t_idx} merged:")
                    for r in merged:
                        print("    MRG:", r)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Отладка настроек pdfplumber для извлечения таблиц."
    )
    parser.add_argument(
        "--pdf",
        type=str,
        default="data/users/admin/jobs/1.pdf",
        help="Путь к проблемному PDF (по умолчанию data/raw/pdf/87.pdf).",
    )
    parser.add_argument(
        "--pages",
        type=str,
        default="",
        help="Список страниц через запятую (например, '1,2,5'). Пусто — все страницы.",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="data/debug/pdf_tables",
        help="Директория для сохранения PNG с визуализацией.",
    )

    args = parser.parse_args()
    pdf_path = Path(args.pdf)
    output_dir = Path(args.out)

    if args.pages.strip():
        pages = [int(p.strip()) for p in args.pages.split(",") if p.strip()]
    else:
        pages = None

    debug_pdf_tables(pdf_path=pdf_path, output_dir=output_dir, pages=pages)


if __name__ == "__main__":
    main()

