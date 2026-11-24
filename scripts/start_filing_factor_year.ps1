param(
    [int]$FiscalYear = 2025,
    [int]$ParseWorkers = 6,
    [int]$LlmWorkers = 8,
    [string]$Model = "deepseek-flash",
    [string]$BaseUrl = "https://api.deepseek.com"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $PSScriptRoot "resolve_python.ps1")
$Python = Resolve-AsterPython -EnvironmentName "aster_5057_quantaalpha" -OverrideVariable "ASTER_QUANTA_PYTHON"
$RunRoot = Join-Path $ProjectRoot "run\filing_factor_$FiscalYear"
$SecretPath = Join-Path $ProjectRoot "run\secrets\deepseek_api_key.dpapi"
New-Item -ItemType Directory -Force -Path $RunRoot | Out-Null

$PreviousPythonPath = $env:PYTHONPATH
$PreviousKey = $env:DEEPSEEK_API_KEY
try {
    if ([string]::IsNullOrWhiteSpace($env:DEEPSEEK_API_KEY)) {
        if (-not (Test-Path -LiteralPath $SecretPath)) {
            throw "Set DEEPSEEK_API_KEY or create the DPAPI credential first."
        }
        $SecureKey = Get-Content -LiteralPath $SecretPath -Raw | ConvertTo-SecureString
        $KeyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureKey)
        try { $env:DEEPSEEK_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($KeyPointer) }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($KeyPointer) }
    }
    $env:PYTHONPATH = Join-Path $ProjectRoot "src"
    $Process = Start-Process -FilePath $Python -ArgumentList @(
        "-u", "-m", "aster_data.filing_factor_batch",
        "--project-root", $ProjectRoot,
        "--year", $FiscalYear,
        "--parse-workers", $ParseWorkers,
        "--llm-workers", $LlmWorkers,
        "--model", $Model,
        "--base-url", $BaseUrl
    ) -WorkingDirectory $ProjectRoot `
      -RedirectStandardOutput (Join-Path $RunRoot "background.stdout.log") `
      -RedirectStandardError (Join-Path $RunRoot "background.stderr.log") `
      -WindowStyle Hidden -PassThru
}
finally {
    $env:PYTHONPATH = $PreviousPythonPath
    $env:DEEPSEEK_API_KEY = $PreviousKey
}

[pscustomobject]@{
    Pid = $Process.Id
    FiscalYear = $FiscalYear
    StatusPath = (Join-Path $RunRoot "status.json")
    LogPath = (Join-Path $ProjectRoot "logs\filing_factor_$FiscalYear.log")
}
