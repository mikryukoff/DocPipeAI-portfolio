from dataclasses import dataclass, field
from ..models.specification import Specification


@dataclass
class FlowDirection:
    start: str
    end: str


@dataclass
class PipelineParameters:
    gost_category: str
    working_pressure: str
    working_temperature: str
    calculated_pressure: str
    calculated_temperature: str
    strength_test_pressure: str
    strength_test_method: str
    strength_test_type: str
    strength_test_duration: str
    material: str
    installation_date: str
    welding_type: str
    welding_material: str
    strength_test_result: str = field(default="выдержал")


@dataclass
class PipelineLength:
    total_length: float
    pages: list[str]


@dataclass
class VIKEntry:
    pipe_num: str
    statement_text: str
    type: str = field(default="ВИК")


@dataclass
class Pipeline:
    name: str
    medium: str
    mounting_scheme: str
    flow_direction: FlowDirection
    parameters: PipelineParameters
    specifications: list[Specification] = field(default_factory=list)
    pipelines_len: dict[str, PipelineLength] = field(default_factory=dict)
    vik_entries: list[VIKEntry] = field(default_factory=list)
    year: int | None = None
