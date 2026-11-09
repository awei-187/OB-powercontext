# PowerContext 1.5.0 部署

这些脚本在项目内创建独立运行环境，不依赖作者电脑上的绝对路径、全局 Python 或已存在数据库。

## 要求

- Windows 10/11、PowerShell 7
- 网络访问 PyPI
- [uv](https://docs.astral.sh/uv/getting-started/installation/) 已安装并在 PATH 中

## 安装为当前用户服务

```powershell
.\powercontext\Install-PowerContext.ps1
.\powercontext\Status-PowerContext.ps1
```

安装脚本固定使用：

- CPython `3.11.18`
- `powercontext[cli,server]==1.5.0`
- SQLite 数据库：`powercontext/data/powercontext.db`
- HTTP：`127.0.0.1:8000`
- Dashboard：`http://127.0.0.1:8000/dashboard/home`

配置写入 `powercontext/config/powercontext.env`，脚本会取消继承 ACL，仅授予当前用户完全控制。该文件、数据库、日志和虚拟环境均被 `.gitignore` 排除。

管理服务：

```powershell
.\powercontext\Start-PowerContext.ps1
.\powercontext\Status-PowerContext.ps1
.\powercontext\Stop-PowerContext.ps1
```

## Task Scheduler 不可用

某些沙箱或受限 Windows 会阻止当前用户服务。使用前台模式：

```powershell
.\powercontext\Install-PowerContext.ps1 -NoService
.\powercontext\Run-PowerContextForeground.ps1
```

保持该窗口运行，再从另一终端启动游戏。

## 安全说明

默认关闭认证是因为服务只监听 `127.0.0.1`。不要把 Host 改成 `0.0.0.0` 后继续关闭认证。需要远程部署时，应启用 PowerContext 认证并在游戏 `.env` 中填写 `POWERCONTEXT_TOKEN`。

`powercontext.env.example` 仅说明变量格式；实际文件由安装脚本根据当前位置生成，不应手工提交绝对路径。
