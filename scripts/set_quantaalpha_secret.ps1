param()

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$SecretDirectory = Join-Path $ProjectRoot "run\secrets"
$SecretPath = Join-Path $SecretDirectory "deepseek_api_key.dpapi"

$SecureKey = Read-Host "DeepSeek API key" -AsSecureString
if ($SecureKey.Length -eq 0) {
    throw "The API key cannot be empty."
}
New-Item -ItemType Directory -Force -Path $SecretDirectory | Out-Null
$SecureKey | ConvertFrom-SecureString | Set-Content -LiteralPath $SecretPath -Encoding ascii -NoNewline
Write-Output "Encrypted credential saved for the current Windows user at $SecretPath"
