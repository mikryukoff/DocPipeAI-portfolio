from dataclasses import dataclass


@dataclass(frozen=True)
class ExtractedTable:
    page: int
    index: int
    rows: list[list[str]]


@dataclass
class PDFTable:
    page: str
    rows: list[list[str]]
    # Тип таблицы на странице PDF: "params", "spec", "main" и т.п.
    kind: str | None = None


@dataclass
class PDFTextPage:
    page: int
    text: str