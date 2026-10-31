from pathlib import Path
from urllib.parse import urlparse

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from .errors import (
    DownloadFailedError,
    FFmpegMissingError,
    InvalidUrlError,
    MediaUnavailableError,
)
from .models import DownloadRequest, DownloadResult, MediaInfo, Mode, Progress
from .tools import find_tool


def validate_url(url):
    """Return the cleaned URL, or raise InvalidUrlError."""
    url = (url or "").strip()
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise InvalidUrlError(f"This doesn't look like a web address: {url!r}")
    return url


def _translate_error(error):
    """Turn yt-dlp's DownloadError into one of OUR errors, by reading its message.
    This is a best-effort guess: unknown messages become DownloadFailedError."""
    message = str(error).replace("ERROR: ", "", 1)
    lowered = message.lower()

    if "unsupported url" in lowered:
        return InvalidUrlError("This link or website isn't supported.")

    unavailable_markers = (
        "private video", "video unavailable", "not available",
        "has been removed", "sign in to confirm", "members-only",
    )
    if any(marker in lowered for marker in unavailable_markers):
        return MediaUnavailableError(message)

    return DownloadFailedError(message)


def _final_paths(info):
    """Collect the saved file paths from yt-dlp's result (single video or playlist)."""
    entries = info.get("entries")
    items = [entry for entry in entries if entry] if entries else [info]

    paths = []
    for item in items:
        for download in item.get("requested_downloads") or []:
            path = download.get("filepath")
            if path:
                paths.append(path)
    return paths


class Downloader:
    """Our own simple interface on top of yt-dlp.
    The rest of the app talks to this class and never imports yt_dlp directly."""

    def __init__(self):
        self.ffmpeg = find_tool("ffmpeg")        # full path, or None


    # 1) Look at a link without downloading it 
    def fetch_info(self, url, playlist=False):
        url = validate_url(url)

        options = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": not playlist,
        }
        if playlist:
            # "flat" = list the entries only, without analysing every video
            options["extract_flat"] = "in_playlist"

        try:
            with YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=False)
        except DownloadError as e:
            raise _translate_error(e) from e

        return self._to_media_info(url, info)

    @staticmethod
    def _to_media_info(url, info):
        entries = info.get("entries")
        is_playlist = entries is not None

        heights = ()
        if not is_playlist:
            # Keep only real video formats that report a height
            found = {
                f["height"]
                for f in info.get("formats") or []
                if f.get("height") and f.get("vcodec") not in (None, "none")
            }
            heights = tuple(sorted(found, reverse=True))

        return MediaInfo(
            url=url,
            title=info.get("title") or "Untitled",
            uploader=info.get("uploader") or info.get("channel") or "Unknown",
            duration_seconds=info.get("duration"),
            thumbnail_url=info.get("thumbnail"),
            is_playlist=is_playlist,
            entry_count=len(list(entries)) if is_playlist else 1,
            heights=heights,
        )


    # 2) Download
    def download(self, request, on_progress=None):
        """Download according to `request`.
        on_progress is optional: a function that receives Progress objects.
        (A function passed to another function is called a callback.)"""
        url = validate_url(request.url)

        if not self.ffmpeg:
            raise FFmpegMissingError(
                "FFmpeg wasn't found. Install it with: winget install Gyan.FFmpeg "
                "and restart the app."
            )

        def hook(d):
            # yt-dlp calls this many times per second with a dict called d
            if on_progress is None:
                return
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                done = d.get("downloaded_bytes") or 0
                percent = done / total * 100 if total else 0.0
                on_progress(Progress(
                    "downloading", percent, d.get("speed"), d.get("eta"),
                    d.get("filename", ""),
                ))
            elif d.get("status") == "finished":
                # One file finished downloading; merging/converting comes next
                on_progress(Progress("processing", 100.0, None, None, d.get("filename", "")))

        try:
            options = self._build_options(request, hook)
            with YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=True)
        except DownloadError as e:
            raise _translate_error(e) from e
        except OSError as e:
            raise DownloadFailedError(f"File problem: {e}") from e

        if on_progress:
            on_progress(Progress("finished", 100.0, None, None, ""))

        return DownloadResult(files=tuple(Path(p) for p in _final_paths(info)))

    def _build_options(self, request, hook):
        """Translate OUR request into yt-dlp's options dictionary."""
        folder = Path(request.folder)
        folder.mkdir(parents=True, exist_ok=True)

        if request.playlist:
            # A subfolder per playlist, files numbered in order
            template = "%(playlist_title)s/%(playlist_index)s - %(title)s [%(id)s].%(ext)s"
        else:
            template = "%(title)s [%(id)s].%(ext)s"

        options = {
            "outtmpl": str(folder / template),
            "noplaylist": not request.playlist,
            "quiet": True,
            "no_warnings": True,
            "windowsfilenames": True,            # no characters Windows forbids
            "ffmpeg_location": self.ffmpeg,
            "progress_hooks": [hook],
        }

        if request.mode is Mode.AUDIO:
            options["format"] = "bestaudio/best"
            options["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }]
        else:
            # "[height<=720]" caps the quality at 720p. (">=" would mean 720 or MORE.)
            limit = f"[height<={request.max_height}]" if request.max_height else ""
            options["format"] = f"bv*{limit}+ba/b{limit}"
            # Prefer H.264 video and AAC audio: they play everywhere on Windows
            options["format_sort"] = ["vcodec:h264", "res", "acodec:m4a"]
            options["merge_output_format"] = "mp4"

        return options