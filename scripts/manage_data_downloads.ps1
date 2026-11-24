param(
    [ValidateSet("status", "ensure")][string]$Action = "status",
    [string]$StartDate = "2016-11-24",
    [string]$EndDate = "2026-11-24",
    [int]$StaleMinutes = 20,
    [switch]$IncludeAkshare,
    [switch]$IncludeIc,
    [switch]$IncludeFilings
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$UnionPath = Join-Path $ProjectRoot "data\raw\qlib_full\csi500_historical_union.csv"
$ExpectedInstruments = if (Test-Path $UnionPath) {
    @((Import-Csv $UnionPath | Select-Object -ExpandProperty instrument -Unique)).Count
} else { $null }
$StartPeriod = [DateTime]::Parse($StartDate).ToString("yyyy-MM")
$EndPeriod = [DateTime]::Parse($EndDate).ToString("yyyy-MM")
$ExpectedMonths = (([DateTime]::Parse("$EndPeriod-01").Year - [DateTime]::Parse("$StartPeriod-01").Year) * 12) +
    ([DateTime]::Parse("$EndPeriod-01").Month - [DateTime]::Parse("$StartPeriod-01").Month) + 1

function Get-DownloadState {
    param(
        [string]$Name,
        [string]$CommandPattern,
        [string]$StatusPath
    )
    $Process = Get-CimInstance Win32_Process | Where-Object {
        $_.Name -eq "python.exe" -and $_.CommandLine -match $CommandPattern
    } | Select-Object -First 1
    $Payload = $null
    $StatusError = $null
    if (Test-Path -LiteralPath $StatusPath) {
        try { $Payload = Get-Content -LiteralPath $StatusPath -Raw | ConvertFrom-Json }
        catch { $StatusError = $_.Exception.Message }
    }
    $UpdatedAt = $null
    $AgeMinutes = $null
    if ($null -ne $Payload -and $Payload.updated_at) {
        $UpdatedAt = [DateTimeOffset]::Parse([string]$Payload.updated_at)
        $AgeMinutes = (([DateTimeOffset]::Now - $UpdatedAt).TotalMinutes)
    }
    [pscustomobject]@{
        name = $Name
        process_running = ($null -ne $Process)
        pid = if ($Process) { [int]$Process.ProcessId } else { $null }
        status_state = if ($Payload) { $Payload.state } else { $null }
        stage = if ($Payload) { $Payload.stage } else { $null }
        completed = if ($Payload.completed) { $Payload.completed } elseif ($null -ne $Payload.jobs_completed) { $Payload.jobs_completed } else { $null }
        total = if ($Payload.total) { $Payload.total } elseif ($Payload.total_discovered) { $Payload.total_discovered } elseif ($Payload.jobs_total) { $Payload.jobs_total } else { $null }
        failures = if ($Payload) { $Payload.failures } else { $null }
        updated_at = if ($UpdatedAt) { $UpdatedAt.ToString("o") } else { $null }
        heartbeat_age_minutes = if ($null -ne $AgeMinutes) { [math]::Round($AgeMinutes, 2) } else { $null }
        stale = ($null -ne $AgeMinutes -and $AgeMinutes -gt $StaleMinutes)
        status_error = $StatusError
    }
}

$Definitions = @(
    [pscustomobject]@{
        Name = "qlib_full"
        Pattern = "aster_data\.full_download"
        Status = Join-Path $ProjectRoot "run\full_download\status.json"
        StartScript = Join-Path $ProjectRoot "scripts\start_full_download.ps1"
        ExpectedTotal = $ExpectedInstruments
        RetryFailures = $false
    },
    [pscustomobject]@{
        Name = "parallel_financial"
        Pattern = "aster_data\.parallel_financial"
        Status = Join-Path $ProjectRoot "run\parallel_financial\status.json"
        StartScript = Join-Path $ProjectRoot "scripts\start_parallel_financial.ps1"
        ExpectedTotal = $ExpectedInstruments
        RetryFailures = $false
    }
)
if ($IncludeAkshare) {
    $Definitions += [pscustomobject]@{
        Name = "akshare_market"
        Pattern = "aster_data\.akshare_market"
        Status = Join-Path $ProjectRoot "run\akshare_market\status.json"
        StartScript = Join-Path $ProjectRoot "scripts\start_akshare_market.ps1"
        ExpectedTotal = $ExpectedInstruments
        RetryFailures = $true
    }
}
if ($IncludeIc) {
    $Definitions += [pscustomobject]@{
        Name = "ic_futures"
        Pattern = "aster_data\.ic_futures"
        Status = Join-Path $ProjectRoot "run\ic_futures\status.json"
        StartScript = Join-Path $ProjectRoot "scripts\start_ic_download.ps1"
        ExpectedTotal = $ExpectedMonths
        RetryFailures = $true
    }
}
if ($IncludeFilings) {
    $Definitions += [pscustomobject]@{
        Name = "official_filings"
        Pattern = "download_filings_bulk\.py"
        Status = Join-Path $ProjectRoot "data\raw\filings\bulk_status.json"
        StartScript = Join-Path $ProjectRoot "scripts\start_filing_download.ps1"
        ExpectedTotal = $ExpectedInstruments
        RetryFailures = $true
    }
}

$Before = foreach ($Definition in $Definitions) {
    Get-DownloadState -Name $Definition.Name -CommandPattern $Definition.Pattern -StatusPath $Definition.Status
}
if ($Action -eq "ensure") {
    foreach ($Definition in $Definitions) {
        $State = $Before | Where-Object name -eq $Definition.Name
        $Incomplete = $State.status_state -ne "complete" -or `
            $null -eq $State.total -or `
            ($null -ne $Definition.ExpectedTotal -and [int]$State.total -lt [int]$Definition.ExpectedTotal) -or `
            ($Definition.RetryFailures -and $null -ne $State.failures -and [int]$State.failures -gt 0)
        if (-not $State.process_running -and $Incomplete) {
            Start-Process -FilePath "powershell.exe" -ArgumentList @(
                "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $Definition.StartScript,
                "-StartDate", $StartDate, "-EndDate", $EndDate
            ) -WindowStyle Hidden | Out-Null
        }
    }
    Start-Sleep -Seconds 3
}
$After = foreach ($Definition in $Definitions) {
    Get-DownloadState -Name $Definition.Name -CommandPattern $Definition.Pattern -StatusPath $Definition.Status
}
[pscustomobject]@{
    checked_at = [DateTimeOffset]::Now.ToString("o")
    action = $Action
    downloads = @($After)
    note = "Active but stale jobs are reported and never killed automatically."
} | ConvertTo-Json -Depth 6
