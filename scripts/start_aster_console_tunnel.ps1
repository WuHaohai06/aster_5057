[CmdletBinding()]
param(
    [string]$Origin = "http://127.0.0.1:8765"
)

$ErrorActionPreference = "Stop"
$Cloudflared = Get-Command cloudflared -ErrorAction SilentlyContinue
if ($null -eq $Cloudflared) {
    throw "cloudflared is not installed. Install it, then rerun this script."
}

Write-Warning "A quick tunnel is publicly reachable by anyone with its URL. The app exposes only sanitised read-only data. For persistent sharing, protect a named tunnel with Cloudflare Access."
& $Cloudflared.Source tunnel --url $Origin --no-autoupdate

