import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.request import urlopen

from .errors import ToolSetupError
from .tools import find_tool

# Official download links (the "latest" versions)
FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
DENO_URL = "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip"

# tool -> (download link, the files we take out of the zip)
TOOLS = {
    "ffmpeg": (FFMPEG_URL, ("ffmpeg.exe", "ffprobe.exe")),
    "deno": (DENO_URL, ("deno.exe",)),
}


@dataclass(frozen=True)
class ToolProgress:
    tool: str
    fraction: float          # 0.0 to 1.0, for THIS tool's download


def missing_tools():
    """Names of the tools we depend on that can't be found right now."""
    return [name for name in TOOLS if not find_tool(name)]


def _download(url, destination, tool, on_progress):
    try:
        with urlopen(url, timeout=30) as response, open(destination, "wb") as out:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if on_progress and total:
                    on_progress(ToolProgress(tool, min(done / total, 1.0)))
    except OSError as e:            # network errors (URLError, timeouts...) are OSErrors
        raise ToolSetupError(
            f"Could not download {tool}: {e}", tool=tool, reason=str(e)
        ) from e


def extract_tools(zip_path, wanted, folder):
    """Copy the wanted files out of the zip, wherever they sit inside it.
    Only the FILE NAME is used, never the path stored in the zip, so a malicious
    zip can't write outside our folder. Returns the names that were found."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    found = []
    try:
        with zipfile.ZipFile(zip_path) as archive:
            for member in archive.namelist():
                name = Path(member).name.lower()
                if name in wanted and name not in found:
                    temp = folder / (name + ".part")
                    with archive.open(member) as source, open(temp, "wb") as out:
                        shutil.copyfileobj(source, out)
                    os.replace(temp, folder / name)     # swap in one step
                    found.append(name)
    except (zipfile.BadZipFile, OSError) as e:
        raise ToolSetupError(f"Could not unpack the download: {e}", reason=str(e)) from e
    return found


def install_tools(folder, names=None, on_progress=None):
    """Download and unpack the given tools (default: the missing ones) into `folder`.
    on_progress receives ToolProgress objects. Returns the names installed."""
    names = list(names) if names is not None else missing_tools()
    installed = []
    for tool in names:
        url, wanted = TOOLS[tool]
        with tempfile.TemporaryDirectory() as temp_dir:     # deleted when the block ends
            zip_path = Path(temp_dir) / f"{tool}.zip"
            _download(url, zip_path, tool, on_progress)
            found = extract_tools(zip_path, wanted, folder)
        if f"{tool}.exe" not in found:
            raise ToolSetupError(
                f"{tool}.exe wasn't inside the download", tool=tool, reason="file missing in the zip"
            )
        installed.append(tool)
    return installed