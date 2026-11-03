# Builds dist\MediaGrabber\MediaGrabber.exe
# Run from the project folder, with the virtual environment active:   .\build.ps1
$ErrorActionPreference = "Stop"      # stop at the first error instead of continuing

# Always build with the newest yt-dlp (YouTube changes all the time)
python -m pip install --upgrade "yt-dlp[default]" pyinstaller

pyinstaller --noconfirm --clean --windowed `
    --name MediaGrabber `
    --icon assets/icon.ico `
    --add-data "assets;assets" `
    --collect-all yt_dlp `
    --collect-all yt_dlp_ejs `
    main.py

# Optional: copy FFmpeg / Deno next to the app (put them in the tools_bin folder first)
if (Test-Path tools_bin) {
    Copy-Item tools_bin dist\MediaGrabber\bin -Recurse -Force
    Write-Host "Copied tools_bin to dist\MediaGrabber\bin"
}

Write-Host ""
Write-Host "Done: dist\MediaGrabber\MediaGrabber.exe"