from collections import defaultdict
from dataclasses import asdict, fields

from backend.app.domain.models.pipeline import (
    Pipeline,
    FlowDirection,
    PipelineLength,
    PipelineParameters,
    VIKEntry,
)
from backend.app.infrastructure.db.models.pipeline import PipelineORM
from backend.app.infrastructure.db.models.spec_item import SpecItemORM
from .specification_mapper import (
    orm_items_to_specification,
)

def _filter_dataclass_kwargs(cls, payload: dict | None) -> dict:
    data = dict(payload or {})
    allowed = {f.name for f in fields(cls)}
    return {k: v for k, v in data.items() if k in allowed}


def domain_to_orm_pipeline(pipeline: Pipeline) -> PipelineORM:
    # Маппинг агрегата Pipeline -> ORM-модель + плоские строки спецификации.
    pipelines_len = pipeline.pipelines_len or {}
    orm = PipelineORM(
        name=pipeline.name,
        medium=pipeline.medium,
        mounting_scheme=pipeline.mounting_scheme,
        year=pipeline.year,
        flow_direction=asdict(pipeline.flow_direction),
        parameters=asdict(pipeline.parameters),
        pipelines_len={k: asdict(v) for k, v in pipelines_len.items()},
    )

    for spec in pipeline.specifications:
        # Разворачиваем секции в единый список spec_items (section хранит тип элемента).
        for section, items in {
            "pipes": spec.pipes,
            "pipeline_armature": spec.pipeline_armature,
            "instrument_embedments": spec.instrument_embedments,
            "connection_parts": spec.connection_parts,
            "flanges": spec.flanges,
            "supports": spec.supports,
        }.items():
            for item in items:
                orm.spec_items.append(
                    SpecItemORM(
                        page=spec.page,
                        section=section,
                        position=item.position,
                        name=item.name,
                        unit=item.unit,
                        quantity=item.quantity,
                        extra=asdict(item),
                    )
                )

    return orm


def orm_to_domain_pipeline(
    orm: PipelineORM,
    items: list[SpecItemORM],
    vik_items: list | None = None,
) -> Pipeline:
    # Собираем спецификации обратно группировкой по странице.
    specs_by_page = defaultdict(list)
    for item in items:
        specs_by_page[item.page].append(item)

    specifications = [
        orm_items_to_specification(v)
        for _, v in sorted(specs_by_page.items())
    ]

    return Pipeline(
        name=orm.name,
        medium=orm.medium,
        mounting_scheme=orm.mounting_scheme,
        flow_direction=FlowDirection(**_filter_dataclass_kwargs(FlowDirection, orm.flow_direction)),
        parameters=PipelineParameters(**_filter_dataclass_kwargs(PipelineParameters, orm.parameters)),
        pipelines_len={
            k: PipelineLength(**_filter_dataclass_kwargs(PipelineLength, v))
            for k, v in (orm.pipelines_len or {}).items()
        },
        specifications=specifications,
        vik_entries=[
            VIKEntry(
                pipe_num=(getattr(row, "pipe_num", "") or "").strip(),
                statement_text=(getattr(row, "statement_text", "") or "").strip(),
                type=(getattr(row, "type", "ВИК") or "ВИК").strip(),
            )
            for row in (vik_items or [])
            if (getattr(row, "pipe_num", "") or "").strip()
            and (getattr(row, "statement_text", "") or "").strip()
        ],
        year=getattr(orm, "year", None),
    )
