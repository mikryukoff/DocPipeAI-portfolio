from types import SimpleNamespace

from backend.app.infrastructure.db.mappers.pipeline_mapper import orm_to_domain_pipeline
from backend.app.infrastructure.db.models.spec_item import SpecItemORM


def test_orm_to_domain_pipeline_ignores_unknown_json_fields():
    orm = SimpleNamespace(
        name="XX01-41001-PSA-50-E010H2A00-IP",
        medium="test",
        mounting_scheme="scheme",
        flow_direction={
            "start": "от A до B",
            "end": "",
            "source_excel_flow_direction": "debug-only",
        },
        parameters={
            "gost_category": "",
            "working_pressure": "",
            "working_temperature": "",
            "calculated_pressure": "",
            "calculated_temperature": "",
            "strength_test_pressure": "",
            "strength_test_method": "",
            "strength_test_type": "",
            "strength_test_duration": "",
            "strength_test_result": "",
            "material": "",
            "installation_date": "",
            "welding_type": "",
            "welding_material": "",
            "unexpected_key": "ignore-me",
        },
        pipelines_len={},
    )
    items = [
        SpecItemORM(
            pipeline_id=1,
            page="1",
            section="pipeline_armature",
            position=1,
            name="Арматура X",
            unit="шт",
            quantity=1.0,
            extra={
                "location": "L1",
                "dn": "50",
                "pn": "10",
                "material_grade": "A182 F51",
                "gost": "",
                "source_excel_armature": "debug-only",
            },
        )
    ]
    orm.spec_items = items

    pipeline = orm_to_domain_pipeline(orm, items=items)

    assert pipeline.flow_direction.start == "от A до B"
    assert pipeline.specifications[0].pipeline_armature[0].dn == "50"
    assert pipeline.specifications[0].pipeline_armature[0].material_grade == "A182 F51"
