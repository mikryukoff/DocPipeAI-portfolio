import os

import pytest

from backend.app.domain.parsing.support_gost_search_yandex import SupportGostSearch


@pytest.mark.integration
def test_support_gost_search_real_web_query():
    """
    Интеграционный тест с реальным интернет-поиском.
    Запускается только при RUN_REAL_SEARCH_TESTS=1.
    """
    if os.getenv("RUN_REAL_SEARCH_TESTS", "0") != "1":
        pytest.skip("Set RUN_REAL_SEARCH_TESTS=1 to run real web search test")
    if not os.getenv("YANDEX_FOLDER_ID") or not os.getenv("YANDEX_API_KEY"):
        pytest.skip("Set YANDEX_FOLDER_ID and YANDEX_API_KEY for Yandex Search API")

    service = SupportGostSearch(
        enabled=True,
        timeout_sec=45.0,
    )
    gost = service.find_gost("Опора хомутовая ОПХ2-150-60,3-09Г2С")
    assert gost.startswith("ГОСТ "), f"Unexpected GOST value: {gost!r}"
