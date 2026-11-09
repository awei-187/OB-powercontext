# 《个人使用说明书》一页说明

《个人使用说明书》是一个有明确终点的娱乐选择游戏。玩家先做三项自我预判，再完成六个生活故事、两次条件反转、两次取舍和两次换位选择，最终得到一份带选择证据的说明书。它不做心理诊断，也不让模型自由决定题目权重或人格结论。

## 为什么使用 Dify 和 PowerContext

Dify Workflow 只负责两项生成：每轮编写一套新故事与配套选项，以及根据可信计算结果撰写最终说明书。Node 后端保存行为锚点、题号、分值、原始选择和证据 ID，并对模型输出做严格校验。模型不能增加题目、修改分数或引用不存在的选择。

PowerContext 1.5.0 为每轮创建独立 Scope。三项预判、六项初选、两项反转、两项取舍和两项换位合计 15 项，每项写入 content source 并生成 Atomic Memory。报告前，后端调用 `context/prepare` 召回本轮内容，逐项核对 15 个标识和选择原文，再把召回文本作为 Dify `report` 任务的 `payload.recalled` 字段。

```text
浏览器 → Node 后端 → Dify scenes → 15 项选择 → PowerContext 写入
                                      ↓
最终说明书 ← Dify report ← 校验后的 PowerContext 召回 + 后端可信计算
```

## 已完成的真实验收

- `PROFILE_MODE=dify`，Dify 1.19.0 的 `scenes` 与 `report` 均有成功工作流记录。
- PowerContext 1.5.0 中，最终 Scope 有 15 条 active decision memory、15 个 Atomic Memory Artifact；召回 6384 字节，哈希与进入 Dify 的 `recalled` 字段一致。
- 退出重进同一轮、Node 服务重启后恢复、无 Cookie 会话隔离、PowerContext 重启后继续召回均通过。
- 真实 PowerContext 停止时，答案先保存在本地并显示待同步；服务恢复后显式重试不会重复答题。
- Node 自动测试 18/18，通过全部 4096 种初选组合和 36864 种初选／反转组合。

## 记忆边界

当前验证的是“退出后继续同一轮”，不是“新一轮使用上一轮记录”。重新开始会创建新的测试 ID 和 PowerContext Scope；跨轮人格演化或上一轮记忆注入尚未实现。

## 交付边界

交付包含 Dify 官方无密钥导出的 DSL、完整源码、PowerContext 固定版本安装脚本、空白配置示例、启动步骤、验证样例和脱敏证据。不包含 `.env`、API Key、Cookie、用户存档、PowerContext SQLite、原始日志、模型正文或临时隧道。运行时路径均由项目当前位置生成，不依赖作者的 `D:` 盘或已有数据库。
