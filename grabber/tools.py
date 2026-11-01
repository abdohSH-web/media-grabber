import os
import shutil
import sys
from pathlib import Path


def app_folder():
    """The folder of the .exe when packaged, otherwise the project folder."""
    if getattr(sys, "frozen", False):       # "frozen" = running as a packaged program
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def use_bundled_tools():
    """If a 'bin' folder sits next to the app (holding ffmpeg.exe, deno.exe...),
    put it FIRST on the PATH. Every search for a tool, ours and yt-dlp's, then finds it."""
    bin_folder = app_folder() / "bin"
    if bin_folder.is_dir():
        os.environ["PATH"] = str(bin_folder) + os.pathsep + os.environ.get("PATH", "")


def find_tool(name):
    """Return the full path of a program found on PATH (like "ffmpeg"), or None."""
    return shutil.which(name)