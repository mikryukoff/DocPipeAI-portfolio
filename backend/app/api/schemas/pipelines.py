from pydantic import BaseModel, Field


class PassportsZipRequest(BaseModel):
    pipeline_names: list[str] = Field(default_factory=list)


class EmbedmentElementRow(BaseModel):
    name: str = "---"
    location: str = "---"
    dn: str = "---"
    pn: str = "---"
    material_grade: str = "---"
    gost: str = "---"


class InstrumentEmbedmentUpdate(BaseModel):
    """Поля строки таблицы: либо elements (до 20), либо одна плоская строка location…gost."""

    embedment_group_key: str = ""
    instrument_tag: str = ""
    location: str = "---"
    dn: str = "---"
    pn: str = "---"
    material_grade: str = "---"
    gost: str = "---"
    elements: list[EmbedmentElementRow] | None = None
