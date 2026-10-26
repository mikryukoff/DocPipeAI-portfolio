import csv
from backend.app.application.ports.table_source import TableSource
from loguru import logger


class CSVTableSource(TableSource):
    """
    Infrastructure adapter.
    Отвечает ТОЛЬКО за чтение CSV-файлов.
    """

    def __init__(self, file_paths: list[str]):
        self.file_paths = file_paths

    async def extract_tables(self) -> list[list[list[str]]]:
        tables: list[list[list[str]]] = []
        logger.info("Start CSV table extraction. files={}", len(self.file_paths))

        for path in self.file_paths:
            with open(path, encoding="utf-8-sig") as f:
                reader = csv.reader(f)
                rows = [row for row in reader if any(cell.strip() for cell in row)]

                if rows:
                    tables.append(rows)
                    logger.debug("CSV loaded. path={} rows={}", path, len(rows))

        logger.info("CSV table extraction completed. tables={}", len(tables))
        return tables

