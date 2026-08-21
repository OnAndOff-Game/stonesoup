$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$bashPath = "C:\msys64\usr\bin\bash.exe"
$sourceDir = Join-Path $projectRoot "crawl-ref\source"
$pidPath = Join-Path $sourceDir "webserver\webtiles-msys.pid"

if (-not (Test-Path -LiteralPath $bashPath)) {
    throw "MSYS2 bash is missing: $bashPath"
}
if (-not (Test-Path -LiteralPath $pidPath)) {
    Write-Host "DCSS WebTiles is not running (no PID file)."
    exit 0
}

& $bashPath "./scripts/stop-webtiles.sh"
if ($LASTEXITCODE -ne 0) {
    throw "Could not stop WebTiles cleanly."
}

