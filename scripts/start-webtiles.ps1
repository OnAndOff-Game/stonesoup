$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$bashPath = "C:\msys64\usr\bin\bash.exe"
$runtimeDir = Join-Path $projectRoot ".webtiles-runtime"
$sourceDir = Join-Path $projectRoot "crawl-ref\source"
$binaryPath = Join-Path $sourceDir "crawl.exe"
$stdoutLog = Join-Path $runtimeDir "webtiles.log"
$stderrLog = Join-Path $runtimeDir "webtiles-error.log"
$url = "http://127.0.0.1:8080/"

function Show-WebTilesAddresses {
    param([string]$LocalUrl)
    Write-Host "Local: $LocalUrl"
    try {
        $addresses = [System.Net.Dns]::GetHostAddresses(
            [System.Net.Dns]::GetHostName()) | Where-Object {
                $_.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork -and
                -not [System.Net.IPAddress]::IsLoopback($_)
            }
        foreach ($address in $addresses) {
            Write-Host "LAN:   http://$($address.IPAddressToString):8080/"
        }
    }
    catch {
        Write-Host "Could not determine a LAN address."
    }
}

function Test-WebTilesPort {
    try {
        $client = [System.Net.Sockets.TcpClient]::new()
        $task = $client.ConnectAsync("127.0.0.1", 8080)
        $connected = $task.Wait(250) -and $client.Connected
        $client.Dispose()
        return $connected
    }
    catch {
        return $false
    }
}

if (-not (Test-Path -LiteralPath $bashPath)) {
    throw "MSYS2 bash is missing: $bashPath"
}
if (-not (Test-Path -LiteralPath $binaryPath)) {
    throw "WebTiles binary is missing. Run BUILD_WEB.cmd first."
}

if (Test-WebTilesPort) {
    Write-Host "DCSS WebTiles is already running."
    Show-WebTilesAddresses -LocalUrl $url
    Write-Host "The existing browser session was left untouched."
    exit 0
}

New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null

$process = Start-Process -FilePath $bashPath `
    -ArgumentList @("./scripts/run-webtiles.sh") `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog `
    -PassThru

for ($attempt = 0; $attempt -lt 80; $attempt++) {
    if (Test-WebTilesPort) {
        Start-Process $url
        Write-Host "DCSS WebTiles dedicated server is ready."
        Show-WebTilesAddresses -LocalUrl $url
        Write-Host "Logs: $stdoutLog"
        exit 0
    }
    if ($process.HasExited) {
        $details = if (Test-Path -LiteralPath $stderrLog) {
            (Get-Content -LiteralPath $stderrLog -Tail 20) -join [Environment]::NewLine
        } else {
            "No error log was created."
        }
        throw "WebTiles stopped during startup.`n$details"
    }
    Start-Sleep -Milliseconds 250
}

throw "WebTiles did not open port 8080 within 20 seconds. Check $stderrLog"
