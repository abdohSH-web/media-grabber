import re

from ui.translations import TRANSLATIONS


def holes(text):
    """The {names} a text expects: 'Item {current}/{total}' -> {'current', 'total'}"""
    return set(re.findall(r"{(\w+)}", text))


def test_both_languages_have_exactly_the_same_keys():
    assert set(TRANSLATIONS["en"]) == set(TRANSLATIONS["ar"])


def test_no_text_is_empty():
    for language, texts in TRANSLATIONS.items():
        for key, text in texts.items():
            assert text.strip(), f"{language}/{key} is empty"


def test_every_text_has_the_same_holes_in_every_language():
    # A text that expects {count} must be given {count} in Arabic too, or the app would crash
    for key, english in TRANSLATIONS["en"].items():
        assert holes(english) == holes(TRANSLATIONS["ar"][key]), key