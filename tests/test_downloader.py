import pytest

from grabber.downloader import _clip_label, _translate_error, validate_url
from grabber.errors import (
    CookieProblemError,
    DownloadFailedError,
    InvalidUrlError,
    MediaUnavailableError,
    VerificationRequiredError,
)


@pytest.mark.parametrize("message, expected", [
    ("ERROR: [youtube] abc: Sign in to confirm you’re not a bot. Use --cookies-from-browser",
     VerificationRequiredError),
    ("ERROR: Could not copy Chrome cookie database. See https://github.com/yt-dlp/yt-dlp/issues/7271",
     CookieProblemError),
    ("ERROR: Failed to decrypt with DPAPI. See https://github.com/yt-dlp/yt-dlp/issues/10927",
     CookieProblemError),
    ("ERROR: Unsupported URL: https://example.com/page", InvalidUrlError),
    ("ERROR: [youtube] abc: Video unavailable", MediaUnavailableError),
    ("ERROR: [youtube] abc: Private video. Sign in if you've been granted access",
     MediaUnavailableError),
    ("ERROR: something nobody has seen before", DownloadFailedError),
])
def test_yt_dlp_messages_become_our_own_errors(message, expected):
    assert isinstance(_translate_error(Exception(message)), expected)


def test_unknown_errors_keep_the_original_reason():
    error = _translate_error(Exception("ERROR: something odd"))
    assert "something odd" in str(error)


def test_validate_url_cleans_good_links():
    assert validate_url("  https://example.com/video  ") == "https://example.com/video"


@pytest.mark.parametrize("bad", ["", "hello", "ftp://example.com/x", "https://", None])
def test_validate_url_rejects_bad_links(bad):
    with pytest.raises(InvalidUrlError):
        validate_url(bad)


def test_clip_label_goes_into_the_file_name():
    assert _clip_label(65, 130) == "01m05s-02m10s"
    assert _clip_label(5, None) == "00m05s-end"