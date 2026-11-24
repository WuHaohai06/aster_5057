param(
    [string]$StartDate = "2016-11-24",
    [string]$EndDate = "2026-11-24"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $PSScriptRoot "resolve_python.ps1")
$Python = Resolve-AsterPython -EnvironmentName "aster_5057_whh" -OverrideVariable "ASTER_DATA_PYTHON"
$RunRoot = Join-Path $ProjectRoot "run\factor_input_download"
New-Item -ItemType Directory -Force -Path $RunRoot | Out-Null

$PreviousPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = Join-Path $ProjectRoot "src"
try {
    $Process = Start-Process `
        -FilePath $Python `
        -ArgumentList @(
            "-u", "-m", "aster_data.factor_input_download",
            "--project-root", $ProjectRoot,
            "--start", $StartDate,
            "--end", $EndDate,
            "--request-delay", "2",
            "--rate-limit-delay", "300"
        ) `
        -WorkingDirectory $ProjectRoot `
        -RedirectStandardOutput (Join-Path $RunRoot "background.stdout.log") `
        -RedirectStandardError (Join-Path $RunRoot "background.stderr.log") `
        -WindowStyle Hidden `
        -PassThru
}
finally {
    $env:PYTHONPATH = $PreviousPythonPath
}

[pscustomobject]@{
    Pid = $Process.Id
    StatusPath = (Join-Path $RunRoot "status.json")
    LogPath = (Join-Path $ProjectRoot "logs\factor_input_download.log")
    OutputRoot = (Join-Path $ProjectRoot "data\raw\factor_inputs")
}
