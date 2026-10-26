from backend.app.application.imports.vik_tests_persistence import vik_pipeline_name_lookup_variants
from backend.app.domain.parsing.pipeline_factory import PipelineFactory


def test_pipeline_factory_normalizes_leading_number_sign():
    pipeline = PipelineFactory().create("№ЗВ.1")
    assert pipeline.name == "ЗВ.1"


def test_vik_pipeline_name_lookup_variants_include_legacy_number_sign():
    variants = vik_pipeline_name_lookup_variants("№ЗВ.1")
    assert variants[0] == "ЗВ.1"
    assert "№ЗВ.1" in variants
