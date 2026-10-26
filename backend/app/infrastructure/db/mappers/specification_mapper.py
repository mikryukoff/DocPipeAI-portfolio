from dataclasses import fields, is_dataclass

from backend.app.domain.models.specification import (
    Specification,
    Armature,
    InstrumentEmbedment,
    Pipe,
    ConnectionPart,
    Flange,
    Support,
)
from backend.app.domain.models.spec_section import SpecSection
from backend.app.infrastructure.db.models.spec_item import SpecItemORM
from collections import defaultdict


def _filter_model_kwargs(cls, data: dict) -> dict:
    if not is_dataclass(cls):
        return data
    allowed = {f.name for f in fields(cls)}
    return {k: v for k, v in data.items() if k in allowed}


def specification_to_orm_items(
    pipeline_id: int,
    spec: Specification,
) -> list[SpecItemORM]:
    items: list[SpecItemORM] = []

    def add(section: SpecSection, obj):
        items.append(
            SpecItemORM(
                pipeline_id=pipeline_id,
                page=spec.page,
                section=section.value,
                position=obj.position,
                name=obj.name,
                unit=obj.unit,
                quantity=obj.quantity,
                extra=obj.__dict__,
            )
        )

    for x in spec.pipeline_armature:
        add(SpecSection.PIPELINE_ARMATURE, x)

    for x in spec.instrument_embedments:
        add(SpecSection.INSTRUMENT_EMBEDMENT, x)

    for x in spec.pipes:
        add(SpecSection.PIPES, x)

    for x in spec.connection_parts:
        add(SpecSection.CONNECTION_PARTS, x)

    for x in spec.flanges:
        add(SpecSection.FLANGES, x)

    for x in spec.supports:
        add(SpecSection.SUPPORTS, x)

    return items


def _canonical_spec_item_section(section: str) -> str:
    """Старые строки в БД: instrument_embedment → instrument_embedments."""
    if section == "instrument_embedment":
        return SpecSection.INSTRUMENT_EMBEDMENT.value
    return section


def orm_items_to_specification(items: list[SpecItemORM]) -> Specification:
    grouped = defaultdict(list)

    for item in items:
        grouped[_canonical_spec_item_section(item.section)].append(item)

    def build(cls, section):
        result = []
        for i in sorted(grouped.get(section.value, []), key=lambda x: x.position):
            data = dict(i.extra or {})
            data.update(
                position=i.position,
                name=i.name,
                unit=i.unit,
                quantity=i.quantity,
            )
            result.append(cls(**_filter_model_kwargs(cls, data)))
        return result

    return Specification(
        page=items[0].page if items else "",
        pipeline_armature=build(Armature, SpecSection.PIPELINE_ARMATURE),
        instrument_embedments=build(InstrumentEmbedment, SpecSection.INSTRUMENT_EMBEDMENT),
        pipes=build(Pipe, SpecSection.PIPES),
        connection_parts=build(ConnectionPart, SpecSection.CONNECTION_PARTS),
        flanges=build(Flange, SpecSection.FLANGES),
        supports=build(Support, SpecSection.SUPPORTS),
    )
