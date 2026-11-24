param(
    [string]$StartDate = (Get-Date).AddYears(-10).ToString("yyyy-MM-dd"),
    [string]$EndDate = (Get-Date).ToString("yyyy-MM-dd")
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $PSScriptRoot "resolve_python.ps1")
$Python = Resolve-AsterPython -EnvironmentName "aster_5057_whh" -OverrideVariable "ASTER_DATA_PYTHON"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python executable not found: $Python"
}

$RunRoot = Join-Path $ProjectRoot "run\full_download"
New-Item -ItemType Directory -Force -Path $RunRoot | Out-Null
$Stdout = Join-Path $RunRoot "background.stdout.log"
$Stderr = Join-Path $RunRoot "background.stderr.log"

$PreviousPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = Join-Path $ProjectRoot "src"
try {
    $Process = Start-Process `
        -FilePath $Python `
        -ArgumentList @(
            "-u", "-m", "aster_data.full_download",
            "--project-root", $ProjectRoot,
            "--start", $StartDate,
            "--end", $EndDate
        ) `
        -WorkingDirectory $ProjectRoot `
        -RedirectStandardOutput $Stdout `
        -RedirectStandardError $Stderr `
        -WindowStyle Hidden `
        -PassThru
}
finally {
    $env:PYTHONPATH = $PreviousPythonPath
}

[pscustomobject]@{
    Pid = $Process.Id
    StartDate = $StartDate
    EndDate = $EndDate
    StatusPath = (Join-Path $RunRoot "status.json")
    PipelineLog = (Join-Path $ProjectRoot "logs\full_download.log")
    StdoutLog = $Stdout
    StderrLog = $Stderr
}

