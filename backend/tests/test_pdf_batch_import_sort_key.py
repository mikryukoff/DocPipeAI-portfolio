from pathlib import Path

from backend.app.application.imports.pdf_batch_import_service import PdfBatchImportService


def test_first_numeric_prefix_int_matches_sort_main_number():
    assert PdfBatchImportService._first_numeric_prefix_int(Path("148.pdf")) == 148
    assert PdfBatchImportService._first_numeric_prefix_int(Path("271.2.pdf")) == 271
    assert PdfBatchImportService._first_numeric_prefix_int(Path("abc.pdf")) is None


def test_numeric_group_key_distinguishes_dot_hierarchy():
    assert PdfBatchImportService._numeric_group_key(Path("1.1.pdf")) == (1,)
    assert PdfBatchImportService._numeric_group_key(Path("1.1.1.pdf")) == (1, 1)
    assert PdfBatchImportService._numeric_group_key(Path("222.1.pdf")) == (222,)
    assert PdfBatchImportService._numeric_group_key(Path("222,2.pdf")) == (222,)
    assert PdfBatchImportService._numeric_group_key(Path("1-2.pdf")) == (1,)


def test_pdf_sort_key_orders_dot_hierarchy():
    files = [Path("1.1.1.pdf"), Path("1.1.pdf"), Path("1.2.pdf")]
    sorted_files = sorted(files, key=PdfBatchImportService._sort_key)
    assert [p.name for p in sorted_files] == ["1.1.pdf", "1.1.1.pdf", "1.2.pdf"]


def test_pdf_sort_key_supports_dot_comma_space_and_dash():
    files = [
        Path("2-1.pdf"),
        Path("1.3.pdf"),
        Path("1,1.pdf"),
        Path("1 4.pdf"),
        Path("1-2.pdf"),
        Path("1_5.pdf"),
    ]

    sorted_files = sorted(files, key=PdfBatchImportService._sort_key)
    assert [p.name for p in sorted_files] == [
        "1,1.pdf",
        "1-2.pdf",
        "1.3.pdf",
        "1 4.pdf",
        "1_5.pdf",
        "2-1.pdf",
    ]


def test_pdf_sort_key_keeps_non_numeric_names_last():
    files = [
        Path("abc.pdf"),
        Path("10.pdf"),
        Path("2,1.pdf"),
        Path("1.pdf"),
    ]

    sorted_files = sorted(files, key=PdfBatchImportService._sort_key)
    assert [p.name for p in sorted_files] == [
        "1.pdf",
        "2,1.pdf",
        "10.pdf",
        "abc.pdf",
    ]
