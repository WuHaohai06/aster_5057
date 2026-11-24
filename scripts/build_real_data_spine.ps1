param(
    [string]$EndDate = "2026-11-24",
    [string]$OfficialAdjustments = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $PSScriptRoot "resolve_python.ps1")
$Python = Resolve-AsterPython -EnvironmentName "aster_5057_whh" -OverrideVariable "ASTER_DATA_PYTHON"
$PreviousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = Join-Path $ProjectRoot "src"
    $UniverseArguments = @(
        (Join-Path $ProjectRoot "scripts\build_csi500_pit_universe.py"),
        "--snapshot-root", (Join-Path $ProjectRoot "data\raw\qlib_full\csi500_snapshots"),
        "--output-root", (Join-Path $ProjectRoot "data\curated\csi500_universe"),
        "--requested-end", $EndDate
    )
    if (-not [string]::IsNullOrWhiteSpace($OfficialAdjustments)) {
        $UniverseArguments += @("--official-adjustments", (Resolve-Path $OfficialAdjustments).Path)
    }
    & $Python @UniverseArguments
    if ($LASTEXITCODE -ne 0) { throw "PIT universe build failed" }

    & $Python (Join-Path $ProjectRoot "scripts\normalize_market_store.py") `
        --akshare-root (Join-Path $ProjectRoot "data\raw\akshare_daily") `
        --yahoo-root (Join-Path $ProjectRoot "data\raw\qlib_full\yahoo_daily") `
        --universe-intervals (Join-Path $ProjectRoot "data\curated\csi500_universe\intervals.parquet") `
        --output-root (Join-Path $ProjectRoot "data\curated\market")
    if ($LASTEXITCODE -ne 0) { throw "Canonical market build failed" }

    $IcPath = Join-Path $ProjectRoot "data\curated\ic_futures\continuous.parquet"
    [pscustomobject]@{
        Status = if (Test-Path $IcPath) { "ready" } else { "waiting_for_ic_download" }
        Market = (Join-Path $ProjectRoot "data\curated\market\daily.parquet")
        Universe = (Join-Path $ProjectRoot "data\curated\csi500_universe\intervals.parquet")
        IcFutures = $IcPath
    } | ConvertTo-Json
}
finally {
    $env:PYTHONPATH = $PreviousPythonPath
}
