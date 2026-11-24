param(
    [string]$RunId = "",
    [int]$StepN = 5,
    [string]$Model = "deepseek-flash",
    [string]$BaseUrl = "https://api.deepseek.com"
)

$ErrorActionPreference = "Continue"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Runner = Join-Path $PSScriptRoot "run_quantaalpha.ps1"
if ([string]::IsNullOrWhiteSpace($RunId)) {
    $RunId = "price_volume_" + (Get-Date -Format "yyyyMMdd_HHmmss")
}
$RunRoot = Join-Path $ProjectRoot "run\factor_mining_batch\$RunId"
New-Item -ItemType Directory -Force -Path $RunRoot | Out-Null
$StatusPath = Join-Path $RunRoot "status.json"

$Common = @'
Use only PIT-safe adjusted daily OHLCV fields from the CSI500 PIT universe. Never use future data, static current constituents, raw cross-stock share-volume comparisons, or market_return. Normalize volume only against the same stock's own trailing history. Produce interpretable candidates for one mechanism only. Preserve the economic mechanism, expected sign, holding horizon, falsification condition, and failure regime. Prefer simple expressions supported by the supplied function library.
'@

$Jobs = @(
    [pscustomobject]@{
        Id = "A01"
        Name = "volume_price_shock_reversal"
        Direction = @'
Mine the PV-A01 abnormal-volume price-shock reversal hypothesis. An extreme same-day return accompanied by volume unusually high relative to that stock's own trailing 20-day history may reflect attention trading, stop-losses, or temporary liquidity demand and should partially reverse over the next 1-5 sessions. Seed: RANK(-1 * $return * TS_ZSCORE(LOG($volume + 1), 20)). Distinguish ordinary liquidity shocks from persistent fundamental distress; falsify the idea if the signal is continuation rather than reversal out of sample.
'@
    },
    [pscustomobject]@{
        Id = "A03"
        Name = "price_volume_divergence"
        Direction = @'
Mine the PV-A03 price-volume divergence hypothesis. A 5-20 day price rise with weakening smoothed volume suggests fading marginal demand, while a price decline with contracting volume may indicate exhausted selling pressure. Seed: -TS_PCTCHANGE($close, 10) * TS_PCTCHANGE(TS_MEAN(LOG($volume + 1), 5), 10). Test whether divergence predicts reversal and whether price-volume confirmation instead predicts continuation; reject the mechanism if results depend on a single volume spike.
'@
    },
    [pscustomobject]@{
        Id = "A04"
        Name = "volume_confirmed_momentum"
        Direction = @'
Mine the PV-A04 smoothed-volume-confirmed medium-horizon momentum hypothesis. Persistent rather than one-day volume expansion can indicate gradual information diffusion and confirm a 10-20 day price trend. Seed: TS_PCTCHANGE($close, 20) * TS_ZSCORE(TS_MEAN(LOG($volume + 1), 5), 60). Penalize isolated volume spikes, use a 5-20 day forecast horizon, and falsify if the effect is actually short-term shock reversal.
'@
    },
    [pscustomobject]@{
        Id = "A05"
        Name = "compression_volume_breakout"
        Direction = @'
Mine the PV-A05 volume breakout after volatility compression hypothesis. After low trailing return volatility and a compressed trading range, a directional range expansion accompanied by unusually high own-history volume may continue. Seed components: SIGN($return), TS_ZSCORE(($high-$low)/(DELAY($close,1)+1e-8),20), TS_ZSCORE(LOG($volume+1),20), and inverse trailing TS_STD($return,20). Require compression to be known before the breakout; falsify if high-volume expansion mostly reverses.
'@
    },
    [pscustomobject]@{
        Id = "A08"
        Name = "close_location_volume_pressure"
        Direction = @'
Mine the PV-A08 close-location and volume-pressure hypothesis. CLV=(2*$close-$high-$low)/($high-$low+1e-8) measures whether buyers or sellers control the close; interact it with the stock's own relative volume. Moderate abnormal volume may confirm 1-5 day continuation, while extreme volume may become overtrading and reversal. Keep any nonlinear threshold simple and falsify if close location adds no information beyond same-day return.
'@
    },
    [pscustomobject]@{
        Id = "B08"
        Name = "price_path_smoothness"
        Direction = @'
Mine the PV-B08 price-path smoothness hypothesis. For the same cumulative return, a path made of many small same-direction moves is more consistent with gradual information diffusion than a path dominated by a few jumps. Seed smoothness: ABS(TS_SUM($return,20))/(TS_SUM(ABS($return),20)+1e-8), signed by the cumulative return, optionally confirmed by persistent own-history volume. Test 20-60 day formation and 5-20 day holding; falsify after controlling for cumulative return and volatility.
'@
    },
    [pscustomobject]@{
        Id = "B11"
        Name = "upper_wick_volume_rejection"
        Direction = @'
Mine the PV-B11 high-volume upper-wick rejection hypothesis. A long upper wick, defined as ($high-MAX($open,$close))/($high-$low+1e-8), with volume unusually high relative to the stock's own history can indicate selling pressure or a failed breakout and predict weak 1-5 day returns. Keep the expected factor sign explicit and falsify if the pattern is merely volatility exposure or if it continues upward out of sample.
'@
    },
    [pscustomobject]@{
        Id = "B12"
        Name = "lower_wick_volume_support"
        Direction = @'
Mine the PV-B12 high-volume lower-wick support hypothesis. A long lower wick, defined as (MIN($open,$close)-$low)/($high-$low+1e-8), with volume unusually high relative to the stock's own history can indicate demand absorption and predict a 1-5 day repair. Require the close to move meaningfully away from the low. Falsify if the apparent support is only a pause inside persistent distress or if the result is just inverse volatility exposure.
'@
    }
)

function Write-Status {
    param([string]$State, [int]$JobIndex, [string]$CurrentId, [array]$Results)
    $Payload = [ordered]@{
        run_id = $RunId
        pid = $PID
        state = $State
        step_n = $StepN
        jobs_total = $Jobs.Count
        job_index = $JobIndex
        current_id = $CurrentId
        results = $Results
        updated_at = (Get-Date).ToString("o")
    }
    $Temporary = "$StatusPath.tmp"
    $Payload | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $Temporary -Encoding UTF8
    Move-Item -LiteralPath $Temporary -Destination $StatusPath -Force
}

$Results = @()
Write-Status -State "running" -JobIndex 0 -CurrentId "starting" -Results $Results
for ($Index = 0; $Index -lt $Jobs.Count; $Index++) {
    $Job = $Jobs[$Index]
    $ExperimentId = "aster_pv_{0}_{1}" -f $Job.Id.ToLowerInvariant(), (Get-Date -Format "yyyyMMdd_HHmmss")
    $LogPath = Join-Path $RunRoot ("{0}_{1}.stdout.log" -f $Job.Id, $Job.Name)
    $ErrorLogPath = Join-Path $RunRoot ("{0}_{1}.stderr.log" -f $Job.Id, $Job.Name)
    $Direction = ($Job.Direction.Trim() + " " + $Common.Trim())
    Write-Status -State "running" -JobIndex ($Index + 1) -CurrentId $Job.Id -Results $Results
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
        id = $Job.Id
        name = $Job.Name
        experiment_id = $ExperimentId
        success = $Succeeded
        error = $ErrorText
        started_at = $StartedAt
        completed_at = (Get-Date).ToString("o")
        log_path = $LogPath
        error_log_path = $ErrorLogPath
    }
    Write-Status -State "running" -JobIndex ($Index + 1) -CurrentId $Job.Id -Results $Results
}

$FinalState = if (($Results | Where-Object { -not $_.success }).Count -eq 0) { "complete" } else { "complete_with_failures" }
Write-Status -State $FinalState -JobIndex $Jobs.Count -CurrentId "complete" -Results $Results
