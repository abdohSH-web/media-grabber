# Builds the app, then the installer:   .\build_installer.ps1
$ErrorActionPreference = "Stop"

.\build.ps1 -NoTools

$version = (python -c "from grabber.version import APP_VERSION; print(APP_VERSION)").Trim()

# Inno Setup doesn't add itself to PATH, so look in its usual places
$candidates = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
)
$iscc = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 wasn't found. Install it with: winget install JRSoftware.InnoSetup" }

& $iscc "/DMyAppVersion=$version" installer\MediaGrabber.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }

Write-Host ""
Write-Host "Done: installer_output\MediaGrabber-Setup-$version.exe"