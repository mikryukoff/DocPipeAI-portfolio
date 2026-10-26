import json
from pathlib import Path

import pytest

from backend.app.domain.parsing.armature_gost_store import ArmatureGostStore


@pytest.fixture
def sample_config(tmp_path: Path) -> Path:
    p = tmp_path / "armature_gost.json"
    p.write_text(
        json.dumps(
            {
                "Кран шаровой": "ТУ-MONO",
                "Клапан обратный": "ТУ-CLAPAN",
                "Кран шаровой / Ball Valve": "ISO-BI",
                "Задвижка шланговая / Pinch Valve": "Q-BI",
                "Сегментный шаровый кран / Segmented ball valve": "IEC-BI",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return p


def test_russian_only_exact_mono(sample_config: Path):
    s = ArmatureGostStore(sample_config)
    g, dr = s.resolve(russian_base="Кран шаровой", bilingual_head="Кран шаровой")
    assert g == "ТУ-MONO"
    assert dr == "Кран шаровой"


def test_russian_only_word_match_mono(sample_config: Path):
    s = ArmatureGostStore(sample_config)
    g, dr = s.resolve(russian_base="Кран шаровой фланцевый", bilingual_head="Кран шаровой фланцевый")
    assert g == "ТУ-MONO"
    assert dr == "Кран шаровой фланцевый"


def test_russian_only_word_order_independent(sample_config: Path):
    s = ArmatureGostStore(sample_config)
    g, _ = s.resolve(russian_base="Обратный клапан", bilingual_head="Обратный клапан")
    assert g == "ТУ-CLAPAN"


def test_russian_only_then_bilingual_russian_part(sample_config: Path):
    s = ArmatureGostStore(sample_config)
    g, dr = s.resolve(
        russian_base="Сегментный шаровый кран",
        bilingual_head="Сегментный шаровый кран",
    )
    assert g == "IEC-BI"
    assert dr == "Сегментный шаровый кран"


def test_bilingual_incoming_only_bi_keys(sample_config: Path):
    s = ArmatureGostStore(sample_config)
    g, dr = s.resolve(
        russian_base="Кран",
        bilingual_head="Кран шаровой / Ball Valve",
    )
    assert g == "ISO-BI"
    assert dr == "Кран"


def test_bilingual_incoming_does_not_use_mono(sample_config: Path):
    s = ArmatureGostStore(sample_config)
    g, _ = s.resolve(
        russian_base="Дроссель",
        bilingual_head="Дроссель / Throttle",
    )
    assert g == ""


def test_bilingual_word_match(sample_config: Path):
    s = ArmatureGostStore(sample_config)
    g, _ = s.resolve(
        russian_base="Задвижка",
        bilingual_head="Задвижка шланговая / Pinch Valve flanged",
    )
    assert g == "Q-BI"
