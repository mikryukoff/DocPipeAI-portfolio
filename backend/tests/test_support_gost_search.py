from pathlib import Path

import pytest

from backend.app.domain.parsing.support_gost_mapping_store import SupportGostMappingStore
from backend.app.domain.parsing.support_gost_search_yandex import SupportGostSearch
import backend.app.domain.parsing.support_gost_search_yandex as support_gost_search_module


def test_extract_gost_from_text():
    text = "Для опоры применяется стандарт гост 14911-82 и доп. требования."
    value = SupportGostSearch._extract_gost(text)
    assert value == "ГОСТ 14911-82"


def test_extract_gost_restores_dash_for_compact_number():
    text = "На странице указано: ГОСТ 1491182 для опор."
    value = SupportGostSearch._extract_gost(text)
    assert value == "ГОСТ 14911-82"


def test_rejects_too_generic_gost_candidate():
    assert SupportGostSearch._is_valid_gost_candidate("ГОСТ Р 12.0") is False
    assert SupportGostSearch._is_valid_gost_candidate("ГОСТ 14911-82") is True


def test_family_key_same_for_ops_o_with_different_sizes():
    key1 = SupportGostSearch._build_family_key("Опора-стойка ОПС-О-60,3-1326-09Г2С")
    key2 = SupportGostSearch._build_family_key("Опора-стойка ОПС-О-114,3-335-09Г2С")
    assert key1 == "ОПОРА СТОЙКА ОПС О"
    assert key2 == "ОПОРА СТОЙКА ОПС О"


def test_mapping_store_persists_values_between_instances(tmp_path: Path):
    mapping_path = tmp_path / "support_gost_mapping.json"
    store_a = SupportGostMappingStore(path=mapping_path)
    store_a.set_exact("Опора хомутовая ОПХ2-150-60,3-09Г2С", "ГОСТ 14911-82")
    store_a.set_family("ОПОРА ХОМУТОВАЯ ОПХ2", "ГОСТ 14911-82")

    service = SupportGostSearch(enabled=True, mapping_store=SupportGostMappingStore(path=mapping_path))
    assert service.find_gost("Опора хомутовая ОПХ2-150-60,3-09Г2С") == "ГОСТ 14911-82"
    assert service.find_gost("Опора хомутовая ОПХ2-150-76,1-09Г2С") == "ГОСТ 14911-82"


def test_mapping_store_ignores_legacy_not_found_keys(tmp_path: Path):
    mapping_path = tmp_path / "support_gost_mapping.json"
    mapping_path.write_text(
        """{
  "exact": {"Опора X": "ГОСТ 14911-82"},
  "family": {"ОПОРА X": "ГОСТ 14911-82"},
  "not_found_exact": ["legacy"],
  "not_found_family": ["legacy"]
}""",
        encoding="utf-8",
    )
    store = SupportGostMappingStore(path=mapping_path)
    assert store.get_exact("Опора X") == "ГОСТ 14911-82"
    assert store.get_family("ОПОРА X") == "ГОСТ 14911-82"


def test_mapping_store_relaxed_lookup_avoids_api_call(monkeypatch, tmp_path: Path):
    mapping_path = tmp_path / "support_gost_mapping.json"
    store = SupportGostMappingStore(path=mapping_path)
    store.set_exact("Опора хомутовая ОПХ 2-150-88,9-09 Г2С", "ГОСТ 14911-82")
    service = SupportGostSearch(enabled=True, mapping_store=store)

    monkeypatch.setattr(
        support_gost_search_module,
        "_run_coro_sync",
        lambda coro: (coro.close(), (_ for _ in ()).throw(AssertionError("API should not be called")))[1],
    )
    value = service.find_gost("Опора хомутовая ОПХ2-150-88,9-09Г2С")
    assert value == "ГОСТ 14911-82"


def test_score_gost_context_prefers_relevant_context():
    service = SupportGostSearch(enabled=True)
    model_tokens = service._extract_model_tokens("Опора хомутовая ОПХ2-150-60,3-09Г2С")
    relevant = service._score_gost_context(
        context="Опора хомутовая ОПХ2-150-60,3-09Г2С соответствует ГОСТ 14911-82.",
        model_tokens=model_tokens,
    )
    junk = service._score_gost_context(
        context="ГОСТ 12.0 общий стандарт без модели опоры.",
        model_tokens=model_tokens,
    )
    assert relevant > junk


def test_find_gost_uses_yandex_payload_and_updates_cache(monkeypatch, tmp_path: Path):
    service = SupportGostSearch(
        enabled=True,
        mapping_store=SupportGostMappingStore(path=tmp_path / "support_gost_mapping.json"),
    )

    monkeypatch.setattr(
        support_gost_search_module,
        "_run_coro_sync",
        lambda coro: (coro.close(), {"gost": "ГОСТ 14911-82", "source": "yandex_search_api"})[1],
    )

    value = service.find_gost("Опора хомутовая ОПХ2-150-60,3-09Г2С")
    assert value == "ГОСТ 14911-82"
    assert service.find_gost("Опора хомутовая ОПХ2-150-60,3-09Г2С") == "ГОСТ 14911-82"


def test_find_gost_returns_empty_when_payload_missing(monkeypatch, tmp_path: Path):
    service = SupportGostSearch(
        enabled=True,
        mapping_store=SupportGostMappingStore(path=tmp_path / "support_gost_mapping.json"),
    )
    monkeypatch.setattr(support_gost_search_module, "_run_coro_sync", lambda coro: (coro.close(), None)[1])
    assert service.find_gost("Опора хомутовая ОПХ2-150-60,3-09Г2С") == ""


@pytest.mark.asyncio
async def test_search_gost_returns_result_when_db_save_fails(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("YANDEX_FOLDER_ID", "folder")
    monkeypatch.setenv("YANDEX_API_KEY", "key")
    monkeypatch.setattr(
        support_gost_search_module,
        "SupportGostMappingStore",
        lambda: SupportGostMappingStore(path=tmp_path / "support_gost_mapping.json"),
    )

    class _Doc:
        title = "Опора хомутовая ОПХ2 ГОСТ 14911-82"
        passages = ("ГОСТ 14911-82 для опор",)

    class _Resp:
        docs = [_Doc()]

    class _Web:
        async def run(self, **kwargs):
            _ = kwargs
            return _Resp()

    class _SearchAPI:
        def web(self, **kwargs):
            _ = kwargs
            return _Web()

    class _SDK:
        def __init__(self, **kwargs):
            _ = kwargs
            self.search_api = _SearchAPI()

    class _SessionCtx:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            _ = (exc_type, exc, tb)
            return False

    async def _fail_save(**kwargs):
        _ = kwargs
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(support_gost_search_module, "AsyncAIStudio", _SDK)
    monkeypatch.setattr(support_gost_search_module, "AsyncSessionLocal", lambda: _SessionCtx())
    monkeypatch.setattr(support_gost_search_module, "_save_gost_to_db", _fail_save)

    result = await support_gost_search_module.search_gost("Опора хомутовая ОПХ2-150-60,3-09Г2С")
    assert result is not None
    assert result["gost"] == "ГОСТ 14911-82"
    assert result["updated_rows"] == 0
