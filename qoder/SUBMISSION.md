# 研续 Yanxu · 参赛材料索引

研续帮助个人研究项目在中断后恢复工作：记录目标、实验、决策和待办，保存交接，再在新会话中读回上下文并生成带真实来源引用的周报。主要开发、调试和网站发布由 Qoder CN 完成。

| 材料 | 入口 |
| --- | --- |
| Qoder Sites 展示网站 | https://yanxu-research-022wcl7311d.qoder.zone |
| 项目代码 | https://github.com/awei-187/OB-powercontext/tree/competition/qoder-yanxu/qoder |
| 提交分支 | `competition/qoder-yanxu` |
| 环境、安装与运行 | [README.md](README.md) |
| 设计与指定技术作用 | [PROJECT.md](PROJECT.md)、[app/memory.py](app/memory.py) |
| Qoder 开发过程 | [evidence/provenance.json](evidence/provenance.json)、[evidence/qoder/](evidence/qoder/) |
| Qoder 账号 UID | `01a17306-8a15-783a-ad49-cdb181a86716`（账号持有人提供） |
| Qoder Sites 发布事实 | [evidence/publication.json](evidence/publication.json) |
| 独立验收 | [evidence/delivery-audit.json](evidence/delivery-audit.json) |

## 指定技术的实际作用

使用官方 `powercontext[client,server]==1.2.0`，运行真实内嵌 HTTP 服务及 SQLite 存储。每个研究项目有独立 Scope；业务内容通过官方 SDK 写入、修订、退役与检索；交接保存为不可变 Revision，接手明确绑定已核对的版本，周报保留 MemoryCitation。独立的小型注册表只记录项目元信息。

不需要模型密钥：记忆由用户显式录入，检索采用 FTS，报告按确定规则组织。线上网站为介绍页；完整应用在本机运行，不开放无鉴权后端。

## 验证样例

先按 README 克隆指定分支、安装依赖，从空的 `data/demo` 目录执行示例脚本，再将 `YANXU_DATA_DIR` 指向同一目录启动应用。样例数据均为合成数据，不代表真实性能测量。

| 操作与输入 | 预期结果 | PowerContext 证据 |
| --- | --- | --- |
| 执行 `scripts/seed_demo.py --data-dir data/demo` | 创建写放大治理与多模态检索两个项目 | 两个不同 Scope |
| 在台账项目查看记忆 | 目标加六条有效内容，共七条活跃记忆；误写记录已退役 | `remember_memory`、`retire_memory_entry` |
| 查看问题「写入抖动是否完全来自 flush 抢占 IO」的历史 | v1、v2 均可读，条目 ID 不变，当前为已解决 | `revise_memory_entry`、版本历史 |
| 脚本以过期版本再次修订 | HTTP 409，错误码 `revision_conflict` | 真实服务端并发检查 |
| 在另一个项目搜索「合并」 | 命中 0 条 | Scope 隔离 |
| 保存并接手交接 | 交接 r1；漏填核对版本或核对项时被拒；完整核对后接手成功 | Handoff Revision 与 receipt Source |
| 退出脚本后启动应用，打开「恢复工作」 | 数据仍在；交接引用 3/3 可回溯；已解决问题不冒充待解决项 | SQLite 跨进程持久化、evidence checks |
| 打开「组会 / 周报」并生成、复制 Markdown | 7 条记忆引用、1 条资料出处，附录列出条目与版本 | 实际记忆引用 |

实跑日志：[播种](evidence/independent-m3-seed.txt)、[跨进程读回](evidence/independent-m3-restart.json)、[界面核对](evidence/independent-m3-ui.json)、[实际复制出的报告](evidence/ui/m3-reproduction-report.md)。随机生成的 ID 和时间每次运行不同；比较语义与数量即可。

## 验收范围与限制

独立运行完整测试套件：**43 passed in 29.61s**，见 [日志](evidence/independent-m3-pytest.txt)。其中 API 测试连接真实 PowerContext；编解码和静态页面测试不启动服务。桌面界面已实测建项、录入、修订历史、保存/接手交接、恢复和复制报告。

文件下载按钮尚未取得独立落盘验证；复制报告已验证。窄屏视觉未验收。当前没有真实用户规模或节省时间的效果研究，不提交合成数字作为提效成果。

## 提交状态

已于 2026-11-03 01:05（America/Phoenix）正式提测，平台显示「提测成功」；记录状态为「待执行」，尚无成绩。

提交的固定版本为 `7cabd5e7e5352bbe35de2e248a7c50eff4ca7a07`。平台表单只有仓库、Commit、Branch 和作品链接字段；Qoder UID、运行说明、验证样例及开发截图均随该版本包含在 `qoder/` 下。

[正式回执](evidence/submission.json) · [提测记录](https://open.oceanbase.com/train/TestRecord?questionId=600078)。后续归档回执的提交不改变上述已提测版本。
