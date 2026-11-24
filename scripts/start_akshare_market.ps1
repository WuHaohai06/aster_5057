param(
    [string]$StartDate = "2016-11-24",
    [string]$EndDate = "2026-11-24",
    [ValidateSet("hfq", "qfq", "")][string]$Adjust = "hfq",
    [double]$RequestDelay = 2.0,
    [double]$RateLimitDelay = 300.0,
    [int]$Limit = 0
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $PSScriptRoot "resolve_python.ps1")
$Python = Resolve-AsterPython -EnvironmentName "aster_5057_whh" -OverrideVariable "ASTER_DATA_PYTHON"
$RunRoot = Join-Path $ProjectRoot "run\akshare_market"
New-Item -ItemType Directory -Force -Path $RunRoot | Out-Null
$Arguments = @(
    "-u", "-m", "aster_data.akshare_market",
    "--project-root", $ProjectRoot,
    "--start", $StartDate,
    "--end", $EndDate,
    "--adjust", $Adjust,
    "--request-delay", [string]$RequestDelay,
    "--rate-limit-delay", [string]$RateLimitDelay
)
if ($Limit -gt 0) { $Arguments += @("--limit", [string]$Limit) }

$PreviousPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = Join-Path $ProjectRoot "src"
try {
    $Process = Start-Process -FilePath $Python -ArgumentList $Arguments `
        -WorkingDirectory $ProjectRoot `
        -RedirectStandardOutput (Join-Path $RunRoot "background.stdout.log") `
        -RedirectStandardError (Join-Path $RunRoot "background.stderr.log") `
        -WindowStyle Hidden -PassThru
}
finally {
    $env:PYTHONPATH = $PreviousPythonPath
}

[pscustomobject]@{
    Pid = $Process.Id
    StatusPath = (Join-Path $RunRoot "status.json")
    LogPath = (Join-Path $ProjectRoot "logs\akshare_market.log")
}
