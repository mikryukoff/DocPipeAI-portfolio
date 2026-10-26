#!/usr/bin/env python3
"""
Список трубопроводов, у которых из Excel (режим АОСР) реально извлекается flow_direction.

Считает только то же, что цепочка импорта: листы «СоМТТ» / «Свидет.монтаже…», строки с
«линия» или с кодом линии по pipeline_code_re, затем ExcelFlowDirectionParser.try_parse.

Не путать с подсчётом всех regex-совпадений по всей книге — здесь только успешный парсинг направления.

Число совпадает с полем job.stats.flow_direction_unique_pipelines в API. Меньшее
flow_direction_updated_pipelines — сколько строк реально записано в БД (нет трубопровода с таким именем и т.п.).
Примеры:
  uv run python backend/scripts/list_aosr_flow_pipeline_names.py "data/users/admin/jobs/АОСР 2 этап.xlsx"
  uv run python backend/scripts/list_aosr_flow_pipeline_names.py path/to.xlsx --jsonl path/to/parsing_logs.jsonl --list
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd

from backend.app.domain.excel_parsing.excel_flow_direction_parser import ExcelFlowDirectionParser


def _read_workbook(excel_path: Path) -> dict[str, list[list[str]]]:
    suffix = excel_path.suffix.lower()
    engine_kw: dict[str, str] = {}
    if suffix in (".xlsx", ".xlsm"):
        engine_kw["engine"] = "openpyxl"
    xls = pd.ExcelFile(excel_path, **engine_kw)
    workbook: dict[str, list[list[str]]] = {}
    for sheet_name in xls.sheet_names:
        df = pd.read_excel(
            xls,
            sheet_name=sheet_name,
            header=None,
            dtype=str,
        ).fillna("")
        workbook[sheet_name] = [
            ["" if value is None else str(value).strip() for value in row]
            for row in df.values.tolist()
        ]
    return workbook


PIPELINE_CODE_RE = re.compile(
    r"[A-Z]{2}\d{2}-\d{5}(?:\.\d+)?-[A-Z]{3}-\d{2,3}-[A-Z0-9-]+(?:-[A-Z]{2})?"
)


def find_somtt_like_sheet_names(sheet_names: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for sheet_name in sheet_names:
        if sheet_name in seen:
            continue
        low = " ".join(sheet_name.lower().split())
        if "сомтт" in low:
            seen.add(sheet_name)
            out.append(sheet_name)
            continue
        if "свидет" in low and "монтаж" in low:
            seen.add(sheet_name)
            out.append(sheet_name)
    return out


def concat_sheet_rows(workbook: dict[str, list[list[str]]], sheet_names: list[str]) -> list[list[str]]:
    merged: list[list[str]] = []
    for sn in sheet_names:
        merged.extend(workbook.get(sn, []))
    return merged


def collect_flow_pipeline_names_from_somtt_rows(rows: list[list[str]]) -> set[str]:
    parser = ExcelFlowDirectionParser()
    names: set[str] = set()
    for row in rows:
        row_text = " ".join([cell for cell in row if cell]).strip()
        if not row_text:
            continue
        low = row_text.lower()
        if "линия" not in low and not PIPELINE_CODE_RE.search(row_text):
            continue
        parsed = parser.try_parse(row_text)
        if parsed is None:
            continue
        names.add(parsed.pipeline_name)
    return names


def load_flow_entity_ids_from_jsonl(path: Path, *, source_file_substr: str) -> set[str]:
    out: set[str] = set()
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            raw = o.get("raw") or {}
            if raw.get("parser") != "ExcelFlowDirectionParser":
                continue
            sf = str(raw.get("source_file") or "")
            if source_file_substr not in sf:
                continue
            eid = raw.get("entity_id") or o.get("pipeline")
            if eid:
                out.add(str(eid))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("excel", type=Path, help="Путь к .xlsx / .xls")
    ap.add_argument(
        "--jsonl",
        type=Path,
        default=None,
        help="Опционально: parsing_audit jsonl — сравнить с entity_id ExcelFlowDirectionParser",
    )
    ap.add_argument(
        "--source-substr",
        default="АОСР 2 этап",
        help="Подстрока source_file для фильтра jsonl (по умолчанию: АОСР 2 этап)",
    )
    ap.add_argument("--list", action="store_true", help="Печатать отсортированный список имён")
    args = ap.parse_args()

    excel_path = args.excel.resolve()
    if not excel_path.is_file():
        print(f"Файл не найден: {excel_path}", file=sys.stderr)
        return 1

    wb = _read_workbook(excel_path)
    somtt = find_somtt_like_sheet_names(list(wb.keys()))
    if not somtt:
        print("Нет листов СоМТТ / «Свидет.монтаже…» — как в импорте АОСР, направления не извлекаются.", file=sys.stderr)
        return 2

    rows = concat_sheet_rows(wb, somtt)
    names = collect_flow_pipeline_names_from_somtt_rows(rows)

    print("excel:", excel_path)
    print("somtt_sheets:", len(somtt))
    print("flow_direction_pipelines_unique:", len(names))

    if args.jsonl:
        if not args.jsonl.is_file():
            print(f"jsonl не найден: {args.jsonl}", file=sys.stderr)
            return 1
        logged = load_flow_entity_ids_from_jsonl(args.jsonl, source_file_substr=args.source_substr)
        print("jsonl_flow_entity_ids_unique:", len(logged))
        only_excel = sorted(names - logged)
        only_log = sorted(logged - names)
        print("only_in_excel_flow_parse_not_in_jsonl:", len(only_excel))
        print("only_in_jsonl_not_in_excel_reparse:", len(only_log))
        if only_excel:
            print("--- only excel ---")
            for x in only_excel:
                print(x)
        if only_log:
            print("--- only jsonl ---")
            for x in only_log:
                print(x)

    if args.list:
        for n in sorted(names):
            print(n)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
