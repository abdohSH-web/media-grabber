import os
import shutil
import sys
from pathlib import Path


def app_folder():
    """The folder of the .exe when packaged, otherwise the project folder."""
    if getattr(sys, "frozen", False):       # "frozen" = running as a packaged program
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def add_to_path(folder):
    """Put `folder` first on the PATH of this program (and of the programs it starts,
    like yt-dlp looking for Deno)."""
    folder = str(folder)
    current = os.environ.get("PATH", "")
    if folder not in current.split(os.pathsep):
        os.environ["PATH"] = folder + os.pathsep + current


def use_bundled_tools(extra_folders=()):
    """Make tools that sit next to the app (a 'bin' folder) or in our own tools
    folder findable. Folders that don't exist are ignored."""
    for folder in (app_folder() / "bin", *extra_folders):
        if Path(folder).is_dir():
            add_to_path(folder)


def find_tool(name):
    """Return the full path of a program found on PATH (like "ffmpeg"), or None."""
    return shutil.which(name)