import threading
import time
from pathlib import Path

from grabber.errors import DownloadFailedError, UserCancelledError
from grabber.jobs import DownloadQueue, JobState
from grabber.models import DownloadRequest, DownloadResult


def wait_until(condition, timeout=3.0):
    """Threads need a moment: check again and again until the condition is true."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


class FakeDownloader:
    """Stands in for the real Downloader: no internet, no yt-dlp.
    A 'download' just waits, and obeys the cancel flag like the real one."""

    def __init__(self, duration=0.2):
        self.duration = duration
        self.durations = {}               # url -> its own duration
        self.fail_urls = set()
        self.started = []
        self.running = 0
        self.max_running = 0              # the most downloads that ever ran at the same time
        self._lock = threading.Lock()

    def download(self, request, on_progress=None, cancel_event=None):
        with self._lock:
            self.running += 1
            self.max_running = max(self.max_running, self.running)
            self.started.append(request.url)
        try:
            end = time.monotonic() + self.durations.get(request.url, self.duration)
            while time.monotonic() < end:
                if cancel_event is not None and cancel_event.is_set():
                    raise UserCancelledError("cancelled")
                time.sleep(0.01)
            if request.url in self.fail_urls:
                raise DownloadFailedError("boom")
            return DownloadResult(files=())
        finally:
            with self._lock:
                self.running -= 1


class BrokenDownloader:
    def download(self, request, on_progress=None, cancel_event=None):
        raise RuntimeError("bug!")


def make_request(url="https://example.com/a"):
    return DownloadRequest(url=url, folder=Path("downloads"))


def all_done(jobs):
    return all(job.state is JobState.DONE for job in jobs)


def test_jobs_run_one_at_a_time_by_default():
    fake = FakeDownloader(duration=0.1)
    queue = DownloadQueue(fake)
    jobs = [queue.add(make_request(f"u{i}"), f"job {i}") for i in range(3)]
    assert wait_until(lambda: all_done(jobs))
    assert fake.max_running == 1


def test_the_parallel_limit_is_respected():
    fake = FakeDownloader(duration=0.15)
    queue = DownloadQueue(fake)
    queue.set_max_parallel(2)
    jobs = [queue.add(make_request(f"u{i}"), f"job {i}") for i in range(5)]
    assert wait_until(lambda: all_done(jobs))
    assert fake.max_running == 2              # two at once, never three


def test_raising_the_limit_starts_waiting_jobs():
    fake = FakeDownloader(duration=2.0)
    queue = DownloadQueue(fake)
    first = queue.add(make_request("a"), "a")
    second = queue.add(make_request("b"), "b")
    assert wait_until(lambda: first.state is JobState.DOWNLOADING)
    assert second.state is JobState.PENDING   # no free slot yet

    queue.set_max_parallel(2)
    assert wait_until(lambda: second.state is JobState.DOWNLOADING)

    queue.cancel(first)                       # don't leave 2-second jobs running
    queue.cancel(second)


def test_cancelling_a_waiting_job_means_it_never_starts():
    fake = FakeDownloader(duration=0.5)
    queue = DownloadQueue(fake)
    running = queue.add(make_request("a"), "a")
    waiting = queue.add(make_request("b"), "b")
    assert wait_until(lambda: running.state is JobState.DOWNLOADING)

    queue.cancel(waiting)
    assert waiting.state is JobState.CANCELLED
    assert wait_until(lambda: running.state is JobState.DONE)
    assert "b" not in fake.started


def test_cancelling_a_running_job():
    queue = DownloadQueue(FakeDownloader(duration=2.0))
    job = queue.add(make_request(), "job")
    assert wait_until(lambda: job.state is JobState.DOWNLOADING)
    queue.cancel(job)
    assert wait_until(lambda: job.state is JobState.CANCELLED)


def test_pause_then_resume():
    queue = DownloadQueue(FakeDownloader(duration=1.0))
    job = queue.add(make_request(), "job")
    assert wait_until(lambda: job.state is JobState.DOWNLOADING)

    queue.pause(job)
    assert wait_until(lambda: job.state is JobState.PAUSED)

    queue.resume(job)
    assert wait_until(lambda: job.state is JobState.DONE, timeout=5)


def test_a_paused_job_frees_its_slot():
    fake = FakeDownloader()
    fake.durations = {"slow": 3.0, "quick": 0.1}
    queue = DownloadQueue(fake)
    slow = queue.add(make_request("slow"), "slow")
    quick = queue.add(make_request("quick"), "quick")
    assert wait_until(lambda: slow.state is JobState.DOWNLOADING)

    queue.pause(slow)                                       # the only slot becomes free...
    assert wait_until(lambda: quick.state is JobState.DONE)  # ...so the waiting job runs
    assert slow.state is JobState.PAUSED

    queue.cancel(slow)


def test_a_failure_is_recorded_and_the_queue_goes_on():
    fake = FakeDownloader(duration=0.05)
    fake.fail_urls = {"bad"}
    queue = DownloadQueue(fake)
    bad = queue.add(make_request("bad"), "bad")
    good = queue.add(make_request("good"), "good")

    assert wait_until(lambda: good.state is JobState.DONE)
    assert bad.state is JobState.FAILED
    assert bad.message == "boom"


def test_an_unexpected_bug_marks_the_job_as_failed():
    queue = DownloadQueue(BrokenDownloader())
    job = queue.add(make_request(), "job")
    assert wait_until(lambda: job.state is JobState.FAILED)
    assert "bug!" in job.message


def test_every_change_is_reported():
    seen = []
    queue = DownloadQueue(FakeDownloader(duration=0.05), on_change=lambda job: seen.append(job.state))
    job = queue.add(make_request(), "job")
    assert wait_until(lambda: job.state is JobState.DONE)
    assert wait_until(lambda: seen and seen[-1] is JobState.DONE)
    assert JobState.DOWNLOADING in seen


def test_clear_finished_keeps_the_unfinished_jobs():
    fake = FakeDownloader(duration=0.05)
    fake.durations = {"slow": 3.0}
    queue = DownloadQueue(fake)
    quick = queue.add(make_request("quick"), "quick")
    slow = queue.add(make_request("slow"), "slow")
    assert wait_until(lambda: quick.state is JobState.DONE)
    assert wait_until(lambda: slow.state is JobState.DOWNLOADING)

    queue.clear_finished()
    assert queue.jobs == [slow]

    queue.cancel(slow)