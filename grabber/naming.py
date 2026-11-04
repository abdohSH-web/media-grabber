import re

# Characters Windows refuses in a file or folder name (plus control characters)
_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL",
             *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def safe_folder_name(text, fallback="Playlist", max_length=80):
    """A playlist's title as a folder name Windows accepts."""
    name = _FORBIDDEN.sub("_", text or "").strip()
    name = name[:max_length].rstrip(". ")        # Windows also refuses a trailing dot or space
    if not name or name.upper() in _RESERVED:
        return fallback
    return name