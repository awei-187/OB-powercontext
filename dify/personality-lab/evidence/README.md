# 验证证据

本目录只提交脱敏后的运行状态、计数、哈希和必要截图，不提交 API Key、Cookie、数据库、完整选择文本或人格报告正文。

- `dify-powercontext-live-20261108.json`：真实 Dify + PowerContext 完整合成会话的早期汇总。
- `dify-workflow-runs-20261108.json`：Dify 数据库中最终 `scenes` 与 `report` 成功运行的脱敏元数据和输入／输出哈希。
- `powercontext-acceptance-20261108.json`：PowerContext 版本、15 项写入、召回、重启后持久化及 Dify 输入哈希对照。
- `resilience-acceptance-20261108.json`：退出重进、Node 重启、会话隔离和真实 PowerContext 故障重试结果。

如比赛平台要求截图，最终提交前还应补充：

1. Dify `scenes` 成功运行的节点记录截图。
2. Dify `report` 成功运行的节点记录截图。
3. PowerContext Dashboard 中对应 Scope 的 15 条记录计数截图。
4. 浏览器最终报告页截图。

截图必须遮盖 API Key、Cookie、Authorization Header 和本机无关路径。
