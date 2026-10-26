import pytest

from backend.app.shared.pipeline_number_format import (
    format_with_number_sign,
    normalize_pipeline_name,
    strip_leading_number_sign,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ЗВ.1", "№ЗВ.1"),
        ("№ЗВ.1", "№ЗВ.1"),
        ("№ №ЗВ.1", "№ЗВ.1"),
        ("№№ЗВ.1", "№ЗВ.1"),
        ("  №  ЗВ.1  ", "№ЗВ.1"),
        ("41079", "№41079"),
        ("№41079", "№41079"),
        ("", ""),
    ],
)
def test_format_with_number_sign(raw: str, expected: str) -> None:
    assert format_with_number_sign(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("№ЗВ.1", "ЗВ.1"),
        ("№№ЗВ.1", "ЗВ.1"),
        ("  №  ЗВ.1", "ЗВ.1"),
        ("ЗВ.1", "ЗВ.1"),
        ("", ""),
    ],
)
def test_strip_leading_number_sign(raw: str, expected: str) -> None:
    assert strip_leading_number_sign(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ЗВ.1", "ЗВ.1"),
        ("№ЗВ.1", "ЗВ.1"),
        ("№ №ЗВ.1", "ЗВ.1"),
        ("XX01-41041-PSL-100", "XX01-41041-PSL-100"),
        ("", ""),
    ],
)
def test_normalize_pipeline_name(raw: str, expected: str) -> None:
    assert normalize_pipeline_name(raw) == expected
