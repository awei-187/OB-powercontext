$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$appEnv = Join-Path $projectRoot '.env'
$app = @{}
foreach ($line in Get-Content -LiteralPath $appEnv) {
  if ($line -match '^\s*([^#=\s]+)=(.*)$') { $app[$Matches[1]] = $Matches[2] }
}
docker inspect stepfun-seekdb-1 --format 'container={{.Name}} status={{.State.Status}} health={{.State.Health.Status}} image={{.Config.Image}} imageId={{.Image}} ports={{json .NetworkSettings.Ports}} mounts={{json .Mounts}}'
docker exec -e "MYSQL_PWD=$($app['SEEKDB_PASSWORD'])" stepfun-seekdb-1 mysql -h 127.0.0.1 -P 2881 -u stepfun_app -D stepfun_lab -Nse 'SELECT 1, VERSION(), DATABASE(), CURRENT_USER()'
