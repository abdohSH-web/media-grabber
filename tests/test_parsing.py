import pytest

from ui.parsing import parse_clip, parse_languages, parse_time


def test_parse_time_understands_seconds_minutes_and_hours():
    assert parse_time("90") == 90
    assert parse_time("1:30") == 90
    assert parse_time("1:02:03") == 3723


# parametrize: the SAME test runs once for each bad value
@pytest.mark.parametrize("bad", ["", "abc", "1:2:3:4", "-5", "nan", "inf", "1::2"])
def test_parse_time_rejects_garbage(bad):
    with pytest.raises(ValueError):           # we EXPECT an error here
        parse_time(bad)


def test_clip_between_two_times():
    assert parse_clip("0:05", "0:12") == (5, 12)


def test_clip_of_the_whole_video_means_no_clip():
    assert parse_clip("", "") == (None, None)


def test_clip_without_an_end_goes_to_the_end():
    assert parse_clip("0:10", "") == (10, None)


def test_an_end_past_the_video_means_until_the_end():
    assert parse_clip("0:10", "5:00", duration=120) == (10, None)


def test_clip_must_start_inside_the_video():
    with pytest.raises(ValueError):
        parse_clip("3:00", "", duration=120)


def test_clip_end_must_be_after_start():
    with pytest.raises(ValueError):
        parse_clip("0:20", "0:10")


def test_languages_are_split_and_deduplicated():
    assert parse_languages("en, ar") == ("en", "ar")
    assert parse_languages("en,en") == ("en",)
    assert parse_languages("pt-BR") == ("pt-BR",)
    assert parse_languages("") == ()


@pytest.mark.parametrize("bad", ["english", "e", "en_US", "123"])
def test_languages_reject_things_that_are_not_codes(bad):
    with pytest.raises(ValueError):
        parse_languages(bad)