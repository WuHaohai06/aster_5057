param(
    [string]$StartDate = "2016-11-24",
    [string]$EndDate = "2026-11-24",
    [int]$MaxWorkers = 2
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $PSScriptRoot "resolve_python.ps1")
$Python = Resolve-AsterPython -EnvironmentName "aster_5057_whh" -OverrideVariable "ASTER_DATA_PYTHON"
$RunRoot = Join-Path $ProjectRoot "run\ic_futures"
New-Item -ItemType Directory -Force -Path $RunRoot | Out-Null
$PreviousPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = Join-Path $ProjectRoot "src"
try {
    $Process = Start-Process -FilePath $Python -ArgumentList @(
        "-u", "-m", "aster_data.ic_futures",
        "--start", $StartDate,
        "--end", $EndDate,
        "--archive-root", (Join-Path $ProjectRoot "data\raw\cffex\monthly"),
        "--output-root", (Join-Path $ProjectRoot "data\curated\ic_futures"),
        "--status-path", (Join-Path $RunRoot "status.json"),
        "--lock-path", (Join-Path $RunRoot "pipeline.lock"),
        "--max-workers", [string]$MaxWorkers,
        "--allow-missing-months"
    ) -WorkingDirectory $ProjectRoot `
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
    OutputRoot = (Join-Path $ProjectRoot "data\curated\ic_futures")
}
