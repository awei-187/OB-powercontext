[CmdletBinding()]
param([int]$TimeoutSeconds = 600)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$composeFile = Join-Path $PSScriptRoot 'compose.yml'
$composeEnv = Join-Path $PSScriptRoot '.env'
$appEnv = Join-Path $projectRoot '.env'

if (-not (Test-Path -LiteralPath $composeEnv) -or -not (Test-Path -LiteralPath $appEnv)) {
  & (Join-Path $PSScriptRoot 'configure.ps1') -ProjectRoot $projectRoot
}

$dockerOs = docker info --format '{{.OSType}}'
if ($LASTEXITCODE -ne 0 -or $dockerOs -ne 'linux') { throw 'Docker Linux engine is required.' }

docker compose --env-file $composeEnv -f $composeFile up -d
if ($LASTEXITCODE -ne 0) { throw 'docker compose up failed.' }

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
do {
  $health = docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' stepfun-seekdb-1 2>$null
  if ($health -eq 'healthy') { break }
  if ($health -eq 'unhealthy' -or (Get-Date) -ge $deadline) {
    docker logs --tail 120 stepfun-seekdb-1
    throw "seekdb did not become SQL-ready; health=$health"
  }
  Start-Sleep -Seconds 2
} while ($true)

function Read-Env([string]$Path) {
  $values = @{}
  foreach ($line in Get-Content -LiteralPath $Path) {
    if ($line -match '^\s*([^#=\s]+)=(.*)$') { $values[$Matches[1]] = $Matches[2] }
  }
  return $values
}

$compose = Read-Env $composeEnv
$app = Read-Env $appEnv
$rootPassword = $compose['SEEKDB_ROOT_PASSWORD']
$appPassword = $app['SEEKDB_PASSWORD']

$sql = 'CREATE DATABASE IF NOT EXISTS stepfun_lab; CREATE USER IF NOT EXISTS ''stepfun_app''@''%'' IDENTIFIED BY ''${APP_PASSWORD}''; ALTER USER ''stepfun_app''@''%'' IDENTIFIED BY ''${APP_PASSWORD}''; GRANT ALL PRIVILEGES ON stepfun_lab.* TO ''stepfun_app''@''%''; FLUSH PRIVILEGES;'
$command = 'mysql -h127.0.0.1 -P2881 -uroot -e "' + $sql + '"'
docker exec -e "MYSQL_PWD=$rootPassword" -e "APP_PASSWORD=$appPassword" stepfun-seekdb-1 /bin/bash -lc $command
if ($LASTEXITCODE -ne 0) { throw 'Failed to create or grant the StepFun application account.' }

docker exec -e "MYSQL_PWD=$appPassword" stepfun-seekdb-1 mysql -h 127.0.0.1 -P 2881 -u stepfun_app -D stepfun_lab -Nse 'SELECT 1'
if ($LASTEXITCODE -ne 0) { throw 'StepFun application account verification failed.' }

docker exec -e "MYSQL_PWD=$appPassword" stepfun-seekdb-1 mysql -h 127.0.0.1 -P 2881 -u stepfun_app -D stepfun_lab -Nse 'SELECT VERSION()'
if ($LASTEXITCODE -ne 0) { throw 'SELECT VERSION() failed.' }
