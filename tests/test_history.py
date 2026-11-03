import json

from grabber.history import HistoryEntry, HistoryStore


def make_entry(title="Video", **changes):
    data = dict(
        title=title, url="https://example.com/v", mode="video", max_height=None,
        playlist=False, folder="C:/downloads", finished_at="2026-11-02T10:00:00", file_count=1,
    )
    data.update(changes)
    return HistoryEntry(**data)


def test_no_file_means_empty_history(tmp_path):         # tmp_path: a temporary folder
    assert HistoryStore(tmp_path / "history.json").load() == []


def test_newest_entry_comes_first(tmp_path):
    store = HistoryStore(tmp_path / "history.json")
    store.add(make_entry("first"))
    store.add(make_entry("second"))
    assert [entry.title for entry in store.load()] == ["second", "first"]


def test_history_survives_a_restart(tmp_path):
    path = tmp_path / "history.json"
    HistoryStore(path).add(make_entry("kept"))
    assert HistoryStore(path).load()[0].title == "kept"    # a NEW store object reads the file


def test_files_saved_by_an_older_version_still_load(tmp_path):
    path = tmp_path / "history.json"
    old = [{"title": "Old", "url": "https://x", "mode": "video", "max_height": None,
            "playlist": False, "folder": "C:/x", "finished_at": "2026-10-01T10:00:00",
            "file_count": 1}]                                 # no "items", no "subtitles"...
    path.write_text(json.dumps(old), encoding="utf-8")
    entry = HistoryStore(path).load()[0]
    assert entry.title == "Old"
    assert entry.items is None                                # the default was used


def test_a_damaged_file_is_backed_up_and_ignored(tmp_path):
    path = tmp_path / "history.json"
    path.write_text("this is not json", encoding="utf-8")
    assert HistoryStore(path).load() == []
    assert path.with_suffix(".bak").exists()


def test_only_the_newest_entries_are_kept(tmp_path):
    store = HistoryStore(tmp_path / "history.json")
    store.MAX_ENTRIES = 3
    for number in range(5):
        store.add(make_entry(f"video {number}"))
    assert [entry.title for entry in store.load()] == ["video 4", "video 3", "video 2"]


def test_clear(tmp_path):
    store = HistoryStore(tmp_path / "history.json")
    store.add(make_entry())
    store.clear()
    assert store.load() == []