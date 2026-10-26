from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.app.infrastructure.repositories.pipeline_repository import PipelineRepository


@pytest.mark.asyncio
async def test_update_parameters_from_excel_formats_strength_test_duration(monkeypatch):
    repo = PipelineRepository(session=SimpleNamespace())
    pipeline_orm = SimpleNamespace(parameters={"strength_test_method": "Вода"})

    monkeypatch.setattr(repo, "_get_pipeline_orm", AsyncMock(return_value=pipeline_orm))

    ok = await repo.update_parameters_from_excel(
        pipeline_name="P-1",
        parameters_update={
            "strength_test_duration": "30",
            "strength_test_method": "водой очищенной",
        },
    )

    assert ok is True
    assert pipeline_orm.parameters["strength_test_duration"] == "0 ч. (30 мин.)"
    assert pipeline_orm.parameters["strength_test_method"] == "водой очищенной"
