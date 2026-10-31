class GrabberError(Exception):
    """Base class for every error this app raises on purpose.
    The UI will catch THIS one and show a friendly message."""


class InvalidUrlError(GrabberError):
    """The text isn't a usable web address, or the site isn't supported."""


class MediaUnavailableError(GrabberError):
    """The media can't be accessed (private, removed, blocked, needs login...)."""


class FFmpegMissingError(GrabberError):
    """FFmpeg is needed for this job but wasn't found on this computer."""


class DownloadFailedError(GrabberError):
    """Any other failure. The message keeps the original reason."""