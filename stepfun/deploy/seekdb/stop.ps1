$ErrorActionPreference = 'Stop'
$composeFile = Join-Path $PSScriptRoot 'compose.yml'
$composeEnv = Join-Path $PSScriptRoot '.env'
docker compose --env-file $composeEnv -f $composeFile stop
if ($LASTEXITCODE -ne 0) { throw 'Failed to stop StepFun seekdb.' }
Write-Host 'StepFun seekdb stopped. The named volume stepfun_seekdb_data was preserved.'
