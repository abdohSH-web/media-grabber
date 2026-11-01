from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class Mode(Enum):
    """What the user wants to get."""
    VIDEO = "video"
    AUDIO = "audio"


# @dataclass writes __init__ and __repr__ for us.
# frozen=True makes the objects read-only after creation (safer: nobody
# changes them by accident while a download is running).

@dataclass(frozen=True)
class MediaInfo:
    """What we learned about a link BEFORE downloading it."""
    url: str
    title: str
    uploader: str
    duration_seconds: int | None
    thumbnail_url: str | None
    is_playlist: bool
    entry_count: int
    heights: tuple[int, ...] = ()        # available video heights, e.g. (1080, 720, 360)


@dataclass(frozen=True)
class DownloadRequest:
    """What the user chose."""
    url: str
    folder: Path
    mode: Mode = Mode.VIDEO
    max_height: int | None = None        # None = the best quality available
    playlist: bool = False


@dataclass(frozen=True)
class Progress:
    """One progress report, sent to whoever is listening."""
    status: str                          # "downloading", "processing" or "finished"
    percent: float                       # 0 to 100, for the CURRENT file
    speed: float | None                  # bytes per second
    eta: int | None                      # seconds left
    filename: str
    item_index: int | None = None        # position inside a playlist (1, 2, 3...), else None


@dataclass(frozen=True)
class DownloadResult:
    files: tuple[Path, ...]


@dataclass(frozen=True)
class CookieSettings:
    """Where to take login cookies from (YouTube sometimes demands them)."""
    browser: str | None = None       # "firefox", "edge", "chrome", "brave", or None
    file: Path | None = None         # a cookies.txt file (it wins over the browser)