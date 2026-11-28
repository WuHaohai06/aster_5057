param(
    [Parameter(Mandatory=$true)][string]$StartDate,
    [Parameter(Mandatory=$true)][string]$EndDate,
    [string]$OutputRoot = "",
    [string]$FactorDecision = "",
    [string]$FactorSchedule = "",
    [string]$PortfolioDecision = "",
    [string]$PortfolioSchedule = "",
    [string]$FactorCatalog = "",
    [string]$IndustrySnapshot = "",
    [string]$IndustryBenchmark = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $PSScriptRoot "resolve_python.ps1")
$Python = Resolve-AsterPython -EnvironmentName "aster_5057_quantaalpha" -OverrideVariable "ASTER_QUANTA_PYTHON"
if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path $ProjectRoot "data\portfolio\real_runs\${StartDate}_${EndDate}"
}
$Arguments = @(
    (Join-Path $ProjectRoot "scripts\run_real_pipeline.py"),
    "--market", (Join-Path $ProjectRoot "data\curated\market\daily.parquet"),
    "--ic-futures", (Join-Path $ProjectRoot "data\curated\ic_futures\continuous.parquet"),
    "--output-root", $OutputRoot,
    "--start", $StartDate,
    "--end", $EndDate
)
if (-not [string]::IsNullOrWhiteSpace($FactorDecision)) {
    $Arguments += @("--factor-decision", (Resolve-Path $FactorDecision).Path)
}
if (-not [string]::IsNullOrWhiteSpace($FactorSchedule)) {
    $Arguments += @("--factor-schedule", (Resolve-Path $FactorSchedule).Path)
}
if (-not [string]::IsNullOrWhiteSpace($PortfolioDecision)) {
    $Arguments += @("--portfolio-decision", (Resolve-Path $PortfolioDecision).Path)
}
if (-not [string]::IsNullOrWhiteSpace($PortfolioSchedule)) {
    $Arguments += @("--portfolio-schedule", (Resolve-Path $PortfolioSchedule).Path)
}
if ([string]::IsNullOrWhiteSpace($FactorCatalog)) {
    $DefaultFactorCatalog = Join-Path $ProjectRoot "data\curated\factor_library\catalog.json"
    if (Test-Path -LiteralPath $DefaultFactorCatalog) { $FactorCatalog = $DefaultFactorCatalog }
}
if (-not [string]::IsNullOrWhiteSpace($FactorCatalog)) {
    $Arguments += @("--factor-catalog", (Resolve-Path $FactorCatalog).Path)
}
$DefaultIndustrySnapshot = Join-Path $ProjectRoot "data\curated\industry_snapshot\latest.parquet"
$DefaultIndustryBenchmark = Join-Path $ProjectRoot "data\curated\industry_snapshot\benchmark_weights.parquet"
if ([string]::IsNullOrWhiteSpace($IndustrySnapshot) -and (Test-Path -LiteralPath $DefaultIndustrySnapshot)) {
    $IndustrySnapshot = $DefaultIndustrySnapshot
}
if ([string]::IsNullOrWhiteSpace($IndustryBenchmark) -and (Test-Path -LiteralPath $DefaultIndustryBenchmark)) {
    $IndustryBenchmark = $DefaultIndustryBenchmark
}
if (-not [string]::IsNullOrWhiteSpace($IndustrySnapshot)) {
    $Arguments += @("--industry-snapshot", (Resolve-Path $IndustrySnapshot).Path)
}
if (-not [string]::IsNullOrWhiteSpace($IndustryBenchmark)) {
    $Arguments += @("--industry-benchmark", (Resolve-Path $IndustryBenchmark).Path)
}
$PreviousPythonPath = $env:PYTHONPATH
$PreviousOmpThreads = $env:OMP_NUM_THREADS
$PreviousMklThreads = $env:MKL_NUM_THREADS
$PreviousOpenBlasThreads = $env:OPENBLAS_NUM_THREADS
try {
    $env:PYTHONPATH = Join-Path $ProjectRoot "src"
    $env:OMP_NUM_THREADS = "1"
    $env:MKL_NUM_THREADS = "1"
    $env:OPENBLAS_NUM_THREADS = "1"
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Real Aster pipeline failed" }
}
finally {
    $env:PYTHONPATH = $PreviousPythonPath
    $env:OMP_NUM_THREADS = $PreviousOmpThreads
    $env:MKL_NUM_THREADS = $PreviousMklThreads
    $env:OPENBLAS_NUM_THREADS = $PreviousOpenBlasThreads
}
