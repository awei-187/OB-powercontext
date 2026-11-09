param(
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$CommandArguments
)

$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.runtime\venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
  throw "PowerContext 尚未安装。请先运行 $PSScriptRoot\Install-PowerContext.ps1"
}

& $python -c 'from powercontext.cli.app import main; main()' @CommandArguments
if ($LASTEXITCODE -ne 0) {
  throw "PowerContext 命令失败，退出码 $LASTEXITCODE。"
}
