import csv
from pathlib import Path

from backend.app.application.ports.table_writer import TableWriter
from loguru import logger


class CSVTableWriter(TableWriter):
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir

    def write(self, rows: list[list[str]], page: int, index: int) -> None:
        page_dir = self.base_dir / f"page_{page}"
        page_dir.mkdir(parents=True, exist_ok=True)

        path = page_dir / f"table_{index}.csv"

        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerows(rows)

        logger.debug("CSV table written. path={} rows={}", path, len(rows))
