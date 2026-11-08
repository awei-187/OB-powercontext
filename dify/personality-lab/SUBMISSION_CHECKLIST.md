# 提交清单

## 仓库

- [ ] 目录位于比赛仓库 `dify/personality-lab`。
- [ ] 分支基于 `2026-competition-ecosystem`。
- [ ] branch、commit SHA 与提交平台填写一致，提交已推送。
- [ ] 私有仓库已给评测账号读取权限。

## 禁止提交

- [ ] 没有 `.env`、API Key、Token、Cookie。
- [ ] 没有 `.runtime/`、`.deployment-backups/`、数据库、WAL、日志。
- [ ] 没有 `powercontext/.runtime/`、`powercontext/data/` 或 uv/Python 安装缓存。
- [ ] 没有真实用户选择和完整人格报告正文。

## Dify

- [ ] `workflow/personal-manual.yml` 从最终发布版本导出或与其逐项核对。
- [ ] README 写明 Dify 版本、模型供应商插件、模型和重新绑定步骤。
- [ ] 在空 Workspace 导入 DSL，重新创建 API Key，并成功运行 `scenes` 与 `report`。
- [ ] 保存 Dify 两次成功运行的节点记录截图，截图中不显示密钥。

## PowerContext

- [ ] 在干净目录执行 `powercontext/Install-PowerContext.ps1` 成功。
- [ ] `Status-PowerContext.ps1` 的 `live`、`ready` 均成功。
- [ ] 新 Scope 完成 15 次真实写入，15 个 Source 和 Artifact ID 唯一。
- [ ] 最终召回覆盖 15/15，结果参与 Dify 报告，不是固定示例文本。

## 应用与证据

- [ ] `npm.cmd test` 18/18。
- [ ] 按 `VALIDATION.md` 从空会话完成一次真实全流程。
- [ ] 页面显示 `Dify 工作流` 和 `PowerContext`。
- [ ] 最终报告显示 Dify 来源、PowerContext 来源和三条有效证据。
- [ ] evidence 中只保留脱敏计数、状态、哈希和必要截图。
- [ ] 记录已知等待时间、模型限制和失败重试方式。
