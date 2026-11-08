$ErrorActionPreference = 'Stop'
$envFile = Join-Path $PSScriptRoot 'config\powercontext.env'
if (-not (Test-Path -LiteralPath $envFile)) {
  throw '缺少 powercontext.env。请先运行 Install-PowerContext.ps1。'
}

Get-Content -LiteralPath $envFile | ForEach-Object {
  if ($_ -match '^\s*#' -or $_ -notmatch '=') { return }
  $name, $value = $_.Split('=', 2)
  [Environment]::SetEnvironmentVariable($name.Trim(), $value.Trim(), 'Process')
}

& (Join-Path $PSScriptRoot 'Invoke-PowerContext.ps1') server run
