[CmdletBinding()]
param(
  [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path,
  [int]$HostPort = 12881
)

$ErrorActionPreference = 'Stop'
$composeEnv = Join-Path $PSScriptRoot '.env'
$appEnv = Join-Path $ProjectRoot '.env'

function New-HexSecret {
  return [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(24)).ToLowerInvariant()
}

function Read-EnvFile([string]$Path) {
  $values = [ordered]@{}
  if (Test-Path -LiteralPath $Path) {
    foreach ($line in Get-Content -LiteralPath $Path) {
      if ($line -match '^\s*([^#=\s]+)=(.*)$') { $values[$Matches[1]] = $Matches[2] }
    }
  }
  return $values
}

function Set-EnvValues([string]$Path, [System.Collections.IDictionary]$Updates) {
  $existing = @()
  if (Test-Path -LiteralPath $Path) {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    Copy-Item -LiteralPath $Path -Destination "$Path.backup-$stamp"
    $existing = @(Get-Content -LiteralPath $Path)
  }
  $seen = @{}
  $output = @()
  foreach ($line in $existing) {
    if ($line -match '^\s*([^#=\s]+)=') {
      $key = $Matches[1]
      if ($Updates.Contains($key)) {
        $seen[$key] = $true
        $output += "$key=$($Updates[$key])"
        continue
      }
    }
    $output += $line
  }
  foreach ($entry in $Updates.GetEnumerator()) {
    if (-not $seen.ContainsKey($entry.Key)) { $output += "$($entry.Key)=$($entry.Value)" }
  }
  [IO.File]::WriteAllLines($Path, $output, [Text.UTF8Encoding]::new($false))
}

$compose = Read-EnvFile $composeEnv
$rootPassword = if ($compose['SEEKDB_ROOT_PASSWORD']) { $compose['SEEKDB_ROOT_PASSWORD'] } else { New-HexSecret }
$app = Read-EnvFile $appEnv
$appPassword = if ($app['SEEKDB_PASSWORD']) { $app['SEEKDB_PASSWORD'] } else { New-HexSecret }

Set-EnvValues $composeEnv ([ordered]@{
  SEEKDB_HOST_PORT = $HostPort
  SEEKDB_ROOT_PASSWORD = $rootPassword
})
Set-EnvValues $appEnv ([ordered]@{
  PORT = 4317
  SEEKDB_HOST = '127.0.0.1'
  SEEKDB_PORT = $HostPort
  SEEKDB_USER = 'stepfun_app'
  SEEKDB_PASSWORD = $appPassword
  SEEKDB_DATABASE = 'stepfun_lab'
})

Write-Host "Configured local secret files: $composeEnv and $appEnv"
