"""Проверка сопоставления строк закладных при PATCH (алиасы, нормализация тегов)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.app.infrastructure.repositories.spec_item_repository import SpecItemRepository


@pytest.mark.asyncio
async def test_update_embedment_group_matches_aliases_by_normalized_tag():
    session = AsyncMock()
    repo = SpecItemRepository(session)

    rows = []
    for tag in ("TAG-A", "tag-a"):
        m = MagicMock()
        m.extra = {"instrument_tag": tag, "embedment_group_key": ""}
        rows.append(m)

    async def fake_list(_pipeline_id: int):
        return rows

    repo.list_instrument_embedments = fake_list  # type: ignore[method-assign]

    n = await repo.update_instrument_embedment_group(
        pipeline_id=1,
        embedment_group_key="GK",
        peer_tags={"TAG-A", "TAG-B"},
        location="Loc",
        dn="DN",
        pn="PN",
        material_grade="MG",
        gost="GOST",
        elements=None,
    )
    assert n == 2
    for m in rows:
        assert m.extra["location"] == "Loc"
        assert m.extra["embedment_group_key"] == "GK"


@pytest.mark.asyncio
async def test_update_embedment_group_sets_drawing_image_path_when_passed():
    session = AsyncMock()
    repo = SpecItemRepository(session)

    m = MagicMock()
    m.extra = {"instrument_tag": "T-1", "embedment_group_key": "GK"}
    rows = [m]

    async def fake_list(_pipeline_id: int):
        return rows

    repo.list_instrument_embedments = fake_list  # type: ignore[method-assign]

    n = await repo.update_instrument_embedment_group(
        pipeline_id=1,
        embedment_group_key="GK",
        peer_tags={"T-1"},
        location="Loc",
        dn="DN",
        pn="PN",
        material_grade="MG",
        gost="GOST",
        elements=None,
        drawing_image_path="data/ocr/crop_page/x.png",
    )
    assert n == 1
    assert m.extra["drawing_image_path"] == "data/ocr/crop_page/x.png"


@pytest.mark.asyncio
async def test_sync_drawing_paths_from_store_fills_path(monkeypatch):
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class _Entry:
        path: str
        group_key: str
        peer_tags: frozenset

    store = MagicMock()

    def _resolve(s: str):
        if (s or "").strip() == "T-1":
            return _Entry("data/ocr/crop_page/a.png", "T-1", frozenset({"T-1"}))
        return None

    store.resolve = _resolve
    monkeypatch.setattr(
        "backend.app.domain.parsing.drawing_4_store.reset_drawing_4_store",
        lambda: None,
    )
    monkeypatch.setattr(
        "backend.app.domain.parsing.drawing_4_store.get_drawing_4_store",
        lambda: store,
    )

    class _Row:
        def __init__(self) -> None:
            self.extra: dict = {"instrument_tag": "T-1"}

    row = _Row()
    session = AsyncMock()

    async def exec_q(_stmt):
        res = MagicMock()
        res.scalars = lambda: MagicMock(all=lambda: [row])
        return res

    session.execute = exec_q
    session.flush = AsyncMock()

    monkeypatch.setattr(
        "backend.app.infrastructure.repositories.spec_item_repository.flag_modified",
        lambda *_a, **_k: None,
    )

    repo = SpecItemRepository(session)
    n = await repo.sync_instrument_embedment_drawing_paths_from_store(only_missing=True)
    assert n == 1
    assert row.extra["drawing_image_path"] == "data/ocr/crop_page/a.png"


@pytest.mark.asyncio
async def test_sync_drawing_paths_skips_when_only_missing_and_path_set(monkeypatch):
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class _Entry:
        path: str
        group_key: str
        peer_tags: frozenset

    store = MagicMock()
    store.resolve = lambda s: _Entry("data/ocr/crop_page/new.png", "T-1", frozenset({"T-1"}))
    monkeypatch.setattr(
        "backend.app.domain.parsing.drawing_4_store.reset_drawing_4_store",
        lambda: None,
    )
    monkeypatch.setattr(
        "backend.app.domain.parsing.drawing_4_store.get_drawing_4_store",
        lambda: store,
    )

    class _Row:
        def __init__(self) -> None:
            self.extra: dict = {
                "instrument_tag": "T-1",
                "drawing_image_path": "data/ocr/crop_page/old.png",
            }

    row = _Row()
    session = AsyncMock()

    async def exec_q(_stmt):
        res = MagicMock()
        res.scalars = lambda: MagicMock(all=lambda: [row])
        return res

    session.execute = exec_q
    session.flush = AsyncMock()

    monkeypatch.setattr(
        "backend.app.infrastructure.repositories.spec_item_repository.flag_modified",
        lambda *_a, **_k: None,
    )

    repo = SpecItemRepository(session)
    n = await repo.sync_instrument_embedment_drawing_paths_from_store(only_missing=True)
    assert n == 0
    assert row.extra["drawing_image_path"] == "data/ocr/crop_page/old.png"
