import zipfile

import pytest

from grabber.errors import ToolSetupError
from grabber.toolsetup import extract_tools


def make_zip(path, files):
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)


def test_only_the_wanted_files_are_taken_from_any_depth(tmp_path):
    archive = tmp_path / "ffmpeg.zip"
    make_zip(archive, {
        "ffmpeg-7.1-essentials_build/bin/ffmpeg.exe": b"ffmpeg",
        "ffmpeg-7.1-essentials_build/bin/ffprobe.exe": b"ffprobe",
        "ffmpeg-7.1-essentials_build/bin/ffplay.exe": b"ffplay",
        "ffmpeg-7.1-essentials_build/README.txt": b"readme",
    })
    out = tmp_path / "tools"

    found = extract_tools(archive, ("ffmpeg.exe", "ffprobe.exe"), out)

    assert sorted(found) == ["ffmpeg.exe", "ffprobe.exe"]
    assert (out / "ffmpeg.exe").read_bytes() == b"ffmpeg"
    assert not (out / "ffplay.exe").exists()                   # not asked for


def test_a_malicious_path_cannot_escape_the_folder(tmp_path):
    archive = tmp_path / "evil.zip"
    make_zip(archive, {"../../evil.exe": b"x"})
    out = tmp_path / "sub" / "tools"

    extract_tools(archive, ("evil.exe",), out)

    assert (out / "evil.exe").exists()                         # written INSIDE our folder
    assert not (tmp_path.parent / "evil.exe").exists()


def test_a_zip_without_the_file_finds_nothing(tmp_path):
    archive = tmp_path / "empty.zip"
    make_zip(archive, {"readme.txt": b"hello"})
    assert extract_tools(archive, ("deno.exe",), tmp_path / "tools") == []


def test_a_file_that_is_not_a_zip_raises_our_error(tmp_path):
    archive = tmp_path / "broken.zip"
    archive.write_text("this is not a zip", encoding="utf-8")
    with pytest.raises(ToolSetupError):
        extract_tools(archive, ("deno.exe",), tmp_path / "tools")