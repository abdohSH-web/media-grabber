import time
from pathlib import Path

from grabber.downloader import Downloader
from grabber.jobs import DownloadQueue, JobState
from grabber.models import DownloadRequest, Mode

URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
FOLDER = Path("downloads")


def show(job):
    """Called by the queue (from its own thread) every time a job changes."""
    p = job.progress
    percent = f"{p.percent:5.1f}%" if p else "      "
    print(f"[job {job.id}] {job.state.value:<11} {percent}  {job.title}  {job.message}")


queue = DownloadQueue(Downloader(), on_change=show)

queue.add(DownloadRequest(URL, FOLDER, Mode.VIDEO, 360), "Video 360p")
queue.add(DownloadRequest(URL, FOLDER, Mode.AUDIO), "Audio only")
third = queue.add(DownloadRequest(URL, FOLDER, Mode.VIDEO, 144), "Will be cancelled")
queue.cancel(third)            # it is still waiting in line, so it's cancelled at once

# Wait until nothing is waiting or running
while any(j.state in (JobState.PENDING, JobState.DOWNLOADING) for j in queue.jobs):
    time.sleep(0.5)

print("\nFinal:", [(j.id, j.state.value) for j in queue.jobs])