import pytest

from grabber.errors import (
    DownloadFailedError, FFmpegMissingError, GrabberError, InvalidUrlError,
    VerificationRequiredError,
)
from ui.i18n import error_text, set_language
from ui.translations import TRANSLATIONS


@pytest.fixture(autouse=True)
def back_to_english():
    yield                                   # the test runs here
    set_language("en")                      # then reset, so tests never affect each other


def test_an_error_with_a_code_is_translated():
    error = InvalidUrlError("plain message", url="hello")
    set_language("en")
    english = error_text(error)
    set_language("ar")
    arabic = error_text(error)
    assert "hello" in english and "hello" in arabic
    assert english != arabic                # two different languages


def test_the_details_fill_the_holes():
    set_language("en")
    assert "boom" in error_text(DownloadFailedError("boom"))   # "reason" is always there


def test_an_unknown_code_falls_back_to_the_plain_message():
    assert error_text(GrabberError("plain", code="no_such_code")) == "plain"


def test_a_missing_detail_falls_back_to_the_plain_message():
    assert error_text(InvalidUrlError("message only")) == "message only"   # no url= given


def test_ordinary_exceptions_work_too():
    assert error_text(ValueError("oops")) == "oops"


@pytest.mark.parametrize("code", [
    "invalid_url", "unsupported_url", "bot_check", "cookie_problem", "unavailable",
    "failed", "file_problem", "ffmpeg_missing", "unexpected", "tools_failed",
])
def test_every_error_code_has_a_translation_in_both_languages(code):
    assert f"err_{code}" in TRANSLATIONS["en"]
    assert f"err_{code}" in TRANSLATIONS["ar"]


def test_default_codes():
    assert VerificationRequiredError("x").code == "bot_check"
    assert FFmpegMissingError("x").code == "ffmpeg_missing"