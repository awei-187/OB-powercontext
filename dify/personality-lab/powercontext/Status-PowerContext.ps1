[CmdletBinding()]
param([int]$Port = 8000)

$ErrorActionPreference = 'Stop'
$invoke = Join-Path $PSScriptRoot 'Invoke-PowerContext.ps1'
$url = "http://127.0.0.1:$Port"
& $invoke --server-url $url live
& $invoke --server-url $url ready
