import os
import time
from pathlib import Path

import pytest

from grabber.downloader import (
    Downloader, _entry_url, _existed_before, _translate_error, validate_url,
)
from grabber.models import DownloadRequest
from grabber.downloader import _translate_error, validate_url
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


def test_file_name_is_the_title_and_quality_only(tmp_path):
    # Even for a clip: no id, no clip range in the name
    request = DownloadRequest(url="https://example.com/v", folder=tmp_path, clip_start=5.0, clip_end=12.0)
    options = Downloader()._build_options(request, hook=lambda d: None)
    assert options["outtmpl"].endswith("%(title)s%(height& [{}p]|)s.%(ext)s")


def test_playlist_videos_get_their_number_in_front(tmp_path):
    request = DownloadRequest(url="https://example.com/v", folder=tmp_path, name_prefix="03 - ")
    options = Downloader()._build_options(request, hook=lambda d: None)
    assert options["outtmpl"].endswith("03 - %(title)s%(height& [{}p]|)s.%(ext)s")


def test_a_percent_sign_in_the_prefix_is_doubled(tmp_path):
    request = DownloadRequest(url="https://example.com/v", folder=tmp_path, name_prefix="100% - ")
    options = Downloader()._build_options(request, hook=lambda d: None)
    assert "100%% - " in options["outtmpl"]


def test_audio_files_have_no_quality_in_the_name(tmp_path):
    from grabber.models import Mode
    request = DownloadRequest(url="https://example.com/v", folder=tmp_path, mode=Mode.AUDIO)
    options = Downloader()._build_options(request, hook=lambda d: None)
    assert options["outtmpl"].endswith("%(title)s.%(ext)s")


def test_entry_url_prefers_the_full_link():
    link = "https://www.youtube.com/watch?v=abc"
    assert _entry_url({"url": link}) == link


def test_entry_url_builds_a_youtube_link_from_the_id():
    assert _entry_url({"id": "abc", "ie_key": "Youtube"}) == "https://www.youtube.com/watch?v=abc"


def test_entry_url_gives_up_cleanly():
    assert _entry_url({"id": "abc"}) == ""


def test_an_old_file_counts_as_existing_before_the_download(tmp_path):
    old = tmp_path / "old.mp4"
    old.write_text("x")
    os.utime(old, (1000, 1000))                       # a date long ago
    fresh = tmp_path / "fresh.mp4"
    fresh.write_text("x")

    started = time.time() - 5
    assert _existed_before(old, started) is True
    assert _existed_before(fresh, started) is False
    assert _existed_before(tmp_path / "missing.mp4", started) is False