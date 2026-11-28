param(
    [string]$RunId = "",
    [int]$StepN = 5,
    [string]$Model = "deepseek-flash",
    [string]$BaseUrl = "https://api.deepseek.com"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BatchScript = Join-Path $PSScriptRoot "run_factors_directory_mining_batch.ps1"
if ([string]::IsNullOrWhiteSpace($RunId)) {
    $RunId = "factors_directory_pv_" + (Get-Date -Format "yyyyMMdd_HHmmss")
}
$RunRoot = Join-Path $ProjectRoot "run\factor_mining_batch\$RunId"
New-Item -ItemType Directory -Force -Path $RunRoot | Out-Null
$Process = Start-Process -FilePath "powershell.exe" -ArgumentList @(
    "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $BatchScript,
    "-RunId", $RunId, "-StepN", $StepN, "-Model", $Model, "-BaseUrl", $BaseUrl
) -WorkingDirectory $ProjectRoot `
  -RedirectStandardOutput (Join-Path $RunRoot "batch.stdout.log") `
  -RedirectStandardError (Join-Path $RunRoot "batch.stderr.log") `
  -WindowStyle Hidden -PassThru

[pscustomobject]@{
    Pid = $Process.Id
    RunId = $RunId
    StatusPath = (Join-Path $RunRoot "status.json")
    Stdout = (Join-Path $RunRoot "batch.stdout.log")
    Stderr = (Join-Path $RunRoot "batch.stderr.log")
}
