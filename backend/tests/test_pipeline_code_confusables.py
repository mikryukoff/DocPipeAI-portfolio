import re

from backend.app.shared.pipeline_code_confusables import normalize_pipeline_code_confusable_o_to_zero


def test_normalize_o_cyrillic_latin_to_zero_in_body_keeps_suffix():
    raw = "ZZ04-25276-LFA-80-E010H4CO3"
    assert normalize_pipeline_code_confusable_o_to_zero(raw) == "ZZ04-25276-LFA-80-E010H4C03"


def test_normalize_cyrillic_capital_o_in_body():
    raw = "ZZ04-25276-LFA-80-E010H4CО3"  # О = U+041E
    assert normalize_pipeline_code_confusable_o_to_zero(raw) == "ZZ04-25276-LFA-80-E010H4C03"


def test_normalize_does_not_touch_two_letter_suffix():
    raw = "ZZ04-25276-LFA-80-E010H4CO3-IP"
    assert normalize_pipeline_code_confusable_o_to_zero(raw) == "ZZ04-25276-LFA-80-E010H4C03-IP"


def test_normalize_ie_suffix():
    raw = "XX01-41011-PSA-100-E010H2A0O-IE"  # typo O before -IE
    assert normalize_pipeline_code_confusable_o_to_zero(raw) == "XX01-41011-PSA-100-E010H2A00-IE"


def test_normalize_cyrillic_e_in_ie_suffix():
    raw = "VV06-21053-CPS-65-E010H4CO3-IЕ"  # Latin I + Cyrillic Е U+0415
    assert normalize_pipeline_code_confusable_o_to_zero(raw) == "VV06-21053-CPS-65-E010H4C03-IE"


def test_normalize_greek_omicron_in_body():
    raw = "ZZ04-25276-LFA-80-E010H4C\u039f3-IP"  # Greek capital omicron
    assert normalize_pipeline_code_confusable_o_to_zero(raw) == "ZZ04-25276-LFA-80-E010H4C03-IP"


def test_excel_like_line_cyrillic_C_with_latin_o_in_co3():
    """Как в Excel: «С» кириллица U+0421 в CO3, O латиница — в БД C03."""
    raw = "VV06-21053-CPS-65-E010H4" + "\u0421" + "O3-IE"
    assert normalize_pipeline_code_confusable_o_to_zero(raw) == "VV06-21053-CPS-65-E010H4C03-IE"


def test_extract_tests_line_parenthesis_like_user():
    tests_line_re = re.compile(r"линия\s*([^(,\n\r]+)", re.IGNORECASE)
    row = "линия VV06-21053-CPS-65-E010H4CO3-IE (№124)"
    m = tests_line_re.search(row)
    assert m
    raw = m.group(1).strip().rstrip(".").strip()
    assert normalize_pipeline_code_confusable_o_to_zero(raw) == "VV06-21053-CPS-65-E010H4C03-IE"
