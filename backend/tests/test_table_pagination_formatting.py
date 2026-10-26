from docx import Document
from docx.enum.table import WD_ROW_HEIGHT_RULE
from docx.oxml.ns import qn

from backend.app.infrastructure.exporters.passport_builders.table_formatting import format_table


def test_format_table_sets_cant_split_for_each_row():
    doc = Document()
    table = doc.add_table(rows=3, cols=2)
    table.rows[0].cells[0].text = "H"
    table.rows[1].cells[0].text = "D1"
    table.rows[2].cells[0].text = "D2"

    format_table(table)

    for row in table.rows:
        tr_pr = row._tr.get_or_add_trPr()
        assert tr_pr.find(qn("w:cantSplit")) is not None
        assert row.height_rule == WD_ROW_HEIGHT_RULE.AT_LEAST
        for cell in row.cells:
            tc_pr = cell._tc.get_or_add_tcPr()
            tc_mar = tc_pr.find(qn("w:tcMar"))
            assert tc_mar is not None
