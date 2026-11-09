# StepFun 跨电脑交接包

本包是 `stepfun/` 项目的源码与本机 AMD + seekdb Server 验收材料。项目目录来自 ZIP，不包含 Git 历史；提交、推送和 GitHub 评阅由正式参赛仓库负责人处理。

## 内容

- `server/`、`src/`、`tests/`、`scripts/`、`data/`、`public/` 中的源文件与固定测试语料。
- `package.json`、`package-lock.json`、`.npmrc`、`model-manifest.json`、README。
- `deploy/seekdb/` 中的固定镜像 Compose、配置示例、配置/启动/状态/停止脚本。
- `docs/evidence/2026-11-08-amd-server/` 的 15 份证据和 `SHA256.json`。
- `docs/technical-note.pdf` 与文字版、`docs/acceptance-report-2026-11-08.md`、安全审计与历史 Intel 资料。
- `PACKAGE-FILES-SHA256.json`：包内逐文件哈希。

包中没有实际 `.env`、凭据、诊断日志、数据库、Docker 数据卷、`node_modules`、模型文件或已生成的浏览器资源。

## 在另一台电脑解压与核验

先核对 ZIP 旁边 `.sha256` 文件中的 SHA-256。解压后可核对 `stepfun/PACKAGE-FILES-SHA256.json` 及 AMD 证据目录内的 `SHA256.json`。不要把来源 ZIP 的文件直接覆盖组员的修改；正式仓库负责人应按差异整合。

## Windows + Docker Linux 启动

安装 Node 24.14.x、Docker Desktop Linux engine，以及 Chrome/Edge。进入解压后的 `stepfun` 目录：

```powershell
.\deploy\seekdb\configure.ps1
.\deploy\seekdb\start.ps1
npm ci
npm run models:download
npm run build
npm run db:check:server
npm start
```

浏览器访问 `http://127.0.0.1:4317/`。数据库只发布在 `127.0.0.1:12881`。`configure.ps1` 在本机生成新的随机凭据；不要从原电脑复制 `.env`。模型下载脚本按 `model-manifest.json` 验证来源文件哈希。下载、构建和浏览器资源首次准备需要联网，推理仍在浏览器 Worker 内执行。

如果需要使用其他空闲宿主端口，请修改新机器 `deploy/seekdb/.env` 的 `SEEKDB_HOST_PORT` 和项目根 `.env` 的 `SEEKDB_PORT`，保持一致。数据库持久化使用 named volume `stepfun_seekdb_data`，不要运行 `docker compose down -v`。

运行 `npm run db:check:server` 后，应看见 `ready: 1` 与 `seekdb-v1.4.0.0`；运行 `npm start` 后，`http://127.0.0.1:4317/api/health` 应返回 `mode: "server"`。PowerShell 诊断本机 URL 可用 `Invoke-WebRequest -NoProxy`，以免系统代理产生假 502。

完整 100 段、fallback、性能和质量复测命令见项目 README。停止数据库使用 `.\deploy\seekdb\stop.ps1`，会保留卷。

## 已知边界

本机实测见 `docs/acceptance-report-2026-11-08.md` 和一页技术说明。`npm audit --json` 仍报告 5 个 high 节点；依赖链、公告和升级影响见 `docs/security-audit-2026-11-08.md`。无缓存全新安装尚未在原 AMD 机器独立复测。跨电脑启动和整合后的结果需要在目标环境重新确认。
