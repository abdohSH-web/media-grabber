import itertools
import threading
import time
import traceback
from enum import Enum

from .errors import GrabberError, UserCancelledError

MAX_PARALLEL = 5      # the most downloads that can run at the same time


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

    def __init__(self, request, title, item_count=1):
        self.id = next(DownloadJob._ids)
        self.request = request
        self.title = title
        self.item_count = item_count   # how many videos (more than 1 for a playlist)
        self.state = JobState.PENDING
        self.progress = None           # the latest Progress object (or None)
        self.message = ""              # error text or a short note
        self.files = ()                # filled when the job is DONE
        self.size_bytes = None         # total size on disk, filled when the job is DONE
        self._stop_event = threading.Event()
        self._stop_reason = None       # "pause" or "cancel"


class DownloadQueue:
    """Runs jobs in background threads, up to `max_parallel` at the same time.
    It knows nothing about the UI: it just calls on_change(job) whenever
    a job changes, and whoever created the queue decides what to do with that."""

    def __init__(self, downloader, on_change=None):
        self.downloader = downloader
        self.on_change = on_change or (lambda job: None)
        self.jobs = []
        self.max_parallel = 1          # how many may run at once RIGHT NOW (the user can change it)
        self._active = 0               # how many are running right now

        # A Condition = a lock + a way to put a thread to sleep until someone wakes it
        self._condition = threading.Condition()

        # One worker thread per possible slot. Most of the time they just sleep.
        # daemon=True: they won't keep the program alive after the window closes
        for _ in range(MAX_PARALLEL):
            threading.Thread(target=self._run, daemon=True).start()

    # ------------------------------------------------------------
    # Commands (called by the UI, from any thread)
    # ------------------------------------------------------------
    def set_max_parallel(self, count):
        with self._condition:
            self.max_parallel = max(1, min(int(count), MAX_PARALLEL))
            # Wake every worker: if the limit went UP, some can start a job now.
            # (If it went DOWN, running jobs finish normally; no new ones start until
            # fewer than the limit are running.)
            self._condition.notify_all()

    def add(self, request, title, item_count=1, paused=False):
        """paused=True: the job waits in the list until the user resumes it.
        (Used when restoring the queue from the last session.)"""
        job = DownloadJob(request, title, item_count)
        if paused:
            job.state = JobState.PAUSED
            job.message = "Restored from the last session"
        with self._condition:
            self.jobs.append(job)
            if not paused:
                self._condition.notify_all()
        self.on_change(job)
        return job

    def pause(self, job):
        with self._condition:
            if job.state is JobState.DOWNLOADING:
                job._stop_reason = "pause"
                job._stop_event.set()         # the download thread will notice and stop
            elif job.state is JobState.PENDING:
                job.state = JobState.PAUSED   # hold it: the workers skip paused jobs
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
            self._condition.notify_all()
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

    def clear_finished(self):
        """Forget jobs that are over (done, failed or cancelled)."""
        with self._condition:
            active = (JobState.PENDING, JobState.DOWNLOADING, JobState.PAUSED)
            self.jobs = [job for job in self.jobs if job.state in active]

    # ------------------------------------------------------------
    # The background workers
    # ------------------------------------------------------------
    def _next_pending(self):
        for job in self.jobs:
            if job.state is JobState.PENDING:
                return job
        return None

    def _claim_job(self):
        """Sleep until there is a waiting job AND a free slot, then take the job."""
        with self._condition:
            while True:
                if self._active < self.max_parallel:
                    job = self._next_pending()
                    if job is not None:
                        job.state = JobState.DOWNLOADING
                        job._stop_event = threading.Event()    # a fresh flag for this run
                        job._stop_reason = None
                        self._active += 1                      # this job now uses a slot
                        return job
                self._condition.wait()        # sleep until something changes

    def _run(self):
        while True:
            job = self._claim_job()
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
            traceback.print_exc()             # a real bug: show everything in the log
            self._finish(job, JobState.FAILED, f"Unexpected error: {e}")
        else:
            job.files = result.files
            job.size_bytes = self._total_size(result.files)
            self._finish(job, JobState.DONE, "")

    @staticmethod
    def _total_size(files):
        """Total size of the saved files in bytes (None if we can't tell)."""
        total = 0
        for file in files:
            try:
                total += file.stat().st_size
            except OSError:
                pass
        return total or None

    def _finish(self, job, state, message):
        with self._condition:
            job.state = state
            job.message = message
            self._active -= 1                 # this job no longer uses a slot
            self._condition.notify_all()      # a slot is free: another job may start
        self.on_change(job)