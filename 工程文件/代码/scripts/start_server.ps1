param(
    [string]$ConfigPath = "config/server.env",
    [string]$HostName = "",
    [int]$Port = 0
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $ProjectRoot

if (Test-Path $ConfigPath) {
    Get-Content -LiteralPath $ConfigPath | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) {
            return
        }
        $parts = $line.Split("=", 2)
        [Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1].Trim(), "Process")
    }
}

if ($HostName) {
    $env:RS_AGENT_HOST = $HostName
}
if ($Port -gt 0) {
    $env:RS_AGENT_PORT = [string]$Port
}

$hostArg = if ($env:RS_AGENT_HOST) { $env:RS_AGENT_HOST } else { "0.0.0.0" }
$portArg = if ($env:RS_AGENT_PORT) { [int]$env:RS_AGENT_PORT } else { 8000 }
$logFile = if ($env:RS_AGENT_LOG_FILE) { $env:RS_AGENT_LOG_FILE } else { "logs/server/server.log" }
$logDir = Split-Path -Parent $logFile

if ($logDir) {
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
}

"Starting random signal agent at http://${hostArg}:${portArg}" | Tee-Object -FilePath $logFile
python .\server.py --host $hostArg --port $portArg 2>&1 | Tee-Object -FilePath $logFile -Append
