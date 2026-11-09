$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'Invoke-PowerContext.ps1') service stop
