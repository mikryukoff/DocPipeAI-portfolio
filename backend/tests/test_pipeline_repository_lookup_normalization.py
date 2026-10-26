from backend.app.infrastructure.repositories.pipeline_repository import PipelineRepository


def test_normalize_pipeline_lookup_handles_mixed_alphabets_and_dashes():
    raw = "НР39−41041-PSL-100-E010H2A00"
    mixed = "XX01-41041-PSL-100-E010H2A00"

    assert (
        PipelineRepository._normalize_pipeline_lookup(raw)
        == PipelineRepository._normalize_pipeline_lookup(mixed)
    )


def test_normalize_pipeline_lookup_strips_leading_number_sign():
    assert (
        PipelineRepository._normalize_pipeline_lookup("№ЗВ.1")
        == PipelineRepository._normalize_pipeline_lookup("ЗВ.1")
    )

