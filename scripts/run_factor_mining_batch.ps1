param(
    [string]$RunId = "",
    [int]$StepN = 3,
    [string]$Model = "deepseek-flash",
    [string]$BaseUrl = "https://api.deepseek.com"
)

$ErrorActionPreference = "Continue"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Runner = Join-Path $PSScriptRoot "run_quantaalpha.ps1"
if ([string]::IsNullOrWhiteSpace($RunId)) {
    $RunId = "overnight_" + (Get-Date -Format "yyyyMMdd_HHmmss")
}
$RunRoot = Join-Path $ProjectRoot "run\factor_mining_batch\$RunId"
New-Item -ItemType Directory -Force -Path $RunRoot | Out-Null
$StatusPath = Join-Path $RunRoot "status.json"

$Jobs = @(
    [pscustomobject]@{
        Family = "beta"
        Direction = "Develop three distinct, interpretable CSI500 beta-style factors using only PIT-safe daily OHLCV returns and the SH000905 benchmark. Study shrunk rolling market beta, downside beta, and beta instability across 60/120/252-day windows. Avoid future data, static current constituents, and duplicate formulas. Preserve an economic hypothesis and falsification condition for every candidate."
    },
    [pscustomobject]@{
        Family = "momentum"
        Direction = "Develop three distinct, interpretable CSI500 momentum-style factors using only PIT-safe daily OHLCV data. Separate medium-horizon trend, path-quality momentum, and benchmark-residual momentum; test reversal contamination and multiple formation windows. Avoid future data and retain the economic hypothesis and falsification condition."
    },
    [pscustomobject]@{
        Family = "residual_volatility"
        Direction = "Develop three distinct, interpretable CSI500 residual-volatility-style factors using only PIT-safe daily returns and the SH000905 benchmark. Study idiosyncratic volatility, residual downside variation, and volatility-of-volatility with 60/120/252-day estimation windows. Avoid future data and retain the economic hypothesis and falsification condition."
    },
    [pscustomobject]@{
        Family = "liquidity"
        Direction = "Develop three distinct, interpretable CSI500 liquidity-style factors using PIT-safe daily OHLCV data. Since turnover and bid-ask quotes are unavailable, use scale-free proxies such as return-to-relative-volume price impact, zero/low-volume persistence, and volume-shock recovery. Never compare raw share volume across stocks. Retain the economic hypothesis and falsification condition."
    }
)

function Write-Status {
    param([string]$State, [int]$JobIndex, [string]$CurrentFamily, [array]$Results)
    $Payload = [ordered]@{
        run_id = $RunId
        pid = $PID
        state = $State
        step_n = $StepN
        jobs_total = $Jobs.Count
        job_index = $JobIndex
        current_family = $CurrentFamily
        results = $Results
        updated_at = (Get-Date).ToString("o")
    }
    $Temporary = "$StatusPath.tmp"
    $Payload | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $Temporary -Encoding UTF8
    Move-Item -LiteralPath $Temporary -Destination $StatusPath -Force
}

$Results = @()
Write-Status -State "running" -JobIndex 0 -CurrentFamily "starting" -Results $Results
for ($Index = 0; $Index -lt $Jobs.Count; $Index++) {
    $Job = $Jobs[$Index]
    $ExperimentId = "aster_{0}_{1}" -f $Job.Family, (Get-Date -Format "yyyyMMdd_HHmmss")
    $LogPath = Join-Path $RunRoot ("{0}.stdout.log" -f $Job.Family)
    $ErrorLogPath = Join-Path $RunRoot ("{0}.stderr.log" -f $Job.Family)
    Write-Status -State "running" -JobIndex ($Index + 1) -CurrentFamily $Job.Family -Results $Results
    $StartedAt = (Get-Date).ToString("o")
    $Succeeded = $false
    $ErrorText = $null
    try {
        $Escape = { param([string]$Value) "'" + $Value.Replace("'", "''") + "'" }
        $Command = "& {0} -Direction {1} -StepN {2} -ExperimentId {3} -Model {4} -BaseUrl {5}" -f `
            (& $Escape $Runner),
            (& $Escape $Job.Direction),
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
        $Succeeded = $Child.ExitCode -eq 0
        if (-not $Succeeded) {
            $ErrorText = "QuantaAlpha child exited with code $($Child.ExitCode)"
        }
    }
    catch {
        $ErrorText = $_.Exception.Message
        Add-Content -LiteralPath $ErrorLogPath -Value ("BATCH ERROR: " + $ErrorText)
    }
    $Results += [pscustomobject]@{
        family = $Job.Family
        experiment_id = $ExperimentId
        success = $Succeeded
        error = $ErrorText
        started_at = $StartedAt
        completed_at = (Get-Date).ToString("o")
        log_path = $LogPath
        error_log_path = $ErrorLogPath
    }
    Write-Status -State "running" -JobIndex ($Index + 1) -CurrentFamily $Job.Family -Results $Results
}

$FinalState = if (($Results | Where-Object { -not $_.success }).Count -eq 0) { "complete" } else { "complete_with_failures" }
Write-Status -State $FinalState -JobIndex $Jobs.Count -CurrentFamily "complete" -Results $Results
