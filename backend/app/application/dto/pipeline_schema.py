from pydantic import BaseModel
from typing import Dict, List


class FlowDirectionSchema(BaseModel):
    start: str
    end: str


class PipelineParametersSchema(BaseModel):
    gost_category: str
    working_pressure: str
    working_temperature: str
    calculated_pressure: str
    calculated_temperature: str
    strength_test_pressure: str
    strength_test_method: str
    strength_test_type: str
    material: str


class PipelineLengthSchema(BaseModel):
    total_length: float
    pages: List[str]


class SpecificationSchema(BaseModel):
    pipeline_armature: list
    instrument_embedments: list
    pipes: list
    connection_parts: list
    flanges: list
    supports: list
    page: str


class PipelineSchema(BaseModel):
    medium: str
    mounting_scheme: str
    year: int | None = None
    flow_direction: FlowDirectionSchema
    parameters: PipelineParametersSchema
    specifications: List[SpecificationSchema]
    pipelines_len: Dict[str, PipelineLengthSchema]
