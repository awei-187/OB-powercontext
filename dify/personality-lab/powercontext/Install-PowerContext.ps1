[CmdletBinding()]
param(
  [string]$UvPath = 'uv.exe',
  [string]$PythonVersion = '3.11.18',
  [string]$PowerContextVersion = '1.5.0',
  [int]$Port = 8000,
  [switch]$NoService
)

$ErrorActionPreference = 'Stop'
$uv = Get-Command $UvPath -ErrorAction SilentlyContinue
if (-not $uv) {
  throw '未找到 uv。请先按 https://docs.astral.sh/uv/getting-started/installation/ 安装 uv。'
}

$runtime = Join-Path $PSScriptRoot '.runtime'
$venv = Join-Path $runtime 'venv'
$python = Join-Path $venv 'Scripts\python.exe'
$configDir = Join-Path $PSScriptRoot 'config'
$dataDir = Join-Path $PSScriptRoot 'data'
$envFile = Join-Path $configDir 'powercontext.env'

New-Item -ItemType Directory -Path $runtime, $configDir, $dataDir -Force | Out-Null

& $uv.Source python install $PythonVersion
if ($LASTEXITCODE -ne 0) { throw 'uv 安装 Python 失败。' }

if (-not (Test-Path -LiteralPath $python)) {
  & $uv.Source venv --python $PythonVersion $venv
  if ($LASTEXITCODE -ne 0) { throw 'uv 创建 PowerContext 虚拟环境失败。' }
}

& $uv.Source pip install --python $python --upgrade "powercontext[cli,server]==$PowerContextVersion"
if ($LASTEXITCODE -ne 0) { throw 'PowerContext 安装失败。' }

$dataPosix = $dataDir.Replace('\', '/')
$assignments = @(
  "POWERCONTEXT_HOME=$dataPosix",
  'POWERCONTEXT_SERVER_HTTP_HOST=127.0.0.1',
  "POWERCONTEXT_SERVER_HTTP_PORT=$Port",
  'POWERCONTEXT_SERVER_DATABASE_KIND=sqlite',
  "POWERCONTEXT_SERVER_DATABASE_URL=sqlite+aiosqlite:///$dataPosix/powercontext.db",
  'POWERCONTEXT_SERVER_MCP_ENABLED=true',
  'POWERCONTEXT_SERVER_MCP_PATH=/mcp',
  'POWERCONTEXT_SERVER_DASHBOARD_ENABLED=true',
  'POWERCONTEXT_SERVER_ACCESS_MODE=disabled',
  'POWERCONTEXT_SERVER_AUTH_ENABLED=false',
  'POWERCONTEXT_SERVER_LOGGING_LEVEL=INFO',
  'POWERCONTEXT_SERVER_LOGGING_FORMAT=console'
)
[System.IO.File]::WriteAllLines($envFile, $assignments, [System.Text.UTF8Encoding]::new($false))

$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$acl = [System.Security.AccessControl.FileSecurity]::new()
$acl.SetOwner([System.Security.Principal.NTAccount]::new($identity))
$acl.SetAccessRuleProtection($true, $false)
$rule = [System.Security.AccessControl.FileSystemAccessRule]::new($identity, 'FullControl', 'Allow')
$acl.AddAccessRule($rule)
Set-Acl -LiteralPath $envFile -AclObject $acl

$invoke = Join-Path $PSScriptRoot 'Invoke-PowerContext.ps1'
& $invoke --version

if ($NoService) {
  Write-Host 'PowerContext 已安装。请运行 Run-PowerContextForeground.ps1。'
  exit 0
}

& $invoke service install --env-file $envFile --start-on-login
& $invoke service start
Write-Host "PowerContext 已启动：http://127.0.0.1:$Port"
