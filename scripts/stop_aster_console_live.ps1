$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PidFile = Join-Path $ProjectRoot "run\aster_console\server.pid"
if (-not (Test-Path -LiteralPath $PidFile)) {
    Write-Output "Aster console has no recorded background process."
    exit 0
}
$ConsolePid = [int](Get-Content -LiteralPath $PidFile -Raw).Trim()
$Process = Get-Process -Id $ConsolePid -ErrorAction SilentlyContinue
if ($null -ne $Process) {
    Stop-Process -Id $ConsolePid
    [void]$Process.WaitForExit(5000)
}
Remove-Item -LiteralPath $PidFile -ErrorAction SilentlyContinue
Write-Output "Aster console stopped (PID $ConsolePid)."

