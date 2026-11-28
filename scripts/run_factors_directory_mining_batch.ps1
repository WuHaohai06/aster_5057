param(
    [string]$RunId = "",
    [string]$ConfigPath = "",
    [int]$StepN = 5,
    [string]$Model = "deepseek-flash",
    [string]$BaseUrl = "https://api.deepseek.com"
)

$ErrorActionPreference = "Continue"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Runner = Join-Path $PSScriptRoot "run_quantaalpha.ps1"
if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
    $ConfigPath = Join-Path $ProjectRoot "config\quantaalpha\factors_directory_price_volume_v2.json"
}
$ConfigPath = (Resolve-Path -LiteralPath $ConfigPath).Path
$Batch = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
$Jobs = @($Batch.jobs)
if ($Jobs.Count -eq 0) { throw "Mining batch has no jobs: $ConfigPath" }
if ([string]::IsNullOrWhiteSpace($RunId)) {
    $RunId = "factors_directory_pv_" + (Get-Date -Format "yyyyMMdd_HHmmss")
}
$RunRoot = Join-Path $ProjectRoot "run\factor_mining_batch\$RunId"
New-Item -ItemType Directory -Force -Path $RunRoot | Out-Null
$StatusPath = Join-Path $RunRoot "status.json"

function Write-Status {
    param([string]$State, [int]$JobIndex, [string]$CurrentId, [array]$Results)
    $Payload = [ordered]@{
        run_id = $RunId
        pid = $PID
        state = $State
        batch_version = $Batch.version
        config_path = $ConfigPath
        step_n = $StepN
        jobs_total = $Jobs.Count
        job_index = $JobIndex
        current_id = $CurrentId
        results = $Results
        updated_at = (Get-Date).ToString("o")
    }
    $Temporary = "$StatusPath.tmp"
    $Payload | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $Temporary -Encoding UTF8
    Move-Item -LiteralPath $Temporary -Destination $StatusPath -Force
}

$Results = @()
Write-Status -State "running" -JobIndex 0 -CurrentId "starting" -Results $Results
for ($Index = 0; $Index -lt $Jobs.Count; $Index++) {
    $Job = $Jobs[$Index]
    $ExperimentId = "aster_fd_{0}_{1}" -f $Job.id.ToLowerInvariant(), (Get-Date -Format "yyyyMMdd_HHmmss")
    $LogPath = Join-Path $RunRoot ("{0}_{1}.stdout.log" -f $Job.id, $Job.name)
    $ErrorLogPath = Join-Path $RunRoot ("{0}_{1}.stderr.log" -f $Job.id, $Job.name)
    $Direction = ($Job.prompt.Trim() + " " + $Batch.common_constraints.Trim() + " Discovery reference: " + $Job.source_url)
    Write-Status -State "running" -JobIndex ($Index + 1) -CurrentId $Job.id -Results $Results
    $StartedAt = (Get-Date).ToString("o")
    $Succeeded = $false
    $ErrorText = $null
    try {
        $Escape = { param([string]$Value) "'" + $Value.Replace("'", "''") + "'" }
        $Command = "& {0} -Direction {1} -StepN {2} -ExperimentId {3} -Model {4} -BaseUrl {5}" -f `
            (& $Escape $Runner),
            (& $Escape $Direction),
            $StepN,
            (& $Escape $ExperimentId),
            (& $Escape $Model),
            (& $Escape $BaseUrl)
        $EncodedCommand = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($Command))
        $Child = Start-Process -FilePath "powershell.exe" `
            -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", $EncodedCommand) `
            -WorkingDirectory $ProjectRoot `
            -RedirectStandardOutput $LogPath `
            -RedirectStandardError $ErrorLogPath `
            -WindowStyle Hidden `
            -Wait `
            -PassThru
        $Workspace = Join-Path $ProjectRoot "data\quantalpha\results\workspace_$ExperimentId"
        $ResultFiles = @(Get-ChildItem -LiteralPath $Workspace -Filter "result.h5" -Recurse -File -ErrorAction SilentlyContinue)
        $Succeeded = ($Child.ExitCode -eq 0) -and ($ResultFiles.Count -gt 0)
        if (-not $Succeeded) {
            $ErrorText = "QuantaAlpha child exit=$($Child.ExitCode), result_h5_count=$($ResultFiles.Count)"
        }
    }
    catch {
        $ErrorText = $_.Exception.Message
        Add-Content -LiteralPath $ErrorLogPath -Value ("BATCH ERROR: " + $ErrorText)
    }
    $Results += [pscustomobject]@{
        id = $Job.id
        name = $Job.name
        source_url = $Job.source_url
        experiment_id = $ExperimentId
        success = $Succeeded
        error = $ErrorText
        started_at = $StartedAt
        completed_at = (Get-Date).ToString("o")
        log_path = $LogPath
        error_log_path = $ErrorLogPath
    }
    Write-Status -State "running" -JobIndex ($Index + 1) -CurrentId $Job.id -Results $Results
}

$FinalState = if (($Results | Where-Object { -not $_.success }).Count -eq 0) {
    "complete"
} else {
    "complete_with_failures"
}
Write-Status -State $FinalState -JobIndex $Jobs.Count -CurrentId "complete" -Results $Results
