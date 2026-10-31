from pathlib import Path

from grabber.downloader import Downloader
from grabber.errors import GrabberError
from grabber.models import DownloadRequest, Mode
from grabber.tools import find_tool

# A very short test video (19 seconds), so every test finishes fast
URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
FOLDER = Path("downloads")


def show_progress(p):
    # "\r" moves back to the start of the line, so the SAME line is rewritten
    print(f"\r{p.status:<12} {p.percent:5.1f}%", end="", flush=True)


downloader = Downloader()
print("FFmpeg:", downloader.ffmpeg)
print("Deno  :", find_tool("deno"))

# # Test 1: a bad link must give our error, not a crash
try:
    downloader.fetch_info("hello")
except GrabberError as e:
    print("\nTest 1 OK ->", type(e).__name__, ":", e)

try:
    #  Test 2: look at a real link 
    info = downloader.fetch_info(URL)
    print("\nTitle   :", info.title)
    print("Uploader:", info.uploader)
    print("Duration:", info.duration_seconds, "seconds")
    print("Heights :", info.heights)

    #  Test 3: download the video, capped at 360p 
    request = DownloadRequest(url=URL, folder=FOLDER, mode=Mode.VIDEO, max_height=360)
    result = downloader.download(request, show_progress)
    print("\nSaved:", result.files)

    #  Test 4: download the audio only, as mp3 
    request = DownloadRequest(url=URL, folder=FOLDER, mode=Mode.AUDIO)
    result = downloader.download(request, show_progress)
    print("\nSaved:", result.files)

except GrabberError as e:
    print("\nFailed:", type(e).__name__, ":", e)