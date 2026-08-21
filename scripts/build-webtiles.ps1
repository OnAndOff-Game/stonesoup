$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$bashPath = "C:\msys64\usr\bin\bash.exe"

if (-not (Test-Path -LiteralPath $bashPath)) {
    throw "MSYS2 bash is missing: $bashPath"
}

& $bashPath "./scripts/build-webtiles.sh"
if ($LASTEXITCODE -ne 0) {
    throw "The WebTiles build failed."
}

Write-Host "WebTiles build completed. Run PLAY_WEB.cmd."

