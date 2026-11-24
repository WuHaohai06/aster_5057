param(
    [string]$WorkRoot = "",
    [string]$Model = "deepseek-flash",
    [string]$BaseUrl = "https://api.deepseek.com"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $PSScriptRoot "resolve_python.ps1")
$Python = Resolve-AsterPython -EnvironmentName "aster_5057_quantaalpha" -OverrideVariable "ASTER_QUANTA_PYTHON"
if ([string]::IsNullOrWhiteSpace($WorkRoot)) {
    $WorkRoot = Join-Path $ProjectRoot "run\portfolio_full_chain_smoke"
}
$WorkRoot = [System.IO.Path]::GetFullPath($WorkRoot)
$BaselineRoot = Join-Path $WorkRoot "baseline"
$PacketPath = Join-Path $WorkRoot "packet.json"
$CouncilRoot = Join-Path $WorkRoot "council_runs"
$ReplayRoot = Join-Path $WorkRoot "decision_replay"

$PreviousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = Join-Path $ProjectRoot "src"
    & $Python (Join-Path $ProjectRoot "scripts\run_portfolio_smoke.py") `
        --output-root $BaselineRoot --profile balanced | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Baseline portfolio smoke failed" }

    & $Python (Join-Path $ProjectRoot "scripts\build_portfolio_council_smoke.py") `
        --portfolio-smoke-root $BaselineRoot --output $PacketPath | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Portfolio Council packet build failed" }

    $CouncilJson = & powershell -NoProfile -ExecutionPolicy Bypass `
        -File (Join-Path $ProjectRoot "scripts\run_portfolio_council.ps1") `
        -PacketPath $PacketPath -OutputRoot $CouncilRoot -Model $Model -BaseUrl $BaseUrl
    if ($LASTEXITCODE -ne 0) { throw "Portfolio Council failed" }
    $Council = $CouncilJson | Out-String | ConvertFrom-Json
    $DecisionPath = Join-Path $Council.run_dir "decision.json"

    & $Python (Join-Path $ProjectRoot "scripts\replay_synthetic_portfolio_decision.py") `
        --decision $DecisionPath --output-root $ReplayRoot | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Council decision replay failed" }

    [pscustomobject]@{
        Status = "complete"
        SelectedProfile = $Council.selected_profile_id
        FallbackUsed = $Council.fallback_used
        PacketPath = $PacketPath
        CouncilRunDir = $Council.run_dir
        ReplayRoot = $ReplayRoot
    } | ConvertTo-Json -Depth 3
}
finally {
    $env:PYTHONPATH = $PreviousPythonPath
}
