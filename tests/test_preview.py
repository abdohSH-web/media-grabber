from grabber.downloader import _pick_preview


def fmt(height, vcodec="avc1", acodec="mp4a", protocol="https", url=None):
    return {"height": height, "vcodec": vcodec, "acodec": acodec,
            "protocol": protocol, "url": url or f"https://x/{height}"}


def test_picks_the_biggest_picture_up_to_480p():
    info = {"formats": [fmt(144), fmt(360), fmt(720)]}
    assert _pick_preview(info) == "https://x/360"


def test_video_only_and_audio_only_formats_are_ignored():
    info = {"formats": [fmt(360, acodec="none"), fmt(None, vcodec="none")]}
    assert _pick_preview(info) == ""


def test_when_everything_is_big_the_smallest_is_used():
    info = {"formats": [fmt(1080), fmt(720)]}
    assert _pick_preview(info) == "https://x/720"


def test_formats_without_a_link_or_with_odd_protocols_are_ignored():
    info = {"formats": [
        {"height": 360, "vcodec": "avc1", "acodec": "mp4a", "protocol": "https"},          # no url
        fmt(240, protocol="http_dash_segments"),                                            # not playable
    ]}
    assert _pick_preview(info) == ""


def test_no_formats_at_all():
    assert _pick_preview({}) == ""