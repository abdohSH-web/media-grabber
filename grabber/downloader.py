import time
import os
from pathlib import Path
from urllib.parse import urlparse

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadCancelled, YoutubeDLError, download_range_func

from .errors import (
    CookieProblemError,
    DownloadFailedError,
    FFmpegMissingError,
    InvalidUrlError,
    MediaUnavailableError,
    UserCancelledError,
    VerificationRequiredError,
)
from .models import (
    CookieSettings,
    DownloadRequest,
    DownloadResult,
    MediaInfo,
    Mode,
    PlaylistEntry,
    Progress,
)
from .tools import find_tool


class _SilentLogger:
    """yt-dlp prints a lot to the terminal. Giving it this logger silences it:
    the window shows our own, friendlier messages instead."""

    def debug(self, message):
        pass

    def info(self, message):
        pass

    def warning(self, message):
        pass

    def error(self, message):
        pass


def _logger():
    """Set the environment variable MEDIA_GRABBER_DEBUG=1 to get yt-dlp's normal
    terminal output back (None = its default). Handy when something misbehaves."""
    return None if os.environ.get("MEDIA_GRABBER_DEBUG") else _SilentLogger()


def validate_url(url):
    """Return the cleaned URL, or raise InvalidUrlError."""
    url = (url or "").strip()
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise InvalidUrlError(f"This doesn't look like a web address: {url!r}")
    return url


def _translate_error(error):
    """Turn a yt-dlp error into one of OUR errors, by reading its message.
    This is a best-effort guess: unknown messages become DownloadFailedError."""
    message = str(error).replace("ERROR: ", "", 1)
    lowered = message.lower()

    if "unsupported url" in lowered:
        return InvalidUrlError("This link or website isn't supported.")

    # Check this BEFORE the cookie check: YouTube's own message mentions "cookies"
    if "not a bot" in lowered:
        return VerificationRequiredError(
            "YouTube is asking to verify that you're not a bot.\n\n"
            "Fix: under 'Cookies', choose a browser where you are signed in to YouTube "
            "(Firefox works best on Windows) or a cookies.txt file, then try again."
        )

    cookie_trouble = ("could not copy", "decrypt", "database", "failed to", "not found")
    if ("cookie" in lowered or "dpapi" in lowered) and any(word in lowered for word in cookie_trouble):
        return CookieProblemError(
            "Couldn't read the cookies. Close that browser completely and try again.\n"
            "On Windows, Chrome and Edge often block this: Firefox or a cookies.txt "
            f"file works better.\n\nDetails: {message}"
        )

    unavailable_markers = (
        "private video", "video unavailable", "not available",
        "has been removed", "members-only", "confirm your age",
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


def _entry_url(entry):
    """The link of one playlist entry (from the fast 'flat' listing), or "" if none."""
    url = entry.get("url") or entry.get("webpage_url") or ""
    if url.startswith(("http://", "https://")):
        return url
    video_id = entry.get("id")
    if video_id and (entry.get("ie_key") or "").lower() == "youtube":
        return f"https://www.youtube.com/watch?v={video_id}"
    return ""


def _existed_before(path, started):
    """True if the file is older than this download: yt-dlp found it and skipped it."""
    try:
        return path.stat().st_mtime < started - 1
    except OSError:
        return False


class Downloader:
    """Our own simple interface on top of yt-dlp.
    The rest of the app talks to THIS class and never imports yt_dlp directly."""

    def __init__(self, cookies=None):
        self.ffmpeg = find_tool("ffmpeg")              # full path, or None
        self.cookies = cookies or CookieSettings()     # the UI may replace this any time

    def _apply_cookies(self, options):
        """Add the cookie settings (if any) to a yt-dlp options dictionary."""
        if self.cookies.file:
            options["cookiefile"] = str(self.cookies.file)
        elif self.cookies.browser:
            # yt-dlp expects a tuple here: (browser name,)
            options["cookiesfrombrowser"] = (self.cookies.browser,)

    # ------------------------------------------------------------
    # 1) Look at a link without downloading it
    # ------------------------------------------------------------
    def fetch_info(self, url, playlist=False):
        url = validate_url(url)

        options = {
            "quiet": True,
            "no_warnings": True,
            "logger": _logger(),
            "noplaylist": not playlist,
            # "flat" = list a playlist's entries without analysing every video (fast)
            "extract_flat": "in_playlist",
        }
        self._apply_cookies(options)

        try:
            with YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=False)
        except YoutubeDLError as e:
            raise _translate_error(e) from e

        return self._to_media_info(url, info)

    @staticmethod
    def _to_media_info(url, info):
        raw_entries = info.get("entries")
        is_playlist = raw_entries is not None

        heights = ()
        entries = ()
        if is_playlist:
            # enumerate BEFORE dropping empty entries: positions must match the playlist
            entries = tuple(
                PlaylistEntry(
                    index, entry.get("title") or "Untitled", entry.get("duration"), _entry_url(entry)
                )
                for index, entry in enumerate(list(raw_entries), start=1)
                if entry
            )
        else:
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
            entry_count=len(entries) if is_playlist else 1,
            heights=heights,
            entries=entries,
        )

    # ------------------------------------------------------------
    # 2) Download
    # ------------------------------------------------------------
    def download(self, request, on_progress=None, cancel_event=None):
        """Download according to `request`.
        on_progress  : OPTIONAL function that receives Progress objects (a callback).
        cancel_event : OPTIONAL threading.Event. Another thread calls .set() on it
                       to ask us to stop."""
        url = validate_url(request.url)

        if not self.ffmpeg:
            raise FFmpegMissingError(
                "FFmpeg wasn't found. Install it with: winget install Gyan.FFmpeg "
                "and restart the app."
            )

        # A video is usually TWO files (picture + sound). To report ONE smooth progress
        # per item, we remember how much of the current item is already finished.
        state = {"item": None, "finished": 0, "finished_bytes": 0}

        def hook(d):
            # yt-dlp calls this many times per second with a dict called d.

            # 1) Cancel check FIRST. Raising here makes yt-dlp stop right away.
            if cancel_event is not None and cancel_event.is_set():
                raise DownloadCancelled()

            if on_progress is None:
                return

            info_dict = d.get("info_dict") or {}
            item_index = info_dict.get("playlist_index")
            if item_index != state["item"]:          # a new playlist item started
                state.update(item=item_index, finished=0, finished_bytes=0)

            formats = info_dict.get("requested_formats") or []
            stream_count = len(formats) or 1

            # 2) Report progress
            if d.get("status") == "downloading":
                stream_total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                stream_done = d.get("downloaded_bytes") or 0

                done = state["finished_bytes"] + stream_done
                # Size of ALL streams of this item, as announced by the site (may be approximate)
                planned = sum((f.get("filesize") or f.get("filesize_approx") or 0) for f in formats)
                total = planned if planned >= done else state["finished_bytes"] + stream_total

                if total > 0 and total >= done:
                    percent = done / total * 100
                else:                                # sizes unknown: fall back to counting streams
                    fraction = stream_done / stream_total if stream_total else 0.0
                    percent = (state["finished"] + fraction) / stream_count * 100
                    total = 0

                speed = d.get("speed")
                eta = d.get("eta")
                if speed and total > done:
                    eta = int((total - done) / speed)    # time for ALL streams, not just this one

                on_progress(Progress(
                    "downloading", min(percent, 100.0), speed, eta,
                    d.get("filename", ""), item_index, done, total or None,
                ))

            elif d.get("status") == "finished":
                state["finished"] += 1
                state["finished_bytes"] += d.get("total_bytes") or d.get("downloaded_bytes") or 0
                # Only when ALL streams are downloaded does merging/converting begin
                if state["finished"] >= stream_count:
                    on_progress(Progress(
                        "processing", 100.0, None, None, d.get("filename", ""), item_index,
                    ))

        started = time.time()
        try:
            options = self._build_options(request, hook)
            with YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=True)
        except DownloadCancelled as e:               # must come BEFORE YoutubeDLError
            raise UserCancelledError("Download cancelled.") from e
        except YoutubeDLError as e:
            raise _translate_error(e) from e
        except OSError as e:
            raise DownloadFailedError(f"File problem: {e}") from e

        if on_progress:
            on_progress(Progress("finished", 100.0, None, None, ""))

        files = tuple(Path(p) for p in _final_paths(info))
        reused = tuple(path for path in files if _existed_before(path, started))
        return DownloadResult(files=files, reused=reused)

    def _build_options(self, request, hook):
        """Translate OUR request into yt-dlp's options dictionary."""
        folder = Path(request.folder)
        folder.mkdir(parents=True, exist_ok=True)

        # File name = the title plus the real quality: "My video [720p].mp4".
        # "%(height& [{}p]|)s" means: if the video has a height, write " [720p]", else nothing.
        quality = "" if request.mode is Mode.AUDIO else "%(height& [{}p]|)s"
        # name_prefix is plain text (like "03 - " for playlist videos): a "%" must be doubled
        prefix = request.name_prefix.replace("%", "%%")
        name = f"{prefix}%(title)s{quality}.%(ext)s"

        if request.playlist:
            # A subfolder per playlist, files numbered by their place in the playlist
            template = f"%(playlist_title)s/%(playlist_index)s - {name}"
        else:
            template = name

        options = {
            "outtmpl": str(folder / template),
            "noplaylist": not request.playlist,
            "quiet": True,
            "no_warnings": True,
            "logger": _logger(),
            "windowsfilenames": True,            # no characters Windows forbids
            "trim_file_name": 150,               # very long titles are shortened
            "updatetime": False,                 # keep the file's date = when WE saved it               
            "ffmpeg_location": self.ffmpeg,
            "progress_hooks": [hook],
        }

        postprocessors = []                      # extra steps yt-dlp runs with FFmpeg

        if request.mode is Mode.AUDIO:
            options["format"] = "bestaudio/best"
            postprocessors.append({
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            })
        else:
            # "[height<=720]" caps the quality at 720p. (">=" would mean 720 or MORE.)
            limit = f"[height<={request.max_height}]" if request.max_height else ""
            options["format"] = f"bv*{limit}+ba/b{limit}"
            # Prefer H.264 video and AAC audio: they play everywhere on Windows
            options["format_sort"] = ["vcodec:h264", "res", "acodec:m4a"]
            options["merge_output_format"] = "mp4"

        if request.subtitles:
            options["writesubtitles"] = True
            options["writeautomaticsub"] = request.auto_subtitles
            options["subtitleslangs"] = list(request.subtitles)
            # Saved next to the video as .srt files
            postprocessors.append({
                "key": "FFmpegSubtitlesConvertor",
                "format": "srt",
                "when": "before_dl",
            })

        if request.has_clip:
            end = request.clip_end if request.clip_end is not None else float("inf")
            options["download_ranges"] = download_range_func([], [(request.clip_start, end)])
            # Slower (re-encodes around the cut points) but the cut is exact
            options["force_keyframes_at_cuts"] = True

        if postprocessors:
            options["postprocessors"] = postprocessors

        if request.playlist:
            # Skip a broken item instead of stopping the whole playlist
            options["ignoreerrors"] = "only_download"
            if request.items:
                # "1,3,7" = only these positions
                options["playlist_items"] = ",".join(str(i) for i in request.items)

        self._apply_cookies(options)
        return options