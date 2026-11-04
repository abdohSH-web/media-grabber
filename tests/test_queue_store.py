import json
from pathlib import Path

from grabber.jobs import DownloadJob, JobState
from grabber.models import DownloadRequest, Mode
from grabber.queue_store import QueueStore, request_from_dict, request_to_dict


def make_request(**changes):
    return DownloadRequest(url="https://example.com/v", folder=Path("downloads"), **changes)


def test_a_request_survives_the_round_trip():
    request = make_request(
        mode=Mode.AUDIO, max_height=720, playlist=True, items=(1, 3),
        subtitles=("en", "ar"), auto_subtitles=False, clip_start=5.0, clip_end=12.0, name_prefix="03 - ",
    )
    assert request_from_dict(request_to_dict(request)) == request


def test_only_unfinished_jobs_are_saved(tmp_path):
    jobs = []
    for state in JobState:                       # one job in EVERY state
        job = DownloadJob(make_request(), f"job {state.value}")
        job.state = state
        jobs.append(job)

    store = QueueStore(tmp_path / "queue.json")
    store.save(jobs)

    titles = [title for _, title, _ in store.load()]
    assert titles == ["job pending", "job downloading", "job paused"]


def test_a_file_from_an_older_version_loads(tmp_path):
    path = tmp_path / "queue.json"
    old = [{"title": "Old", "request": {"url": "https://x", "folder": "downloads"}}]
    path.write_text(json.dumps(old), encoding="utf-8")
    (request, title, item_count), = QueueStore(path).load()
    assert (title, item_count, request.subtitles) == ("Old", 1, ())


def test_one_damaged_entry_does_not_lose_the_others(tmp_path):
    path = tmp_path / "queue.json"
    entries = [
        {"title": "broken"},                                            # no "request"
        {"title": "good", "request": {"url": "https://x", "folder": "d"}},
    ]
    path.write_text(json.dumps(entries), encoding="utf-8")
    assert [title for _, title, _ in QueueStore(path).load()] == ["good"]


def test_a_damaged_file_is_backed_up_and_ignored(tmp_path):
    path = tmp_path / "queue.json"
    path.write_text("nope", encoding="utf-8")
    assert QueueStore(path).load() == []
    assert path.with_suffix(".bak").exists()