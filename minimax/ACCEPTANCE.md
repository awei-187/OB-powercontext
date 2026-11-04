# MiniMax 赛题验收索引

本文件对应本地保存题面中的六项必做要求。全部通过才满足题面所述 20 分条件；
下述结果为本地验证，官方成绩以赛事验收为准。

## 评审入口

从仓库进入 `minimax/`，要求 Linux/WSL、Python 3.12、uv、Docker Compose 和 Docker 使用权限。

```bash
python3 scripts/verify_delivery.py
```

此命令只导出明确列出的交付文件，在全新临时目录中重新执行 `uv sync --locked`，
使用新的容器、数据卷、随机端口和随机密码，运行下表的验证命令。
不复制原 `.env`、`.venv`、`runtime/`、`.git` 或 AMD 目录，不需要 MiniMax 密钥，不调用模型。
新进程从空白 PowerContext 数据库保存并恢复状态；不是读取提交者现有数据库。
结束后仅清理该次创建的容器、数据卷和临时目录，报告及日志保存在 `evidence/delivery/<run-id>/`。
下载可复用包缓存，但不复用原虚拟环境，仍需要联网获得锁定依赖及镜像（若本机没有）。

## 本次完整复现结果

完整报告：[evidence/delivery/136e34aa1bcd42b8b9330bea22bb4887/report.json](evidence/delivery/136e34aa1bcd42b8b9330bea22bb4887/report.json)。

- 10 个执行步骤全部退出 0，包括临时容器与数据卷清理。
- 新虚拟环境由锁文件重新安装；导出目录无 `.git`，新生成的集成报告中 `git_base_commit=null`，源码摘要完整记录。
- 17 项单元测试通过；8 项资料/规格集成检查、6 项状态跨进程检查及前后快照复验通过。
- 本次未调用模型；已有 MiniMax 开发记录和原始业务测试均保持原样。

| 过程 | 本次日志／报告 |
| --- | --- |
| 新环境安装 | [fresh-install.log](evidence/delivery/136e34aa1bcd42b8b9330bea22bb4887/fresh-install.log) |
| 所有单元测试 | [all-tests.log](evidence/delivery/136e34aa1bcd42b8b9330bea22bb4887/all-tests.log) |
| 来源及规格更新 | [context-integration.log](evidence/delivery/136e34aa1bcd42b8b9330bea22bb4887/context-integration.log) |
| 状态重启与复用 | [powercontext-process-restart.log](evidence/delivery/136e34aa1bcd42b8b9330bea22bb4887/powercontext-process-restart.log) |
| 修改前后复验 | [before-after-replay.log](evidence/delivery/136e34aa1bcd42b8b9330bea22bb4887/before-after-replay.log) |

新生成的详细报告和测试日志归档在同目录的 `generated-evidence/`；
本报告文件清单记录的是执行时导出的版本，后续仅补充了这段结果链接。

以下命令均在已按 README 配置的项目目录运行；`.venv/bin/python` 简写为 Python 解释器入口。

## 六项官方要求与验证

| 官方必做项 | 运行命令／检查入口 | 预期结果 | 证据位置 |
| --- | --- | --- | --- |
| 能够运行 | `python3 scripts/verify_delivery.py` | 新目录锁定依赖安装、数据库初始化、入库、查询、测试和清理均退出 0；最终报告 `passed=true` | `evidence/delivery/<run-id>/report.json`、同目录逐步日志及导出文件摘要 |
| MiniMax 实际参与 | 核对成功运行的 `messages.json`、`response.json`、`change.patch` 和 `report.json` | 输入包含任务及检索上下文；最终代码与候选一致；仅修改订单实现；实际中国区 CLI 调用可追溯 | 下方“真实模型记录”所列三个目录 |
| 上下文正确 | `.venv/bin/python -m sdd_context prepare --task tasks/order-status-filter.md`；`.venv/bin/python scripts/verify_context.py` | 四类来源齐全；原文与摘要一致；更新为规格 revision 2 后检索使用新版，旧版保留，不返回固定答案 | `evidence/context/verification-*.json`；完整复现报告的 `generated-evidence/evidence/context/` |
| 数据库实际参与 | `.venv/bin/python -m sdd_context ingest`，再运行上条查询 | 实际执行 seekdb SQL、全文检索得分为正；即使临时副本源文件不可用也能读出入库正文 | 模型成功记录中的 `seekdb-queries.json`、`context.json`；`verify_context.py` 的查询记录 |
| 状态能够复用 | `.venv/bin/python scripts/verify_task_memory.py` | 写进程结束后，新进程恢复同一状态与引用；第三个 prepare 进程组合 seekdb 来源和恢复状态；更新、隔离、非法输入保护均通过 | `evidence/task-memory/verification-*.json`；完整复现报告的对应 `generated-evidence/` |
| 代码修改有效 | `.venv/bin/python scripts/replay_evidence.py --run evidence/minimax/20261104T085127Z-f73a571f` | 原始目标测试修改前失败，修改后 6 项通过；5 项回归测试前后通过；测试 SHA-256 相同 | 成功运行的前后测试日志及 `report.json`，`evidence/replay/*/report.json` |

这些业务测试是本作品根据规格自行设计的验证样例，不是赛事公开判题脚本。
单独通过业务测试不代表整道赛题通过。

## 样例及必要上下文来源

- **任务**：`tasks/order-status-filter.md`；增加状态筛选，保持原有分页行为。
- **有效规格**：`specs/orders-v1.md`。ORD-001～004 为兼容行为，ORD-005～008 为新增行为。
- **修改位置**：`sample_project/orders.py::list_orders`。
- **目标测试**：`tests/test_target.py`。覆盖过滤顺序、有效状态、None、无匹配、非法输入和输入保护。
- **回归测试**：`tests/test_regression.py`。覆盖分页、顺序、空结果、参数边界及返回副本。
- **入库清单**：`project.json`。仅四份有效资料；不导入更新场景说明或证据快照作为当前规格。
- **状态**：`task_progress` 包含 objective、completed、pending、validations，以及 PowerContext Scope 和精确 citation。

`specs/update-example.md` 是更新场景说明，不是初始有效规则。
规格更新验证在临时副本和独立数据库项目编号中进行，不更改提交的 revision 1 业务规格。

## 真实模型记录

成功应用目录：`evidence/minimax/20261104T085127Z-f73a571f/`。

1. `20261104T084756Z-470c7bb7`：真实请求后适配器格式处理失败，未应用代码；无完整最终响应可供复用。
2. `20261104T084956Z-570d8c22`：真实中国区请求成功，最终代码响应已保存；格式解析失败，未应用代码。
3. `20261104T085127Z-f73a571f`：修复适配器后复用第 2 次已保存响应，验证候选、应用代码、运行前后相同测试并保存进度；本次没有新模型调用。

成功目录中的 `reused_model_response_from` 和原模型命令记录上述关系。
`response.json` 保存最终文本，不保存私有推理；`candidate.py`、`after.py` 和当前订单实现的摘要对应。
`before.py` 及原始 `evidence/baseline/` 保留修改前版本。不得将前两次失败记录标成通过。

实际 CLI 为 mmx 1.0.28，请求使用中国区及当时 CLI 默认模型。
该 CLI 对业务 JSON 输出未暴露模型 ID、request ID 和 token 用量，因此报告未填写不存在的数据；
`cli-text-help.txt` 是 CLI 默认模型说明，不能视为服务器返回的模型 ID。
`quota-after.json` 为调用后额度快照，不是单次调用的精确计费证明。
题面允许评审核对开发记录，不要求再次生成完全相同的补丁。

## 重置、复现及边界

- `replay_evidence.py` 每次创建新临时业务目录，分别加载 before/after 快照，用同一组测试复验；不覆盖成功实现。
- `verify_context.py` 使用独立数据库项目编号，结束后只清理该次测试数据。
- `verify_task_memory.py` 每次使用空白临时 PowerContext 数据库，自动清理，不依赖 `runtime/powercontext/`。
- `verify_delivery.py` 使用全新独立数据库和存储，运行结束清理该次资源；原有数据库和工作目录不变。
- 代码身份以导出文件清单和 SHA-256 为准；无 `.git` 时 `git_base_commit=null` 是正常的，不会伪造提交编号。
- 官网提测应填写实际推送的完整 commit SHA 和对应分支，并确认评测读取权限；旧报告中的基线提交不代替最终交付版本。
- 新的真实模型生成需要有效 MiniMax 中国区认证，会消耗额度；完整本地验收与已有补丁复验不需要模型凭据。

技术分工与限制见 `TECHNICAL.md`；逐步配置见 `README.md`。
