import json
import os
from pathlib import Path

from .errors import QueueStoreError
from .jobs import JobState
from .models import DownloadRequest, Mode

# Only jobs that are not over are worth saving
UNFINISHED = (JobState.PENDING, JobState.DOWNLOADING, JobState.PAUSED)


def request_to_dict(request):
    """A DownloadRequest as plain data that JSON can hold."""
    return {
        "url": request.url,
        "folder": str(request.folder),
        "mode": request.mode.value,
        "max_height": request.max_height,
        "playlist": request.playlist,
        "items": list(request.items) if request.items else None,
        "subtitles": list(request.subtitles),
        "auto_subtitles": request.auto_subtitles,
        "clip_start": request.clip_start,
        "clip_end": request.clip_end,
        "name_prefix": request.name_prefix,
    }


def request_from_dict(data):
    """The opposite. .get(..., default) means a file saved by an OLDER version
    of the app (without the newest fields) still loads fine."""
    items = data.get("items")
    return DownloadRequest(
        url=data["url"],
        folder=Path(data["folder"]),
        mode=Mode(data.get("mode", "video")),
        max_height=data.get("max_height"),
        playlist=bool(data.get("playlist", False)),
        items=tuple(items) if items else None,
        subtitles=tuple(data.get("subtitles") or ()),
        auto_subtitles=bool(data.get("auto_subtitles", True)),
        clip_start=data.get("clip_start"),
        clip_end=data.get("clip_end"),
        name_prefix=data.get("name_prefix", ""),
    )


class QueueStore:
    """Keeps the unfinished jobs in a small JSON file."""

    def __init__(self, path):
        self.path = Path(path)

    def save(self, jobs):
        data = [
            {
                "title": job.title,
                "item_count": job.item_count,
                "request": request_to_dict(job.request),
            }
            for job in jobs
            if job.state in UNFINISHED
        ]
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(".tmp")
            temp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(temp, self.path)           # same safe technique as the history file
        except OSError as e:
            raise QueueStoreError(f"Could not write {self.path}: {e}") from e

    def load(self):
        """Return a list of (request, title, item_count). Damaged entries are skipped."""
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                raise ValueError("expected a list")
        except (OSError, ValueError):
            self._backup_bad_file()               # never crash the app because of this file
            return []

        restored = []
        for item in raw:
            try:
                restored.append((
                    request_from_dict(item["request"]),
                    str(item["title"]),
                    int(item.get("item_count", 1)),
                ))
            except (KeyError, TypeError, ValueError, AttributeError):
                continue                          # one damaged entry must not lose the others
        return restored

    def _backup_bad_file(self):
        try:
            self.path.replace(self.path.with_suffix(".bak"))
        except OSError:
            pass