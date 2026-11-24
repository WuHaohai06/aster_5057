param(
    [switch]$Smoke,
    [switch]$SkipQlib
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $PSScriptRoot "resolve_python.ps1")
$Python = Resolve-AsterPython -EnvironmentName "aster_5057_quantaalpha" -OverrideVariable "ASTER_QUANTA_PYTHON"
$PreviousPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = Join-Path $ProjectRoot "src"
try {
    $Arguments = @(
        "-m", "aster_quantalpha.data_adapter",
        "--project-root", $ProjectRoot
    )
    if ($Smoke) {
        $Arguments += @(
            "--source-root", (Join-Path $ProjectRoot "data\raw\qlib_collector\yahoo_daily"),
            "--limit-files", "1",
            "--output-root", (Join-Path $ProjectRoot "data\quantalpha\smoke")
        )
    }
    if ($SkipQlib) {
        $Arguments += "--skip-qlib"
    }
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "QuantaAlpha data preparation failed with exit code $LASTEXITCODE"
    }
}
finally {
    $env:PYTHONPATH = $PreviousPythonPath
}
