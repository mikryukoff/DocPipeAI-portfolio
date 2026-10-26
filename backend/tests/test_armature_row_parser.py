from backend.app.domain.parsing.row_parsers.armature_parser import ArmatureRowParser


def test_armature_row_parser_extracts_corpus_material_grade():
    line = [
        "1",
        "Шаровой кран фланцевый DN25 PN40 с пневматическим приводом. "
        "Материал: корпус - А351 CF3M; шар - F316L; седло - PTFE;",
        "шт.",
        "1",
    ]
    p = ArmatureRowParser()
    arm = p.parse(line, "XX01-TEST")
    assert arm is not None
    assert arm.material_grade == "А351 CF3M"


def test_armature_row_parser_corpus_material_case_insensitive():
    line = [
        "2",
        "Кран. материал: КОРПУС - 12Х18Н10Т;",
        "шт.",
        "2",
    ]
    arm = ArmatureRowParser().parse(line, "X")
    assert arm is not None
    assert arm.material_grade == "12Х18Н10Т"
