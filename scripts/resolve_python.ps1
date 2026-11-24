function Resolve-AsterPython {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$EnvironmentName,
        [Parameter(Mandatory = $true)][string]$OverrideVariable
    )

    $Override = [Environment]::GetEnvironmentVariable($OverrideVariable)
    if (-not [string]::IsNullOrWhiteSpace($Override)) {
        if (-not (Test-Path -LiteralPath $Override -PathType Leaf)) {
            throw "$OverrideVariable points to a missing Python executable: $Override"
        }
        return (Resolve-Path -LiteralPath $Override).Path
    }

    $ActivePython = Get-Command python -ErrorAction SilentlyContinue
    if ($env:CONDA_DEFAULT_ENV -eq $EnvironmentName -and $null -ne $ActivePython) {
        return $ActivePython.Source
    }

    $Conda = Get-Command conda -ErrorAction SilentlyContinue
    if ($null -eq $Conda) {
        throw "Activate Conda environment '$EnvironmentName' or set $OverrideVariable."
    }
    $Lines = @(& $Conda.Source run -n $EnvironmentName python -c "import sys; print(sys.executable)")
    if ($LASTEXITCODE -ne 0) {
        throw "Could not resolve Python from Conda environment '$EnvironmentName'."
    }
    $Candidate = $Lines | Where-Object {
        -not [string]::IsNullOrWhiteSpace($_) -and (Test-Path -LiteralPath $_ -PathType Leaf)
    } | Select-Object -Last 1
    if ([string]::IsNullOrWhiteSpace($Candidate)) {
        throw "Conda environment '$EnvironmentName' did not return a Python executable."
    }
    return (Resolve-Path -LiteralPath $Candidate).Path
}
