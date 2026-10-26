from dataclasses import dataclass


@dataclass(frozen=True)
class TableBlock:
    pipeline_name: str | None
    page: str
    rows: list[list[str]]
