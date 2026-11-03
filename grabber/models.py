from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class Mode(Enum):
    """What the user wants to get."""
    VIDEO = "video"
    AUDIO = "audio"


# @dataclass writes __init__ and __repr__ for us.
# frozen=True makes the objects read-only after creation.

@dataclass(frozen=True)
class PlaylistEntry:
    """One video inside a playlist, as listed BEFORE downloading."""
    index: int                           # position in the playlist, starting at 1
    title: str
    duration_seconds: int | None


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
    heights: tuple[int, ...] = ()                  # available video heights, e.g. (1080, 720)
    entries: tuple[PlaylistEntry, ...] = ()        # the videos of a playlist


@dataclass(frozen=True)
class DownloadRequest:
    """What the user chose."""
    url: str
    folder: Path
    mode: Mode = Mode.VIDEO
    max_height: int | None = None        # None = the best quality available
    playlist: bool = False
    items: tuple[int, ...] | None = None  # playlist positions to download (None = all)
    subtitles: tuple[str, ...] = ()       # language codes like ("en", "ar"); empty = none
    auto_subtitles: bool = True           # also accept auto-generated subtitles
    clip_start: float | None = None       # seconds. When set: download only a part
    clip_end: float | None = None         # seconds. None = until the end

    @property
    def has_clip(self):
        return self.clip_start is not None

@dataclass(frozen=True)
class Progress:
    """One progress report, sent to whoever is listening."""
    status: str                          # "downloading", "processing" or "finished"
    percent: float                       # 0 to 100, for the CURRENT item (all its streams)
    speed: float | None                  # bytes per second
    eta: int | None                      # seconds left (for the whole item)
    filename: str
    item_index: int | None = None        # position inside a playlist, else None
    downloaded_bytes: int | None = None  # bytes of the current item downloaded so far
    total_bytes: int | None = None       # its total size (None when unknown)


@dataclass(frozen=True)
class DownloadResult:
    files: tuple[Path, ...]


@dataclass(frozen=True)
class CookieSettings:
    """Where to take login cookies from (YouTube sometimes demands them)."""
    browser: str | None = None       # "firefox", "edge", "chrome", "brave", or None
    file: Path | None = None         # a cookies.txt file (it wins over the browser)