"""Восстановление строчной латиницы → кириллица в описаниях закладных (не теги)."""

from backend.app.domain.parsing.drawing_tag_normalize import latin_homoglyph_lowercase_to_cyrillic


def test_latin_lower_homoglyph_reverse_basic():
    assert latin_homoglyph_lowercase_to_cyrillic("hp-100") == "нр-100"
    assert latin_homoglyph_lowercase_to_cyrillic("G1/2") == "G1/2"


def test_restore_multilingual_example():
    s = "Бoбышka c bhutpehheй peзьбoй G1/2 L=50mm"
    got = latin_homoglyph_lowercase_to_cyrillic(s)
    # Полная механическая замена строчной латиницы из набора омоглифов
    assert got == "Бобышка с внутренней резьбой G1/2 L=50мм"
