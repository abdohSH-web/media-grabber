import shutil


def find_tool(name):
    """Return the full path of a program found on PATH (like "ffmpeg"), or None."""
    return shutil.which(name)