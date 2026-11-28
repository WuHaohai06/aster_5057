param(
    [int]$Workers = 4,
    [int]$Limit = 0
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
$env:PYTHONPATH = Join-Path $ProjectRoot "src"

$Arguments = @(
    (Join-Path $ProjectRoot "scripts\translate_council_reports.py"),
    "--workers", $Workers
)
if ($Limit -gt 0) { $Arguments += @("--limit", $Limit) }

& $Python @Arguments
exit $LASTEXITCODE
