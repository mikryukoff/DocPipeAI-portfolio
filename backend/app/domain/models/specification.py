from dataclasses import dataclass, field


@dataclass
class SpecificationItem:
    position: int
    name: str
    unit: str
    quantity: float


@dataclass
class Armature(SpecificationItem):
    location: str = "---"
    dn: str = "---"
    pn: str = "---"
    material_grade: str = "---"
    gost: str = "---"


@dataclass
class InstrumentEmbedment(SpecificationItem):
    """Закладная для прибора: те же поля, что у арматуры, плюс скрин и строки таблицы с чертежа."""

    location: str = "---"
    dn: str = "---"
    pn: str = "---"
    material_grade: str = "---"
    gost: str = "---"
    instrument_tag: str = ""
    drawing_image_path: str = ""
    embedment_group_key: str = ""
    # Строки таблицы на скрине (до 20); при заполнении с фронта.
    embedment_elements: list[dict] = field(default_factory=list)


@dataclass
class Pipe(SpecificationItem):
    material: str = "---"
    steel_grade: str = "---"
    gost: str = "---"
    dimensions: str = "---"


@dataclass
class ConnectionPart(Pipe):
    pass


@dataclass
class Flange(SpecificationItem):
    gost: str = "---"
    dn: str = "---"
    pn: str = "---"
    steel_grade: str = "---"
    flange_gost: str = "---"
    bolt_grade: str = "---"
    bolt_gost: str = "---"


@dataclass
class Support(SpecificationItem):
    gost: str = "---"


@dataclass
class Specification:
    page: str
    pipeline_armature: list[Armature] = field(default_factory=list)
    instrument_embedments: list[InstrumentEmbedment] = field(default_factory=list)
    pipes: list[Pipe] = field(default_factory=list)
    connection_parts: list[ConnectionPart] = field(default_factory=list)
    flanges: list[Flange] = field(default_factory=list)
    supports: list[Support] = field(default_factory=list)
