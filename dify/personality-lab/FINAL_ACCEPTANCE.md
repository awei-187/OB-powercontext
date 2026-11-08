# 最终 Dify 交付验收摘要

验收日期：2026-11-08（Asia/Shanghai）

## 1. 最终运行配置

- 应用配置：`PROFILE_MODE=dify`
- Dify：1.19.0，自托管 Docker
- Dify 应用 ID：`5e63bb1d-89e2-487a-b422-b26eb97f684b`
- 已发布 Workflow ID：`53015536-407d-403e-9c2f-cf68ede25b6d`，版本号 1
- PowerContext：1.5.0，官方 HTTP Server，SQLite 持久化
- Node.js：24.22.1；项目声明最低版本 22.18.0

## 2. Dify 真实成功运行

以下记录来自本机 Dify PostgreSQL 的 `workflow_app_logs` 与 `workflow_runs` 只读联表查询。输入和输出正文未导出，只保留字节数与 SHA-256。

| 任务 | Log ID | Run ID | 状态 | 上海时间 | 耗时 | Tokens | 输入／输出 |
|---|---|---|---|---|---:|---:|---|
| scenes | `b214cc19-01ab-46b6-81ae-17767fec72e8` | `90e5394c-fdd4-4f0a-9b19-9a18588bf651` | succeeded | 12:10:47—12:12:10 | 83.007 s | 3705 | 8680／13069 B |
| report | `a64e5360-c0d1-4a38-a311-fe15fed8535e` | `987b5848-aa9b-4d10-a5f2-0190cb9d86c0` | succeeded | 12:20:24—12:21:12 | 47.797 s | 4181 | 18455／4034 B |

完整哈希见 `evidence/dify-workflow-runs-20261108.json`。最终状态为 `sceneSource=dify`、`report.source=dify`，不存在工作流错误。

DSL 使用 Dify 1.19.0 自带 `AppDslService`，指定上述已发布 Workflow、`include_secret=false` 重新导出。导出 DSL 版本为 0.7.0，包含 3 个节点和 1 个 `langgenius/openai:1.1.0` 依赖，文件 7972 字节，SHA-256 为 `206b4300935a2ab21e92e3da3ff2eb694f519d12f51e8a13b39b4c4715cb62b3`。

## 3. PowerContext 真实写入与召回

最终合成验收轮次：

- 测试 ID：`cd6ee630-3bdd-4749-abb2-93baf63770d5`
- Scope：`scp_3fy4y62faa21w920xgxjs8ekzs`
- 3 项预判 + 6 项初选 + 2 项反转 + 2 项取舍 + 2 项换位 = 15 项
- 本地保存 15 份 PowerContext 写入回执，15 个 `source_id` 与 15 个 Artifact ID 均唯一，`pendingMemory=0`
- PowerContext 库存：30 个 Source、15 个 Atomic Memory Artifact、15 条 active decision memory

30 个 Source 并非重复计数错误：每项先写 `/v1/sources/content`，再调用 `/v1/memory/remember`；应用自己的 15 份回执对应前一条路径，15 个 Atomic Memory 对应后一条路径。

报告前召回结果为 6384 字节，SHA-256 为 `fc277c72238e89a3669a2d7b3a2a5e1ce33bf1c7314487b586bb61422d9cda69`。后端确认 15 个阶段标识和相应选择原文全部存在。实际 Dify `report` 运行的 `inputs.payload.recalled` 字段也是 6384 字节且哈希相同；同时传入服务器计算的 6 条初选证据、2 条反转对照和拓展对照。

真实停止并重新启动 PowerContext 后，`live=ok`、`ready=ready`，同一 Scope 再次召回仍为相同字节数和哈希，15 项逐项校验通过。

## 4. 实际验证的记忆语义

已验证的是：**退出后继续同一轮**。

最终 Dify 会话退出后用同一 Cookie 重进，仍恢复测试 ID、revision 14 和完整报告；Node 进程从 PID 18152 重启到 PID 16220 后，再次读取仍为同一轮。无 Cookie 的新会话读取不到该记录。

没有验证、也没有实现“新一轮使用上一轮记录”。重新开始会归档本地旧轮次，并为新测试建立新的 PowerContext Scope；报告只查询本轮 Scope。

## 5. 恢复、隔离与故障结果

| 项目 | 结果 | 验证类型 |
|---|---|---|
| 退出后重进同一轮 | 通过 | 最终真实 Dify 会话，同一 Cookie |
| Node 服务重启后恢复 | 通过 | 最终真实 Dify 会话，真实进程重启 |
| 新会话隔离 | 通过 | 无 Cookie 会话看不到最终记录；自动化还验证两轮建立不同 Scope |
| PowerContext 服务重启 | 通过 | 真实 1.5.0 服务停止／启动后重新召回最终 15 项 |
| PowerContext 写入故障保留答案 | 通过 | 隔离应用实例 + 真实 PowerContext 停服：答案数保持 1、待同步为 1、显示错误 |
| PowerContext 恢复后重试 | 通过 | 服务恢复后显式 `sync`：答案仍为 1、待同步降为 0，落盘 4 份回执（3 预判 + 1 初选） |
| 完整 Dify + PowerContext 主链 | 通过 | 真实服务，最终 15 项报告 |

故障注入实例使用 `PROFILE_MODE=local` 以避免模型延迟干扰存储故障测试，但连接的是本机真实 PowerContext 1.5.0。另有自动化测试在 Dify 模式的协议层使用可控故障替身，验证错误码、报告阻断和不重复答题。两者没有冒充主链的真实 Dify 成功记录。

## 6. 自动测试

`node --test tests/*.test.mjs`：18/18 通过，0 失败。覆盖服务器计分、4096 条初选路径、36864 条初选／反转路径、重复请求、过期 revision、重启恢复、两会话隔离、记忆写入失败与重试、召回缺失、Dify 报告失败及旧存档兼容。

## 7. 尚未通过或尚未验证

- “新一轮自动使用上一轮记录”未实现、未验证。
- 尚未在第二台全新电脑执行一遍 `Install-PowerContext.ps1`；脚本已通过语法检查，但干净机安装仍需复验。
- 尚未把最终 DSL 导入第二套独立 Dify 并重新绑定模型验证；当前证明的是本机 Dify 1.19.0 最终发布版本可运行并可官方导出。
- 一次额外的新 Dify 韧性会话在客户端 120 秒上限处超时，未进入故障注入阶段，未计为通过；最终主链的 `scenes` 和 `report` 成功记录不受影响。
- 未验证公网、反向代理、多机部署或临时隧道；本交付也不依赖这些能力。
- 比赛平台截图、仓库 branch／commit SHA 和平台提测尚未执行。

## 8. 交付独立性

交付不包含或依赖作者未提供的绝对路径、已有 PowerContext 数据库、用户存档、API Key、Cookie、原始日志或临时隧道。PowerContext 安装脚本在项目内创建 `.runtime`、`config` 和 `data`，配置路径按当前项目位置生成；`.env.example` 保持空密钥。评测环境仍需自行提供模型凭据、导入并发布 DSL，然后按 `VALIDATION.md` 生成自己的新 Scope 和验收记录。
