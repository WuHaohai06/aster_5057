param(
    [Parameter(Mandatory=$true)][string]$Direction,
    [int]$StepN = 5,
    [string]$ExperimentId = "",
    [string]$Model = "deepseek-flash",
    [string]$BaseUrl = "https://api.deepseek.com",
    [string]$ConfigPath = "",
    [string]$ResumePath = ""
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
        throw "Set DEEPSEEK_API_KEY or create the local DPAPI credential with scripts\set_quantaalpha_secret.ps1."
    }
}

$env:OPENAI_BASE_URL = $BaseUrl
$env:CHAT_MODEL = $Model
$env:REASONING_MODEL = $Model
# QuantaAlpha initializes this client even when the factor workflow does not
# request embeddings. DeepSeek chat is not used as an embedding endpoint.
$env:EMBEDDING_API_KEY = $env:OPENAI_API_KEY
$env:EMBEDDING_BASE_URL = $BaseUrl
$env:LOG_LLM_CHAT_CONTENT = "false"
$env:QLIB_DATA_DIR = Join-Path $ProjectRoot "data\quantalpha\qlib\cn_data"
$env:QLIB_PROVIDER_URI = $env:QLIB_DATA_DIR
$env:DATA_RESULTS_DIR = Join-Path $ProjectRoot "data\quantalpha\results"
$env:FACTOR_CoSTEER_DATA_FOLDER = Join-Path $ProjectRoot "data\quantalpha\factor_implementation_source_data"
$env:FACTOR_CoSTEER_DATA_FOLDER_DEBUG = Join-Path $ProjectRoot "data\quantalpha\factor_implementation_source_data_debug"
$env:FACTOR_CoSTEER_PYTHON_BIN = $Python
$env:USE_LOCAL = "true"
$env:ASTER_WINDOWS_LINK_FALLBACK = "1"
$env:ASTER_LOCAL_EMBEDDINGS = "1"
$env:ASTER_REDACT_LOG_SECRETS = "1"
# RD-Agent's live-output path uses select.poll(), which is unavailable on
# Windows. Buffered capture preserves logs and return codes without that API.
$env:LIVE_OUTPUT = "false"
# MLflow 3.x disables its legacy file tracking store unless explicitly
# allowed; Qlib 0.9.7 still creates a local file-backed recorder.
$env:MLFLOW_ALLOW_FILE_STORE = "true"
$MlflowDbPath = (Join-Path $ProjectRoot "run\mlflow_quantaalpha.db").Replace("\", "/")
$env:MLFLOW_TRACKING_URI = "sqlite:///$MlflowDbPath"
$env:MLFLOW_DISABLE_AGENT_HINT = "1"
$env:PYTHONPATH = "$QuantaRoot;$ProjectRoot\src"
if ([string]::IsNullOrWhiteSpace($ExperimentId)) {
    $ExperimentId = "aster_" + (Get-Date -Format "yyyyMMdd_HHmmss")
}
$env:EXPERIMENT_ID = $ExperimentId
$env:WORKSPACE_PATH = Join-Path $env:DATA_RESULTS_DIR "workspace_$ExperimentId"
$env:PICKLE_CACHE_FOLDER_PATH_STR = Join-Path $env:DATA_RESULTS_DIR "pickle_cache_$ExperimentId"
$env:FACTOR_LIBRARY_SUFFIX = $ExperimentId
if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
    $ConfigPath = Join-Path $ProjectRoot "config\quantaalpha\experiment_aster_minimal.yaml"
}
else {
    $ConfigPath = (Resolve-Path $ConfigPath).Path
}
$ResolvedResumePath = ""
if (-not [string]::IsNullOrWhiteSpace($ResumePath)) {
    $ResolvedResumePath = (Resolve-Path -LiteralPath $ResumePath).Path
}

Push-Location $QuantaRoot
try {
    $MineArgs = @(
        "-m", "quantaalpha.cli", "mine",
        "--direction", $Direction,
        "--step_n", $StepN,
        "--config_path", $ConfigPath
    )
    if (-not [string]::IsNullOrWhiteSpace($ResolvedResumePath)) {
        $MineArgs += @("--path", $ResolvedResumePath)
    }
    & $Python @MineArgs
    if ($LASTEXITCODE -ne 0) {
        throw "QuantaAlpha exited with code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
    $env:OPENAI_API_KEY = $null
    $env:EMBEDDING_API_KEY = $null
}
