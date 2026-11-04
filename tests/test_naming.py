import pytest

from grabber.naming import safe_folder_name


def test_forbidden_characters_are_replaced():
    assert safe_folder_name('My: "best" <songs>?') == "My_ _best_ _songs__"


def test_trailing_dots_and_spaces_are_removed():
    assert safe_folder_name("Name. . ") == "Name"


@pytest.mark.parametrize("bad", ["", "   ", "CON", "nul", None])
def test_unusable_names_use_the_fallback(bad):
    assert safe_folder_name(bad) == "Playlist"


def test_long_names_are_shortened():
    assert len(safe_folder_name("a" * 200)) == 80


def test_arabic_names_are_kept():
    assert safe_folder_name("دورة بايثون") == "دورة بايثون"