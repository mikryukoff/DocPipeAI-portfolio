from backend.app.domain.excel_parsing.excel_speca_armature_parser import (
    ExcelSpecaArmatureParser,
)


def test_speca_armature_parser_parses_example_row():
    raw = (
        "Арматура XX01-V41000, ЕМК №32, "
        "Задвижка шланговая / Pinch Valve DN50 PN10 Flanged "
        "(Корпус - A182 F51 / Шланг - SBRT)"
    )

    parsed = ExcelSpecaArmatureParser.try_parse(raw)

    assert parsed is not None
    assert parsed.source_prefix == "Арматура XX01-V41000"
    assert parsed.normalized_name == "Задвижка шланговая DN50 PN10"
    assert parsed.dn == "50"
    assert parsed.pn == "1,0 (10)"
    assert parsed.material_grade == "Корпус - A182 F51 / Шланг - SBRT"
    assert parsed.gost == "Q/JBGN02"


def test_speca_armature_parser_ignores_non_armature_rows():
    raw = "Труба по EN ISO 1127 DN114,3x3,2"
    assert ExcelSpecaArmatureParser.try_parse(raw) is None


def test_speca_armature_parser_without_registry_marker_keeps_full_description():
    raw = (
        "Арматура YY03-V90975, "
        "Кран шаровый DN 50 PN 1,0 Мпа, материал корпуса- CF8M, управление- рукоятка, с  КОФ."
    )

    parsed = ExcelSpecaArmatureParser.try_parse(raw)

    assert parsed is not None
    assert parsed.source_prefix == "Арматура YY03-V90975"
    assert parsed.normalized_name == "Кран шаровый DN 50 PN 1,0"
    assert parsed.dn == "50"
    assert parsed.pn == "1,0 (10)"


def test_speca_armature_parser_with_registry_marker_and_decimal_pn():
    raw = (
        "Арматура XX01-V41824, РНГС №64, "
        "Кран шаровый DN 80 PN 1,6 Мпа, материал корпуса- CF3M, управление- рукоятка, с  КОФ."
    )

    parsed = ExcelSpecaArmatureParser.try_parse(raw)

    assert parsed is not None
    assert parsed.source_prefix == "Арматура XX01-V41824"
    assert parsed.normalized_name == "Кран шаровый DN 80 PN 1,6"
    assert parsed.dn == "80"
    assert parsed.pn == "1,6 (16)"


def test_speca_armature_parser_rngs_without_comma_after_tag_not_split_on_pn_decimal():
    """РНГС №… сразу перед наименованием (без запятой после тега): не резать по PN 1,0."""
    raw = (
        "Арматура ZZ04-V25269, РНГС №84 Затвор дисковый межфланцевый  DN 200 PN 1,0 Мпа, "
        "материал корпуса- CF8M, управление- редуктор, с  КОФ"
    )
    parsed = ExcelSpecaArmatureParser.try_parse(raw)
    assert parsed is not None
    assert parsed.normalized_name != "0"
    assert "Затвор" in parsed.normalized_name
    assert parsed.dn == "200"


def test_speca_armature_parser_parse_note_decimal_pn_with_spaces():
    note = "РНГС №31 Клапан обратный DN 40 PN 1, 6 Мпа, материал корпуса- CF3M+F46, с КОФ"

    parsed = ExcelSpecaArmatureParser.try_parse_note(
        source_prefix="V41094",
        note_text=note,
    )

    assert parsed is not None
    assert parsed.source_prefix == "V41094"
    assert parsed.normalized_name == "Клапан обратный DN 40 PN 1,6"
    assert parsed.dn == "40"
    assert parsed.pn == "1,6 (16)"


def test_speca_armature_parser_parse_note_butterfly_like_audit_log():
    note = (
        "ЕМК №66 Затвор дисковый / Butterfly Valve DN150 PN10 Wafer "
        "(Корпус - А 890 CD3MN / Диск - А182 F51 / Седло - PTFE / Шток - А182 F51)'"
    )
    parsed = ExcelSpecaArmatureParser.try_parse_note(
        source_prefix="Арматура V56881",
        note_text=note,
    )
    assert parsed is not None
    assert parsed.dn == "150"
    assert parsed.pn == "1,0 (10)"
    assert "Затвор дисковый" in parsed.normalized_name
