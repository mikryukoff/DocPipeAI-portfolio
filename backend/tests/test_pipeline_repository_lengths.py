from types import SimpleNamespace

from backend.app.domain.models.spec_section import SpecSection
from backend.app.infrastructure.repositories.pipeline_repository import PipelineRepository


def test_build_pipelines_len_from_pipe_items_recalculates_without_double_count():
    # Имитируем итоговые строки спецификации в БД после merge (без дублей ключей).
    rows = [
        SimpleNamespace(
            section=SpecSection.PIPES.value,
            quantity=0.9,
            page="1",
            extra={"dimensions": "60,3x3,2"},
        ),
        SimpleNamespace(
            section=SpecSection.PIPES.value,
            quantity=1.1,
            page="2",
            extra={"dimensions": "60,3x3,2"},
        ),
        SimpleNamespace(
            section=SpecSection.PIPES.value,
            quantity=0.2,
            page="1",
            extra={"dimensions": "33,7x2"},
        ),
        # Не труба — должен быть проигнорирован.
        SimpleNamespace(
            section=SpecSection.SUPPORTS.value,
            quantity=100,
            page="1",
            extra={"dimensions": "60,3x3,2"},
        ),
    ]

    result = PipelineRepository._build_pipelines_len_from_pipe_items(rows)

    assert result["60,3x3,2"]["total_length"] == 2.0
    assert result["60,3x3,2"]["pages"] == ["1", "2"]
    assert result["33,7x2"]["total_length"] == 0.2
    assert result["33,7x2"]["pages"] == ["1"]
