from ui.formatting import format_duration, format_eta, format_size, format_speed


def test_duration():
    assert format_duration(83) == "1:23"
    assert format_duration(3725) == "1:02:05"
    assert format_duration(0) == "0:00"


def test_eta():
    assert format_eta(65) == "1:05"


def test_size_uses_a_sensible_unit():
    assert format_size(500) == "500 B"
    assert format_size(1536) == "1.5 KB"
    assert format_size(125_000_000) == "119.2 MB"


def test_speed():
    assert format_speed(2 * 1024 * 1024) == "2.0 MB/s"
    assert format_speed(640 * 1024) == "640 KB/s"