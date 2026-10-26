from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import backend.app.application.embedment.instrument_embedment_service as emb_svc
from backend.app.application.embedment.instrument_embedment_service import (
    InstrumentEmbedmentService,
)
from backend.app.infrastructure.repositories.embedment_draft_repository import (
    EmbedmentDraftRepository,
)
from backend.app.application.exceptions import PipelineNotFoundError, ValidationError
from backend.app.domain.parsing.drawing_4_store import Drawing4Entry


class _FakePipelineRepo:
    def __init__(self, pipeline_id: int | None):
        self.pipeline_id = pipeline_id

    async def get_id_by_name(self, _pipeline_name: str):
        return self.pipeline_id


class _FakePipelineRepoForFlat:
    def __init__(self, name_to_id: dict[str, int]):
        self.name_to_id = dict(name_to_id)

    async def list_names(self):
        return sorted(self.name_to_id.keys())

    async def get_id_by_name(self, name: str):
        return self.name_to_id.get(name)


class _FakeSpecRepo:
    def __init__(self, items=None):
        self.items = items or []
        self.patch_kwargs = None
        self.session = MagicMock()

    async def list_instrument_embedments(self, _pipeline_id: int):
        return self.items

    async def update_instrument_embedment_group(self, **kwargs):
        self.patch_kwargs = kwargs
        return 3


class _FakeSpecRepoByPipelineId:
    """Разный состав закладных по pipeline_id (несколько трубопроводов)."""

    def __init__(self, pipeline_id_to_items: dict[int, list]):
        self._by_pid = dict(pipeline_id_to_items)
        self.patch_kwargs = None
        self.session = MagicMock()

    async def list_instrument_embedments(self, pipeline_id: int):
        return list(self._by_pid.get(pipeline_id, []))

    async def update_instrument_embedment_group(self, **kwargs):
        self.patch_kwargs = kwargs
        return 3


class _FakeDrawingStore:
    def __init__(self, entry=None):
        self.entry = entry

    def resolve(self, _key: str):
        return self.entry


class _FakeDrawingStoreSplitResolve:
    """Два entry с разным group_key, одинаковым набором peer_tags — кластер должен быть один."""

    def __init__(self):
        self.e1 = Drawing4Entry(
            group_key="KEY-A",
            path="a.png",
            peer_tags=frozenset({"TAG-A", "TAG-B"}),
        )
        self.e2 = Drawing4Entry(
            group_key="KEY-B",
            path="b.png",
            peer_tags=frozenset({"TAG-A", "TAG-B"}),
        )

    def resolve(self, key: str):
        k = (key or "").strip()
        if k == "TAG-A":
            return self.e1
        if k == "TAG-B":
            return self.e2
        return None


class _FakeDrawingStoreStrictKey:
    """Resolve только если ключ совпал с каноническим PG-1 (как в JSON)."""

    def __init__(self):
        self.entry = Drawing4Entry(
            group_key="PG-1",
            path="p.png",
            peer_tags=frozenset({"PG-1", "PG-2"}),
        )

    def resolve(self, key: str):
        if (key or "").strip() == "PG-1":
            return self.entry
        return None


class _FakeDrawingStoreOverlappingPeers:
    """Два JSON-ключа с пересечением peer_tags — один объединённый список."""

    def __init__(self):
        self.e1 = Drawing4Entry(
            group_key="G1",
            path="a.png",
            peer_tags=frozenset({"TAG-A", "TAG-B"}),
        )
        self.e2 = Drawing4Entry(
            group_key="G2",
            path="b.png",
            peer_tags=frozenset({"TAG-B", "TAG-C"}),
        )

    def resolve(self, key: str):
        k = (key or "").strip()
        if k in ("TAG-A", "TAG-B"):
            return self.e1
        if k == "TAG-C":
            return self.e2
        return None


class _FakeDrawingStoreOnlyPrimaryTagResolves:
    """Второй номер группы есть только в peer_tags JSON; resolve("PG-2") = None."""

    def __init__(self):
        self.entry = Drawing4Entry(
            group_key="PG-1",
            path="p.png",
            peer_tags=frozenset({"PG-1", "PG-2"}),
        )

    def resolve(self, key: str):
        if (key or "").strip() == "PG-1":
            return self.entry
        return None


class _Elem:
    def __init__(self, **kwargs):
        self._payload = dict(kwargs)

    def model_dump(self):
        return dict(self._payload)


@pytest.mark.asyncio
async def test_list_pipeline_embedments_builds_groups_with_dedup():
    service = InstrumentEmbedmentService()
    repo = _FakePipelineRepo(10)
    items = [
        SimpleNamespace(
            id=1,
            name="Item A",
            page="1",
            position=1,
            extra={
                "embedment_group_key": "GK-1",
                "instrument_tag": "TAG-1",
                "drawing_image_path": "data/ocr/crop_page/a.png",
                "location": "L1",
                "dn": "DN50",
                "pn": "PN16",
                "material_grade": "09Г2С",
                "gost": "ГОСТ 1",
            },
        ),
        SimpleNamespace(
            id=2,
            name="Item B",
            page="1",
            position=2,
            extra={"embedment_group_key": "GK-1", "instrument_tag": "TAG-1"},
        ),
    ]
    spec_repo = _FakeSpecRepo(items=items)

    result = await service.list_pipeline_embedments(
        pipeline_name="P-1",
        repo=repo,
        spec_repo=spec_repo,
    )

    assert result["pipeline_name"] == "P-1"
    assert len(result["groups"]) == 1
    group = result["groups"][0]
    assert group["embedment_group_key"] == "GK-1"
    assert group["crop_image_url"].startswith("/pipelines/embedment-crop-image?path=")
    assert group["elements"][0]["name"] == "Item A"


@pytest.mark.asyncio
async def test_list_all_embedments_flat_expands_aliases_from_drawing_store():
    service = InstrumentEmbedmentService()
    store = _FakeDrawingStore(
        Drawing4Entry(
            group_key="TAG-A",
            path="x.png",
            peer_tags=frozenset({"TAG-A", "TAG-B"}),
        )
    )
    items = [
        SimpleNamespace(
            id=1,
            name="Item 1",
            page="1",
            position=3,
            extra={
                "instrument_tag": "TAG-A",
                "embedment_group_key": "",
                "drawing_image_path": "data/ocr/crop_page/a.png",
            },
        ),
    ]
    spec_repo = _FakeSpecRepo(items=items)
    repo = _FakePipelineRepoForFlat({"P-1": 10})

    result = await service.list_all_embedments_flat_for_admin(
        repo=repo,
        spec_repo=spec_repo,
        drawing_store=store,
    )
    emb = result["embedments"]
    assert len(emb) == 2
    tags = {e["list_instrument_tag"] for e in emb}
    assert tags == {"TAG-A", "TAG-B"}
    for e in emb:
        assert e["pipeline_name"] == "P-1"
        assert e["pipeline_names"] == ["P-1"]
        assert e["position"] == 3
        assert set(e["group"]["peer_tags"]) == {"TAG-A", "TAG-B"}
        assert e["group"]["instrument_tag"] in {"TAG-A", "TAG-B"}


@pytest.mark.asyncio
async def test_list_all_one_card_per_tag_when_same_instrument_on_two_pipelines():
    """Один нормализованный тег в двух трубопроводах — одна строка ответа, список трубопроводов."""
    service = InstrumentEmbedmentService()
    store = _FakeDrawingStore(entry=None)
    spec_repo = _FakeSpecRepoByPipelineId(
        {
            10: [
                SimpleNamespace(
                    id=1,
                    name="A",
                    page="1",
                    position=1,
                    extra={"instrument_tag": "ZZ04-SHARED", "drawing_image_path": ""},
                ),
            ],
            20: [
                SimpleNamespace(
                    id=2,
                    name="B",
                    page="2",
                    position=1,
                    extra={"instrument_tag": "ZZ04-SHARED", "drawing_image_path": ""},
                ),
            ],
        }
    )
    repo = _FakePipelineRepoForFlat({"Line-A": 10, "Line-B": 20})

    result = await service.list_all_embedments_flat_for_admin(
        repo=repo,
        spec_repo=spec_repo,
        drawing_store=store,
    )
    emb = result["embedments"]
    assert len(emb) == 1
    assert emb[0]["list_instrument_tag"] == "ZZ04-SHARED"
    assert emb[0]["pipeline_names"] == ["Line-A", "Line-B"]


@pytest.mark.asyncio
async def test_list_all_embedments_flat_collapses_peer_tags_differing_only_by_case():
    service = InstrumentEmbedmentService()
    store = _FakeDrawingStore(
        Drawing4Entry(
            group_key="TAG-A",
            path="x.png",
            peer_tags=frozenset({"TAG-A", "tag-a", "TAG-B"}),
        )
    )
    items = [
        SimpleNamespace(
            id=1,
            name="Item 1",
            page="1",
            position=1,
            extra={"instrument_tag": "TAG-A", "drawing_image_path": "a.png"},
        ),
    ]
    spec_repo = _FakeSpecRepo(items=items)
    repo = _FakePipelineRepoForFlat({"P-1": 10})

    result = await service.list_all_embedments_flat_for_admin(
        repo=repo,
        spec_repo=spec_repo,
        drawing_store=store,
    )
    emb = result["embedments"]
    assert len(emb) == 2
    assert {e["list_instrument_tag"] for e in emb} == {"TAG-A", "TAG-B"}


@pytest.mark.asyncio
async def test_list_all_embedments_flat_one_cluster_per_drawing_group_key():
    """Много строк спецификации с одной группой чертежа — разворачиваем peer_tags один раз."""
    service = InstrumentEmbedmentService()
    store = _FakeDrawingStore(
        Drawing4Entry(
            group_key="TAG-A",
            path="x.png",
            peer_tags=frozenset({"TAG-A", "TAG-B"}),
        )
    )
    items = []
    for i in range(5):
        items.append(
            SimpleNamespace(
                id=i + 1,
                name=f"Row {i}",
                page="1",
                position=i + 1,
                extra={"instrument_tag": "TAG-A", "drawing_image_path": "a.png"},
            )
        )
    spec_repo = _FakeSpecRepo(items=items)
    repo = _FakePipelineRepoForFlat({"P-1": 10})

    result = await service.list_all_embedments_flat_for_admin(
        repo=repo,
        spec_repo=spec_repo,
        drawing_store=store,
    )
    emb = result["embedments"]
    assert len(emb) == 2
    assert {e["list_instrument_tag"] for e in emb} == {"TAG-A", "TAG-B"}


@pytest.mark.asyncio
async def test_list_all_embedments_flat_dedupes_same_tag_across_spec_rows():
    service = InstrumentEmbedmentService()
    store = _FakeDrawingStore(
        Drawing4Entry(
            group_key="TAG-A",
            path="x.png",
            peer_tags=frozenset({"TAG-A", "TAG-B"}),
        )
    )
    items = [
        SimpleNamespace(
            id=1,
            name="Item 1",
            page="1",
            position=1,
            extra={"instrument_tag": "TAG-A", "drawing_image_path": "a.png"},
        ),
        SimpleNamespace(
            id=2,
            name="Item 2",
            page="1",
            position=2,
            extra={"instrument_tag": "TAG-B", "drawing_image_path": "b.png"},
        ),
    ]
    spec_repo = _FakeSpecRepo(items=items)
    repo = _FakePipelineRepoForFlat({"P-1": 10})

    result = await service.list_all_embedments_flat_for_admin(
        repo=repo,
        spec_repo=spec_repo,
        drawing_store=store,
    )
    emb = result["embedments"]
    assert len(emb) == 2
    assert {e["list_instrument_tag"] for e in emb} == {"TAG-A", "TAG-B"}


@pytest.mark.asyncio
async def test_list_all_embedments_flat_dedupes_instrument_tag_case_variants():
    service = InstrumentEmbedmentService()
    store = _FakeDrawingStore(entry=None)
    items = [
        SimpleNamespace(
            id=1,
            name="A",
            page="1",
            position=1,
            extra={"instrument_tag": "TT-01", "drawing_image_path": ""},
        ),
        SimpleNamespace(
            id=2,
            name="B",
            page="1",
            position=2,
            extra={"instrument_tag": "tt-01", "drawing_image_path": ""},
        ),
    ]
    spec_repo = _FakeSpecRepo(items=items)
    repo = _FakePipelineRepoForFlat({"P-1": 10})

    result = await service.list_all_embedments_flat_for_admin(
        repo=repo,
        spec_repo=spec_repo,
        drawing_store=store,
    )
    emb = result["embedments"]
    assert len(emb) == 1
    assert emb[0]["list_instrument_tag"] == "TT-01"


@pytest.mark.asyncio
async def test_list_all_dedupes_instrument_tag_zero_width_duplicate():
    service = InstrumentEmbedmentService()
    store = _FakeDrawingStore(entry=None)
    items = [
        SimpleNamespace(
            id=1,
            name="A",
            page="1",
            position=1,
            extra={"instrument_tag": "SOLO-1", "drawing_image_path": ""},
        ),
        SimpleNamespace(
            id=2,
            name="B",
            page="1",
            position=2,
            extra={"instrument_tag": "SOLO-1\u200b", "drawing_image_path": ""},
        ),
    ]
    spec_repo = _FakeSpecRepo(items=items)
    repo = _FakePipelineRepoForFlat({"P-1": 10})

    result = await service.list_all_embedments_flat_for_admin(
        repo=repo,
        spec_repo=spec_repo,
        drawing_store=store,
    )
    emb = result["embedments"]
    assert len(emb) == 1


@pytest.mark.asyncio
async def test_list_all_embedments_flat_single_when_no_drawing_entry():
    service = InstrumentEmbedmentService()
    store = _FakeDrawingStore(entry=None)
    items = [
        SimpleNamespace(
            id=1,
            name="Item 1",
            page="1",
            position=1,
            extra={"instrument_tag": "SOLO", "drawing_image_path": ""},
        ),
    ]
    spec_repo = _FakeSpecRepo(items=items)
    repo = _FakePipelineRepoForFlat({"P-1": 10})

    result = await service.list_all_embedments_flat_for_admin(
        repo=repo,
        spec_repo=spec_repo,
        drawing_store=store,
    )
    emb = result["embedments"]
    assert len(emb) == 1
    assert emb[0]["list_instrument_tag"] == "SOLO"
    assert "peer_tags" not in emb[0]["group"]


class _EmbedmentDraftRepoStub:
    """Реальный compute_dedup_key; upsert — заглушка (в тесте не нужна БД)."""

    compute_dedup_key = staticmethod(EmbedmentDraftRepository.compute_dedup_key)

    def __init__(self, _session):
        pass

    async def upsert(self, **_kwargs):
        return None


@pytest.mark.asyncio
async def test_patch_pipeline_embedments_uses_drawing_store_resolution(monkeypatch):
    monkeypatch.setattr(emb_svc, "EmbedmentDraftRepository", _EmbedmentDraftRepoStub)
    service = InstrumentEmbedmentService()
    repo = _FakePipelineRepo(7)
    spec_repo = _FakeSpecRepo()
    body = SimpleNamespace(
        embedment_group_key="",
        instrument_tag="T-100",
        location="L",
        dn="DN100",
        pn="PN40",
        material_grade="12Х18Н10Т",
        gost="ГОСТ",
        elements=None,
    )
    drawing_store = _FakeDrawingStore(
        Drawing4Entry(
            group_key="GR-42",
            path="p.png",
            peer_tags=frozenset({"T-100", "T-101"}),
        )
    )

    result = await service.patch_pipeline_embedments(
        pipeline_name="PIPE",
        body=body,
        repo=repo,
        spec_repo=spec_repo,
        drawing_store=drawing_store,
    )

    assert result == {"updated": 3}
    assert spec_repo.patch_kwargs["embedment_group_key"] == "GR-42"
    assert spec_repo.patch_kwargs["peer_tags"] == {"T-100", "T-101"}


@pytest.mark.asyncio
async def test_patch_pipeline_embedments_rejects_empty_element_name():
    service = InstrumentEmbedmentService()
    repo = _FakePipelineRepo(7)
    spec_repo = _FakeSpecRepo()
    body = SimpleNamespace(
        embedment_group_key="",
        instrument_tag="T-100",
        location="---",
        dn="DN100",
        pn="PN40",
        material_grade="12Х18Н10Т",
        gost="ГОСТ",
        elements=[
            _Elem(
                name="---",
                location="---",
                dn="DN100",
                pn="PN40",
                material_grade="12Х18Н10Т",
                gost="ГОСТ",
            )
        ],
    )
    drawing_store = _FakeDrawingStore(
        Drawing4Entry(
            group_key="GR-42",
            path="p.png",
            peer_tags=frozenset({"T-100", "T-101"}),
        )
    )

    with pytest.raises(ValidationError) as exc:
        await service.patch_pipeline_embedments(
            pipeline_name="PIPE",
            body=body,
            repo=repo,
            spec_repo=spec_repo,
            drawing_store=drawing_store,
        )
    assert "Наименование обязательно" in str(exc.value)
    assert spec_repo.patch_kwargs is None


@pytest.mark.asyncio
async def test_embedment_operations_raise_when_pipeline_not_found():
    service = InstrumentEmbedmentService()
    repo = _FakePipelineRepo(None)
    spec_repo = _FakeSpecRepo()
    with pytest.raises(PipelineNotFoundError):
        await service.list_pipeline_embedments(
            pipeline_name="X",
            repo=repo,
            spec_repo=spec_repo,
        )


def test_admin_tag_dedup_key_unifies_unicode_dash():
    a = InstrumentEmbedmentService._admin_tag_dedup_key("PG\u20131")
    b = InstrumentEmbedmentService._admin_tag_dedup_key("PG-1")
    assert a == b
    assert a == "pg-1"


def test_admin_tag_dedup_key_collapses_internal_spaces():
    a = InstrumentEmbedmentService._admin_tag_dedup_key("PG  100")
    b = InstrumentEmbedmentService._admin_tag_dedup_key("PG 100")
    assert a == b
    assert a == "pg 100"


@pytest.mark.asyncio
async def test_list_all_clusters_by_normalized_peer_set_not_json_key():
    service = InstrumentEmbedmentService()
    store = _FakeDrawingStoreSplitResolve()
    items = [
        SimpleNamespace(
            id=1,
            name="R1",
            page="1",
            position=1,
            extra={"instrument_tag": "TAG-A", "drawing_image_path": ""},
        ),
        SimpleNamespace(
            id=2,
            name="R2",
            page="1",
            position=2,
            extra={"instrument_tag": "TAG-B", "drawing_image_path": ""},
        ),
    ]
    spec_repo = _FakeSpecRepo(items=items)
    repo = _FakePipelineRepoForFlat({"P-1": 10})

    result = await service.list_all_embedments_flat_for_admin(
        repo=repo,
        spec_repo=spec_repo,
        drawing_store=store,
    )
    emb = result["embedments"]
    assert len(emb) == 2
    assert {e["list_instrument_tag"] for e in emb} == {"TAG-A", "TAG-B"}


@pytest.mark.asyncio
async def test_list_all_merges_drawing_entries_with_overlapping_peer_tags():
    service = InstrumentEmbedmentService()
    store = _FakeDrawingStoreOverlappingPeers()
    items = [
        SimpleNamespace(
            id=1,
            name="R1",
            page="1",
            position=1,
            extra={"instrument_tag": "TAG-A", "drawing_image_path": ""},
        ),
        SimpleNamespace(
            id=2,
            name="R2",
            page="1",
            position=2,
            extra={"instrument_tag": "TAG-C", "drawing_image_path": ""},
        ),
    ]
    spec_repo = _FakeSpecRepo(items=items)
    repo = _FakePipelineRepoForFlat({"P-1": 10})

    result = await service.list_all_embedments_flat_for_admin(
        repo=repo,
        spec_repo=spec_repo,
        drawing_store=store,
    )
    emb = result["embedments"]
    assert len(emb) == 3
    assert {e["list_instrument_tag"] for e in emb} == {"TAG-A", "TAG-B", "TAG-C"}


@pytest.mark.asyncio
async def test_list_all_no_duplicate_when_peer_only_tag_has_no_json_key():
    service = InstrumentEmbedmentService()
    store = _FakeDrawingStoreOnlyPrimaryTagResolves()
    items = [
        SimpleNamespace(
            id=1,
            name="R1",
            page="1",
            position=1,
            extra={"instrument_tag": "PG-1", "drawing_image_path": ""},
        ),
        SimpleNamespace(
            id=2,
            name="R2",
            page="1",
            position=2,
            extra={"instrument_tag": "PG-2", "drawing_image_path": ""},
        ),
    ]
    spec_repo = _FakeSpecRepo(items=items)
    repo = _FakePipelineRepoForFlat({"P-1": 10})

    result = await service.list_all_embedments_flat_for_admin(
        repo=repo,
        spec_repo=spec_repo,
        drawing_store=store,
    )
    emb = result["embedments"]
    assert len(emb) == 2
    assert {e["list_instrument_tag"] for e in emb} == {"PG-1", "PG-2"}


@pytest.mark.asyncio
async def test_list_all_resolve_uses_normalized_tag_for_strict_store():
    service = InstrumentEmbedmentService()
    store = _FakeDrawingStoreStrictKey()
    items = [
        SimpleNamespace(
            id=1,
            name="E1",
            page="1",
            position=1,
            extra={"instrument_tag": "PG\u20131", "drawing_image_path": ""},
        ),
    ]
    spec_repo = _FakeSpecRepo(items=items)
    repo = _FakePipelineRepoForFlat({"P-1": 10})

    result = await service.list_all_embedments_flat_for_admin(
        repo=repo,
        spec_repo=spec_repo,
        drawing_store=store,
    )
    emb = result["embedments"]
    assert len(emb) == 2
    assert {e["list_instrument_tag"] for e in emb} == {"PG-1", "PG-2"}


def test_resolve_embedment_crop_image_rejects_unsafe_path():
    service = InstrumentEmbedmentService()
    with pytest.raises(ValidationError):
        service.resolve_embedment_crop_image(
            relative_path="../outside.png",
            crop_output_dir="data/ocr/crop_page",
        )
