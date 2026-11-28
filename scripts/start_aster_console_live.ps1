[CmdletBinding()]
param(
    [string]$ListenHost = "127.0.0.1",
    [ValidateRange(1, 65535)][int]$Port = 8765,
    [switch]$NoBuild,
    [switch]$Foreground
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $PSScriptRoot "resolve_python.ps1")
$Python = Resolve-AsterPython -EnvironmentName "aster_5057_whh" -OverrideVariable "ASTER_CONSOLE_PYTHON"
$Frontend = Join-Path $ProjectRoot "apps\aster-console"
$Runtime = Join-Path $ProjectRoot "run\aster_console"
New-Item -ItemType Directory -Force -Path $Runtime | Out-Null
$SecretPath = Join-Path $ProjectRoot "run\secrets\deepseek_api_key.dpapi"
if ([string]::IsNullOrWhiteSpace($env:DEEPSEEK_API_KEY) -and (Test-Path -LiteralPath $SecretPath)) {
    $SecureKey = Get-Content -LiteralPath $SecretPath -Raw | ConvertTo-SecureString
    $KeyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureKey)
    try { $env:DEEPSEEK_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($KeyPointer) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($KeyPointer) }
}
$env:OPENAI_BASE_URL = "https://api.deepseek.com"
$env:CHAT_MODEL = "deepseek-flash"

$PreviousErrorAction = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $Python -c "import fastapi, uvicorn, openai" 2>$null
$DependencyProbeExitCode = $LASTEXITCODE
$ErrorActionPreference = $PreviousErrorAction
if ($DependencyProbeExitCode -ne 0) {
    & $Python -m pip install -r (Join-Path $ProjectRoot "requirements-console.txt")
    if ($LASTEXITCODE -ne 0) { throw "Failed to install console API dependencies." }
}

if (-not $NoBuild) {
    Push-Location $Frontend
    try {
        & npm run build
        if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }
    }
    finally { Pop-Location }
}

$Arguments = @(
    "-m", "uvicorn", "aster_console.api:app",
    "--app-dir", (Join-Path $ProjectRoot "src"),
    "--host", $ListenHost,
    "--port", $Port.ToString(),
    "--no-access-log"
)
$HealthUrl = "http://${ListenHost}:$Port/api/health"

try {
    $ExistingHealth = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 2
    if ($ExistingHealth.status -eq "ok") {
        $ExistingPid = $null
        $PidFile = Join-Path $Runtime "server.pid"
        if (Test-Path -LiteralPath $PidFile) { $ExistingPid = (Get-Content -LiteralPath $PidFile -Raw).Trim() }
        [pscustomobject]@{
            state = "already_running"
            pid = $ExistingPid
            url = "http://${ListenHost}:$Port/"
            health = $HealthUrl
            schema = $ExistingHealth.schema
            version = $ExistingHealth.version
        }
        exit 0
    }
}
catch {
    # No healthy console owns the requested address, so start one below.
}

if ($Foreground) {
    Push-Location $ProjectRoot
    try { & $Python @Arguments }
    finally { Pop-Location }
    exit $LASTEXITCODE
}

$Stdout = Join-Path $Runtime "server.stdout.log"
$Stderr = Join-Path $Runtime "server.stderr.log"
$Process = Start-Process -FilePath $Python -ArgumentList $Arguments -WorkingDirectory $ProjectRoot `
    -RedirectStandardOutput $Stdout -RedirectStandardError $Stderr -WindowStyle Hidden -PassThru
Set-Content -LiteralPath (Join-Path $Runtime "server.pid") -Value $Process.Id -Encoding ascii

$Healthy = $false
for ($Attempt = 0; $Attempt -lt 20; $Attempt++) {
    Start-Sleep -Milliseconds 500
    try {
        $Health = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 2
        if ($Health.status -eq "ok") { $Healthy = $true; break }
    }
    catch {
        if ($Process.HasExited) { break }
    }
}
if (-not $Healthy) {
    if (-not $Process.HasExited) { Stop-Process -Id $Process.Id }
    throw "Console failed its health check. Inspect $Stderr"
}

[pscustomobject]@{
    state = "running"
    pid = $Process.Id
    url = "http://${ListenHost}:$Port/"
    health = $HealthUrl
    schema = $Health.schema
    version = $Health.version
}

