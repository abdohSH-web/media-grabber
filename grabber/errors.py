class GrabberError(Exception):
    """Base class for every error this app raises on purpose.

    code    : a short name. The interface looks for the translation "err_<code>".
    details : the values for that translation's {holes}. "reason" (the plain
              message) is always available."""

    default_code = "failed"

    def __init__(self, message="", code=None, **details):
        super().__init__(message)
        self.code = code or self.default_code
        self.details = {"reason": message, **details}


class InvalidUrlError(GrabberError):
    """The text isn't a usable web address, or the site isn't supported."""
    default_code = "invalid_url"


class MediaUnavailableError(GrabberError):
    """The media can't be accessed (private, removed, blocked, needs login...)."""
    default_code = "unavailable"


class FFmpegMissingError(GrabberError):
    """FFmpeg is needed for this job but wasn't found on this computer."""
    default_code = "ffmpeg_missing"


class DownloadFailedError(GrabberError):
    """Any other failure. The message keeps the original reason."""
    default_code = "failed"


class VerificationRequiredError(GrabberError):
    """The site wants proof you're a real user (YouTube's "confirm you're not a bot")."""
    default_code = "bot_check"


class CookieProblemError(GrabberError):
    """Browser cookies were requested but couldn't be read."""
    default_code = "cookie_problem"


class UserCancelledError(GrabberError):
    """The user pressed Cancel. Not a failure: the UI shows no warning for it."""
    default_code = "cancelled"


class HistoryError(GrabberError):
    """The download history couldn't be saved."""
    default_code = "history_error"


class QueueStoreError(GrabberError):
    """The unfinished queue couldn't be saved."""
    default_code = "queue_error"


class ToolSetupError(GrabberError):
    """FFmpeg or Deno couldn't be downloaded or unpacked."""
    default_code = "tools_failed"