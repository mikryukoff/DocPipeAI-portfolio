"""Глобальный поиск обогащённых закладных (без реальной БД)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.app.infrastructure.repositories.pipeline_repository import PipelineRepository


def _result_rows(rows: list):
    m = MagicMock()
    m.scalars.return_value.all.return_value = rows
    return m


@pytest.mark.asyncio
async def test_find_global_enriched_matches_tag_in_peer_set():
    row = MagicMock()
    row.id = 10
    row.extra = {
        "instrument_tag": "K-MAIN",
        "embedment_group_key": "K-MAIN",
        "dn": "50",
        "pn": "16",
        "material_grade": "09Г2С",
        "gost": "ГОСТ 1",
        "source_manual_embedment": True,
    }
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            _result_rows([row]),
            _result_rows([]),
        ]
    )
    repo = PipelineRepository(session)

    tpl = await repo.find_global_enriched_instrument_embedment_extra(
        peer_tags={"K-ALIAS", "K-MAIN"},
        embedment_group_key="K-MAIN",
    )
    assert tpl is not None
    assert tpl["dn"] == "50"


@pytest.mark.asyncio
async def test_find_global_enriched_from_saved_table_only():
    saved = MagicMock()
    saved.id = 3
    saved.extra = {
        "instrument_tag": "K-ARCH",
        "embedment_group_key": "K-ARCH",
        "dn": "80",
        "pn": "16",
        "material_grade": "09Г2С",
        "gost": "ГОСТ 9",
        "source_manual_embedment": True,
    }
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            _result_rows([]),
            _result_rows([saved]),
        ]
    )
    repo = PipelineRepository(session)

    tpl = await repo.find_global_enriched_instrument_embedment_extra(
        peer_tags={"K-ARCH"},
        embedment_group_key="K-ARCH",
    )
    assert tpl is not None
    assert tpl["dn"] == "80"


@pytest.mark.asyncio
async def test_is_instrument_embedment_group_enriched_true_when_global_only():
    enriched_other = MagicMock()
    enriched_other.id = 5
    enriched_other.extra = {
        "instrument_tag": "K-MAIN",
        "embedment_group_key": "K-MAIN",
        "dn": "50",
        "pn": "16",
        "material_grade": "09Г2С",
        "gost": "ГОСТ 1",
        "source_manual_embedment": True,
    }
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            _result_rows([]),
            _result_rows([enriched_other]),
            _result_rows([]),
        ]
    )
    repo = PipelineRepository(session)

    ok = await repo.is_instrument_embedment_group_enriched(
        pipeline_id=99,
        embedment_group_key="K-MAIN",
        peer_tags={"K-ALIAS", "K-MAIN"},
    )
    assert ok is True
    assert session.execute.call_count == 3


@pytest.mark.asyncio
async def test_is_instrument_embedment_group_enriched_local_short_circuits():
    local_row = MagicMock()
    local_row.extra = {
        "instrument_tag": "K-ALIAS",
        "embedment_group_key": "K-MAIN",
        "dn": "50",
        "pn": "16",
        "material_grade": "09Г2С",
        "gost": "ГОСТ 1",
        "source_manual_embedment": True,
    }
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_result_rows([local_row]))
    repo = PipelineRepository(session)

    ok = await repo.is_instrument_embedment_group_enriched(
        pipeline_id=1,
        embedment_group_key="K-MAIN",
        peer_tags={"K-ALIAS"},
    )
    assert ok is True
    assert session.execute.call_count == 1
