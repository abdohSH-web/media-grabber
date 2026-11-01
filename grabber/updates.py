import json
from urllib.request import urlopen

from yt_dlp.version import __version__


def installed_version():
    return __version__


def latest_version():
    """Ask PyPI (the Python package website) for the newest yt-dlp version.
    Returns None if anything goes wrong (no internet, blocked site...)."""
    try:
        with urlopen("https://pypi.org/pypi/yt-dlp/json", timeout=10) as response:
            return json.load(response)["info"]["version"]
    except Exception:
        # The check is a convenience, so ANY failure just means "couldn't check"
        return None


def _version_key(text):
    """'2026.10.31' -> (2026, 10, 31), so versions compare correctly as numbers."""
    return tuple(int(part) for part in text.split(".") if part.isdigit())


def is_newer(latest, current):
    return _version_key(latest) > _version_key(current)