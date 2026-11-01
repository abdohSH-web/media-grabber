import itertools
import threading
import time
import traceback
from enum import Enum

from .errors import GrabberError, UserCancelledError


class JobState(Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DownloadJob:
    """One item in the queue. Unlike our dataclasses it is MUTABLE:
    its state and progress change while it runs."""

    _ids = itertools.count(1)          # one counter shared by all jobs: 1, 2, 3...

    def __init__(self, request, title):
        self.id = next(DownloadJob._ids)
        self.request = request
        self.title = title
        self.state = JobState.PENDING
        self.progress = None           # the latest Progress object (or None)
        self.message = ""              # error text or a short note
        self.files = ()                # filled when the job is DONE
        self._stop_event = threading.Event()
        self._stop_reason = None       # "pause" or "cancel"


class DownloadQueue:
    """Runs jobs ONE AT A TIME in a background thread.
    It knows nothing about the UI: it just calls on_change(job) whenever
    a job changes, and whoever created the queue decides what to do with that."""

    def __init__(self, downloader, on_change=None):
        self.downloader = downloader
        self.on_change = on_change or (lambda job: None)
        self.jobs = []

        # A Condition = a lock + a way to put a thread to sleep until someone wakes it
        self._condition = threading.Condition()

        # daemon=True: this thread won't keep the program alive after the window closes
        worker = threading.Thread(target=self._run, daemon=True)
        worker.start()

    # ------------------------------------------------------------
    # Commands (called by the UI, from any thread)
    # ------------------------------------------------------------
    def add(self, request, title):
        job = DownloadJob(request, title)
        with self._condition:
            self.jobs.append(job)
            self._condition.notify()          # wake the worker: there is something to do
        self.on_change(job)
        return job

    def pause(self, job):
        with self._condition:
            if job.state is JobState.DOWNLOADING:
                job._stop_reason = "pause"
                job._stop_event.set()         # the download thread will notice and stop
            elif job.state is JobState.PENDING:
                job.state = JobState.PAUSED   # hold it: the worker skips paused jobs
                job.message = "Paused"
            else:
                return
        self.on_change(job)

    def resume(self, job):
        with self._condition:
            if job.state is not JobState.PAUSED:
                return
            job.state = JobState.PENDING      # back in line (yt-dlp continues the .part file)
            job.message = ""
            self._condition.notify()
        self.on_change(job)

    def cancel(self, job):
        with self._condition:
            if job.state is JobState.DOWNLOADING:
                job._stop_reason = "cancel"
                job._stop_event.set()
            elif job.state in (JobState.PENDING, JobState.PAUSED):
                job.state = JobState.CANCELLED
                job.message = "Cancelled"
            else:
                return
        self.on_change(job)

    # ------------------------------------------------------------
    # The background worker
    # ------------------------------------------------------------
    def _next_pending(self):
        for job in self.jobs:
            if job.state is JobState.PENDING:
                return job
        return None

    def _run(self):
        while True:
            with self._condition:
                job = self._next_pending()
                while job is None:
                    self._condition.wait()    # sleep until add() or resume() wakes us
                    job = self._next_pending()
                job.state = JobState.DOWNLOADING
                job._stop_event = threading.Event()    # a fresh flag for this run
                job._stop_reason = None
            self.on_change(job)
            self._execute(job)

    def _execute(self, job):
        last_report = 0.0

        def on_progress(progress):
            nonlocal last_report
            job.progress = progress
            now = time.monotonic()
            if progress.status == "downloading" and now - last_report < 0.25:
                return                        # at most ~4 updates per second
            last_report = now
            self.on_change(job)

        try:
            result = self.downloader.download(job.request, on_progress, job._stop_event)
        except UserCancelledError:
            if job._stop_reason == "pause":
                self._finish(job, JobState.PAUSED, "Paused")
            else:
                self._finish(job, JobState.CANCELLED, "Cancelled")
        except GrabberError as e:
            self._finish(job, JobState.FAILED, str(e))
        except Exception as e:
            traceback.print_exc()             # a real bug: show everything in the terminal
            self._finish(job, JobState.FAILED, f"Unexpected error: {e}")
        else:
            job.files = result.files
            self._finish(job, JobState.DONE, "")

    def _finish(self, job, state, message):
        with self._condition:
            job.state = state
            job.message = message
        self.on_change(job)