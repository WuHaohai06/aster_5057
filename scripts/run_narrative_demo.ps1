param(
    [string]$RunId = "narrative_v1",
    [double]$Beta = 0.30,
    [double]$ActiveTilt = 0.05,
    [double]$HitRate = 0.70,
    [string]$WindowStart = "2022-01-01",
    [ValidateSet("quarterly", "monthly")][string]$Frequency = "quarterly",
    [string]$NewsRoot = "",
    [string[]]$NeutralMonths = @(),
    [switch]$ReuseNews
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $PSScriptRoot "resolve_python.ps1")
$Python = Resolve-AsterPython -EnvironmentName "aster_5057_quantaalpha" -OverrideVariable "ASTER_QUANTA_PYTHON"
$SecretPath = Join-Path $ProjectRoot "run\secrets\deepseek_api_key.dpapi"

if ([string]::IsNullOrWhiteSpace($env:DEEPSEEK_API_KEY)) {
    if (Test-Path -LiteralPath $SecretPath) {
        $SecureKey = Get-Content -LiteralPath $SecretPath -Raw | ConvertTo-SecureString
        $KeyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureKey)
        try { $env:DEEPSEEK_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($KeyPointer) }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($KeyPointer) }
    }
    else {
        throw "Set DEEPSEEK_API_KEY or create the local DPAPI credential first."
    }
}
$env:OPENAI_API_KEY = $env:DEEPSEEK_API_KEY
$env:OPENAI_BASE_URL = "https://api.deepseek.com"
$env:PYTHONPATH = Join-Path $ProjectRoot "src"

$Arguments = @(
    (Join-Path $ProjectRoot "scripts\build_narrative_demo.py"),
    "--run-id", $RunId,
    "--beta", $Beta,
    "--active-tilt", $ActiveTilt,
    "--hit-rate", $HitRate,
    "--window-start", $WindowStart,
    "--frequency", $Frequency
)
if ($NewsRoot) { $Arguments += @("--news-root", $NewsRoot) }
foreach ($m in $NeutralMonths) { $Arguments += @("--neutral-month", $m) }
if ($ReuseNews) { $Arguments += "--reuse-news" }

& $Python @Arguments
if ($LASTEXITCODE -ne 0) { throw "Narrative demo failed with exit code $LASTEXITCODE" }
