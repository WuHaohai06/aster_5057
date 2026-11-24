param(
    [string]$Model = "deepseek-flash",
    [string]$BaseUrl = "https://api.deepseek.com"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$QuantaRoot = Join-Path $ProjectRoot "vendor\quantaalpha-b7ceb27"
. (Join-Path $PSScriptRoot "resolve_python.ps1")
$Python = Resolve-AsterPython -EnvironmentName "aster_5057_quantaalpha" -OverrideVariable "ASTER_QUANTA_PYTHON"
$SecretPath = Join-Path $ProjectRoot "run\secrets\deepseek_api_key.dpapi"

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
        throw "Set DEEPSEEK_API_KEY or create the local DPAPI credential first."
    }
}

$env:OPENAI_BASE_URL = $BaseUrl
$env:CHAT_MODEL = $Model
$env:REASONING_MODEL = $Model
$env:EMBEDDING_API_KEY = $env:OPENAI_API_KEY
$env:EMBEDDING_BASE_URL = $BaseUrl
$env:LOG_LLM_CHAT_CONTENT = "false"
$env:MAX_RETRY = "1"
$env:CHAT_STREAM = "false"
$env:PYTHONPATH = "$QuantaRoot;$ProjectRoot\src"
try {
    & $Python (Join-Path $ProjectRoot "scripts\validate_quantaalpha_llm.py")
    if ($LASTEXITCODE -ne 0) {
        throw "DeepSeek connectivity check failed with exit code $LASTEXITCODE"
    }
}
finally {
    $env:OPENAI_API_KEY = $null
    $env:EMBEDDING_API_KEY = $null
}
