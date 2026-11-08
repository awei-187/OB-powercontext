# StepFun seekdb Server（Docker Desktop / Linux engine）

固定镜像：`oceanbase/seekdb:1.4.0-100000172026082615`。仅发布 `127.0.0.1:12881`，数据保存在 named volume `stepfun_seekdb_data` 的 `/var/lib/seekdb`。容器限制为 2 CPU / 3 GiB，seekdb 内部内存限制为 2 GiB。

```powershell
Set-Location deploy/seekdb
.\configure.ps1  # 首次生成本机随机凭据；不会输出密码
.\start.ps1      # 等待真实 SELECT 1，创建应用账号并输出 SELECT VERSION()
.\status.ps1
.\stop.ps1       # 仅停止容器，不删除容器或数据卷
```

实际凭据位于本目录 `.env` 和项目根目录 `.env`，两者均被 `.gitignore` 忽略。不要运行 `docker compose down -v` 或删除 `stepfun_seekdb_data`。
