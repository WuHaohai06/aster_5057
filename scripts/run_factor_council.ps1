param(
    [Parameter(Mandatory=$true)][string]$PacketPath,
    [string]$OutputRoot = "",
    [string]$Model = "deepseek-flash",
    [string]$BaseUrl = "https://api.deepseek.com",
    [int]$MaxTokens = 20000
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $PSScriptRoot "resolve_python.ps1")
$Python = Resolve-AsterPython -EnvironmentName "aster_5057_quantaalpha" -OverrideVariable "ASTER_QUANTA_PYTHON"
$SecretPath = Join-Path $ProjectRoot "run\secrets\deepseek_api_key.dpapi"
$ResolvedPacket = (Resolve-Path $PacketPath).Path
if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path $ProjectRoot "data\council\runs"
}

$PreviousPythonPath = $env:PYTHONPATH
$PreviousOpenAIKey = $env:OPENAI_API_KEY
try {
    if ([string]::IsNullOrWhiteSpace($env:OPENAI_API_KEY)) {
        if (-not [string]::IsNullOrWhiteSpace($env:DEEPSEEK_API_KEY)) {
            $env:OPENAI_API_KEY = $env:DEEPSEEK_API_KEY
        }
        elseif (Test-Path -LiteralPath $SecretPath) {
            $SecureKey = Get-Content -LiteralPath $SecretPath -Raw | ConvertTo-SecureString
            $KeyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureKey)
            try {
                $env:OPENAI_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($KeyPointer)
            }
            finally {
                [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($KeyPointer)
            }
        }
        else {
            throw "Set DEEPSEEK_API_KEY or create the DPAPI credential first."
        }
    }
    $env:PYTHONPATH = Join-Path $ProjectRoot "src"
    & $Python -m aster_council run `
        --packet $ResolvedPacket `
        --output-root $OutputRoot `
        --model $Model `
        --base-url $BaseUrl `
        --max-tokens $MaxTokens
    if ($LASTEXITCODE -ne 0) {
        throw "Factor Council failed with exit code $LASTEXITCODE"
    }
}
finally {
    $env:PYTHONPATH = $PreviousPythonPath
    $env:OPENAI_API_KEY = $PreviousOpenAIKey
}
