import pytest

from backend.app.domain.parsing.specification import spec_section_mapping_store as m


def test_resolve_table_4_2_unique():
    assert m.resolve_table_choice_to_section_ru(m.TABLE_SPEC_4_2, None) == "Арматура"
    assert m.resolve_table_choice_to_section_ru(m.TABLE_SPEC_4_2, "Арматура") == "Арматура"


def test_resolve_table_4_1_without_name_requires_section():
    with pytest.raises(ValueError, match="section_required"):
        m.resolve_table_choice_to_section_ru(m.TABLE_SPEC_4_1, None)


def test_resolve_table_4_1_legacy_explicit_section_without_item_name():
    assert m.resolve_table_choice_to_section_ru(m.TABLE_SPEC_4_1, "Трубы") == "Трубы"
    assert (
        m.resolve_table_choice_to_section_ru(m.TABLE_SPEC_4_1, "Соединительные детали")
        == "Соединительные детали"
    )


def test_resolve_table_4_1_infer_pipes_from_item_name():
    assert (
        m.resolve_table_choice_to_section_ru(m.TABLE_SPEC_4_1, None, item_name="Труба 20 ГОСТ")
        == "Трубы"
    )
    assert (
        m.resolve_table_choice_to_section_ru(m.TABLE_SPEC_4_1, None, item_name="трубы стальные")
        == "Трубы"
    )


def test_resolve_table_4_1_first_word_not_truba_is_connection():
    assert (
        m.resolve_table_choice_to_section_ru(m.TABLE_SPEC_4_1, None, item_name="Трубная заготовка")
        == "Соединительные детали"
    )


def test_resolve_table_4_1_infer_connection_parts():
    assert (
        m.resolve_table_choice_to_section_ru(m.TABLE_SPEC_4_1, None, item_name="Отвод 90°")
        == "Соединительные детали"
    )


def test_resolve_table_4_1_infer_overrides_contradictory_section():
    """При непустом наименовании явный section игнорируется — раздел только из имени."""
    assert (
        m.resolve_table_choice_to_section_ru(
            m.TABLE_SPEC_4_1, "Трубы", item_name="Отвод крутоизогнутый"
        )
        == "Соединительные детали"
    )


def test_resolve_table_4_3_without_name_requires_section():
    with pytest.raises(ValueError, match="section_required"):
        m.resolve_table_choice_to_section_ru(m.TABLE_SPEC_4_3, None)


def test_resolve_table_4_3_infer_supports_and_flanges():
    assert (
        m.resolve_table_choice_to_section_ru(m.TABLE_SPEC_4_3, None, item_name="Опора подвижная")
        == "Опоры"
    )
    assert (
        m.resolve_table_choice_to_section_ru(m.TABLE_SPEC_4_3, None, item_name="опоры скользящие")
        == "Опоры"
    )
    assert (
        m.resolve_table_choice_to_section_ru(m.TABLE_SPEC_4_3, None, item_name="Опорная конструкция")
        == "Фланцы"
    )
    assert (
        m.resolve_table_choice_to_section_ru(m.TABLE_SPEC_4_3, None, item_name="Фланец стальной")
        == "Фланцы"
    )


def test_table_to_sections_map_for_ui_hides_subchoices_for_4_1_and_4_3():
    mp = m.table_to_sections_map_for_ui()
    assert mp[m.TABLE_SPEC_4_1] == []
    assert mp[m.TABLE_SPEC_4_3] == []
    assert mp[m.TABLE_SPEC_4_2] == ["Арматура"]
    assert len(mp[m.TABLE_SPEC_4_4]) == 1


def test_resolve_invalid_table():
    with pytest.raises(ValueError, match="invalid_table"):
        m.resolve_table_choice_to_section_ru("Таблица 9.9", None)


def test_section_ru_label_to_spec_table():
    assert m.section_ru_label_to_spec_table("Трубы") == m.TABLE_SPEC_4_1
    assert m.section_ru_label_to_spec_table("Арматура") == m.TABLE_SPEC_4_2
