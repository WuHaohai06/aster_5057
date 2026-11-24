param(
    [string]$Environment = "aster_5057_whh",
    [Alias("StartDate")]
    [string]$Start = "2016-01-01",
    [Alias("EndDate")]
    [string]$End = "2026-11-24",
    [string]$ReportTypes = "annual",
    [switch]$VerifyExchange
)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$logRoot = Join-Path $projectRoot "data\raw\filings\logs"
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$stdout = Join-Path $logRoot "filings_$stamp.out.log"
$stderr = Join-Path $logRoot "filings_$stamp.err.log"
$arguments = @(
    "run", "-n", $Environment, "python", (Join-Path $PSScriptRoot "download_filings_bulk.py"),
    "--project-root", $projectRoot,
    "--universe", (Join-Path $projectRoot "data\curated\csi500_universe\intervals.parquet"),
    "--start", $Start, "--end", $End, "--report-types", $ReportTypes
)
if ($VerifyExchange) { $arguments += "--verify-exchange" }
$process = Start-Process -FilePath "conda" -ArgumentList $arguments -WorkingDirectory $projectRoot `
    -RedirectStandardOutput $stdout -RedirectStandardError $stderr -WindowStyle Hidden -PassThru
@{ pid = $process.Id; stdout = $stdout; stderr = $stderr } | ConvertTo-Json
