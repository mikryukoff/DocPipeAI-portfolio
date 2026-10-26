#!/usr/bin/env python3
"""
Слияние всех *.json в каталоге распознанных OCR (parsed_texts) в один файл merged.json.

При повторяющихся ключах сохраняется запись из более старого файла (меньший st_mtime).

Исключает merged.json из входа, чтобы не смешивать с предыдущим результатом.

Запуск из корня репозитория:
  uv run python backend/scripts/merge_parsed_texts_dir.py
  uv run python backend/scripts/merge_parsed_texts_dir.py path/to/parsed_texts
"""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path

MERGED_FILENAME = "merged.json"


def merge_parsed_texts_dir(target_dir: Path) -> Path:
    if not target_dir.is_dir():
        raise SystemExit(f"Не каталог: {target_dir}")

    sources = sorted(
        (p for p in target_dir.glob("*.json") if p.name != MERGED_FILENAME),
        key=lambda p: (p.stat().st_mtime_ns, p.name),
    )
    merged: dict[str, object] = {}
    for jpath in sources:
        try:
            data = json.loads(jpath.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"Пропуск {jpath.name}: {e}", file=sys.stderr)
            continue
        if not isinstance(data, dict):
            print(f"Пропуск {jpath.name}: корень не объект", file=sys.stderr)
            continue
        for key, raw in data.items():
            if not isinstance(key, str) or not key.strip():
                continue
            k = key.strip()
            if k in merged:
                continue
            if isinstance(raw, dict):
                merged[k] = deepcopy(raw)
            else:
                merged[k] = raw

    out_path = target_dir / MERGED_FILENAME
    out_path.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "dir",
        nargs="?",
        default=None,
        help="Каталог с *.json (по умолчанию: OCR_PARSED_OUTPUT_PATH из конфига или data/ocr/parsed_texts)",
    )
    args = ap.parse_args()
    if args.dir:
        d = Path(args.dir)
    else:
        try:
            from backend.app.config import load_config

            d = Path(load_config().ocr.parsed_output_dir)
        except Exception:
            d = Path("data/ocr/parsed_texts")

    out = merge_parsed_texts_dir(d.resolve())
    n = len(json.loads(out.read_text(encoding="utf-8")))
    print(f"Записано: {out} ({n} ключей)")


if __name__ == "__main__":
    main()
