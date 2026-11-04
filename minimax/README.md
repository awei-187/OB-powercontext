# MiniMax SDD 工程上下文模块

本地开发分支：`minimax-sdd`，基于官方 `2026-competition-ecosystem`
提交 `d647275c308e09b7b623f322a26f5c4e85734fb0`。所有作品文件放在本目录。

## 当前状态

评审快速入口见 [ACCEPTANCE.md](ACCEPTANCE.md)：六项要求、命令、预期结果及证据索引。

已建立业务规格、订单查询基线、目标功能测试和回归测试。
MiniMax 已完成状态筛选实现，6 项目标测试和 5 项原有回归测试全部通过，原始测试摘要未变。
已实现 seekdb 工程资料入库、真实全文检索、当前版本选择及原文来源输出。
已接入官方 PowerContext Memory，实现任务状态保存、版本更新、重启恢复及开发上下文复用。
已保存真实 MiniMax 请求、最终响应、候选、修改前后快照、补丁和测试日志。
已通过独立 Compose 数据库初始化与检索验证；赛事官方验收尚未执行。

## 样例任务

给 `sample_project/orders.py::list_orders` 增加订单状态筛选，先筛选再分页。
保留原有分页、顺序和输入保护行为。
有效规格见 `specs/orders-v1.md`，开发任务见 `tasks/order-status-filter.md`。
`specs/update-example.md` 仅描述后续规格更新验证，不作为初始有效规则导入。

## 本地运行

要求 Python 3.12+；样例和测试只使用标准库，无需 MiniMax 密钥。
在本目录执行：

```bash
python3 -m sample_project
python3 -m unittest discover -s tests -p 'test_regression.py' -v
python3 -m unittest discover -s tests -p 'test_target.py' -v
# 仅初次生成修改前基线时使用；现有 evidence/baseline/ 已保留，不要覆盖。
# python3 scripts/record_baseline.py
```

修改前快照的目标测试失败是缺少 status 功能，不是缺依赖或导入错误。
基线脚本保存真实日志、退出码、源码 SHA-256 和完整输入快照；
拒绝覆盖已记录的基线。后续修改后必须运行同一组测试，核对测试哈希未变化。

## 接入配置

将 `.env.example` 复制为 `.env` 并在本地填写。
上下文命令自动读取项目根目录 `.env`，同名进程环境变量优先。
配置按字面值读取，不执行 shell 表达式。只使用应用账号连接已有数据库。
不要提交 `.env`、真实密码或 API key。
本机 seekdb 地址为 `127.0.0.1:2881`，数据库 `minimax_sdd`，用户 `minimax_app`。
现有本机数据库的管理说明位于工作区仓库外的 `infra/seekdb/README.md`。
其他环境可使用本目录的 `compose.yaml` 和 `scripts/bootstrap_database.py` 独立初始化，见下文。

## 资料入库与上下文检索

在 WSL 中进入本目录，创建隔离环境并安装固定依赖：

```bash
uv sync --locked --python python3.12
```

已有本地 `.env` 时不要覆盖。新环境可先 `cp .env.example .env`，再填写数据库配置。
当前本机的 `.env` 已配置；命令不会输出密码。

```bash
.venv/bin/python -m sdd_context ingest
.venv/bin/python -m sdd_context prepare --task tasks/order-status-filter.md
.venv/bin/python -m sdd_context prepare --query 'order status filtering pagination'
```

`project.json` 明确列出有效资料及其角色；更新场景说明、历史快照和凭据不在导入清单中。
入库前会验证所有文件，成功后原子更新当前资料集合，保留每份正文的历史版本。
同路径的文件修订会更新当前版本，从清单移除的资料退出当前查询。
不同 `project_id` 的资料隔离。

检索按四类角色分别执行 seekdb `MATCH ... AGAINST` 全文查询，按相关度选择资料。
这是一版关键词检索实现，未接入 Embedding，不承诺跨语言语义匹配。
输出包含数据库中的完整正文、路径、SHA-256、行号范围、函数位置及规格条目编号。
不会从本地文件拼出预设答案。缺少任一必要角色时，输出 `missing_roles` 并以状态码 2 退出。
每次成功执行的 SQL、绑定参数和上下文写入 `runtime/queries/`，不记录连接密码。
运行数据默认不入 Git；审核后的无敏感信息验证材料保存在 `evidence/context/`。

完整上下文可保存供查看（运行 ingest 后 runtime 目录已存在）：

```bash
.venv/bin/python -m sdd_context prepare --task tasks/order-status-filter.md > runtime/prepared-context.json
```

## 验证本次上下文模块

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_context_inputs.py' -v
.venv/bin/python scripts/verify_context.py
```

集成验证必须连接真实 seekdb，不会用 mock 跳过数据库。
它在临时目录中复制业务资料，使用每次独立的数据库项目编号，测试：
四类来源与原文摘要一致、查询只读数据库、重复导入、规格更新、旧版本保留、
无效输入不影响当前版本、项目隔离、未命中查询及清单移除。
结束时仅清理该次验证项目的数据，不修改 `orders-demo` 和正式规格。
报告保存到 `evidence/context/verification-<run-id>.json`，含 SQL、结果及实际源码摘要。

## PowerContext 本地任务状态

依赖固定在官方 `powercontext` 1.2.0 的提交
`9db1753434162c0aa7c9f1189a1722e617880a52`，传递依赖由 `uv.lock` 固定。
运行在本项目 Python 环境中，无需另起 HTTP 服务，也无需模型 API key。

工程资料继续由 seekdb 管理；任务状态使用官方 SQLite Runtime，默认目录
`runtime/powercontext/`，其中 `memory.db` 是持久数据库，`scheduler.db` 是运行时调度库。
Runtime 退出会释放资源，数据保留供下一进程使用。
按项目和任务生成稳定的作用域创建键，再由 PowerContext 分配真实 Scope ID。
保存调用 `memory.remember`，更新调用 `memory.revise`，读回调用 `memory.list/get`。
输出携带精确 Memory revision、entry ID 和 entry version ID，不用自建 JSON 文件冒充存储。

从真实基线证据保存当前任务进度：

```bash
.venv/bin/python scripts/checkpoint_progress.py
```

脚本先核对原始业务资料和测试的摘要，然后将已完成事项、待办、实际测试退出码及日志摘要
保存到 PowerContext。如果业务代码已被 MiniMax 修改，不应再次使用此修改前检查点脚本。

退出后以新进程读取并使用：

```bash
.venv/bin/python -m sdd_context state-show --task-id order-status-filter
.venv/bin/python -m sdd_context prepare --task tasks/order-status-filter.md --task-id order-status-filter
```

返回的 `task_progress` 是从 PowerContext 重新读取的状态，用于后续开发上下文。
没有状态时返回 null，不生成虚假进度。历史进度不是当前有效规格，下一轮应核对实时资料。

后续保存更新后的任务记录可使用：

```bash
.venv/bin/python -m sdd_context state-save --input runtime/task-state-input.json
```

输入字段为 `task_id`、`objective`、`completed`、`pending`、`validations`；
每条 validation 包含实际执行的 `command` 数组、`exit_code`、`log_path`、`log_sha256`。
更新会修订同一 Memory 条目，并保留不可变的历史版本。
单份完整状态不得超过 PowerContext 的 8192 UTF-8 字节限制；不得存入凭据。

验证多个独立进程之间的恢复和复用：

```bash
.venv/bin/python scripts/verify_task_memory.py
```

验证使用临时 PowerContext 数据库，记录真实子进程命令、退出码、输出、库版本和源码摘要，
报告写入 `evidence/task-memory/`。它还验证状态更新、项目/任务隔离，以及非法输入不会覆盖已保存进度。
验证中的标记明确标注为 integration fixture，不作为实际业务完成记录。

## 后续验收清单

- [x] seekdb 保存工程资料，真实查询结果用于上下文。
- [x] 上下文定位有效规格、实现函数、目标和回归测试。
- [x] 规格修订重新导入后，不再使用旧规则。
- [x] MiniMax 真实参与本次代码修改，保存上下文、响应和补丁。
- [x] 同一组目标测试从功能失败变为通过，回归测试通过。
- [x] PowerContext 保存状态，重启后读取并用于后续上下文。
- [x] 新数据库初始化、隔离前后快照复验及技术说明（见下文与 TECHNICAL.md）。

完整模型记录只保存可交付的输入/输出与用量，不收集私有思维链。

## 正式 MiniMax 运行与证据

成功运行：`evidence/minimax/20261104T085127Z-f73a571f/`。
其模型响应来自 `20261104T084956Z-570d8c22` 的真实中国区请求，
适配器修复后复用已保存响应完成应用，没有再发一次模型请求。
之前的两次尝试保留原始失败状态，不能当作成功验收。

| 文件 | 核对用途 |
| --- | --- |
| `messages.json`、`context.json` | 实际发送的任务、seekdb 资料及恢复进度 |
| `seekdb-queries.json` | 真实入库与检索 SQL、参数和结果 |
| `response.json`、`candidate.py` | MiniMax 最终文本和候选代码，不含推理块 |
| `before.py`、`after.py`、`change.patch` | 修改前后行为及代码差异 |
| `before-*.log`、`candidate-*.log`、`after-*.log` | 同一组目标测试和回归测试的真实结果 |
| `saved-progress.json`、`report.json` | 完成后 PowerContext 引用、源码摘要及过程记录 |

mmx 1.0.28 对 JSON 回复会输出解析后的业务对象，因此该响应中未暴露实际模型 ID 和 token 用量；
报告对应字段保留 null，不捏造 API 元数据。请求使用当时 CLI 的默认模型，未显式指定 `--model`。

不调用模型，重置到独立临时目录复验前后状态：

```bash
.venv/bin/python scripts/replay_evidence.py --run evidence/minimax/20261104T085127Z-f73a571f
```

该命令使用相同测试，在不加载 site-packages 的 Python 中验证修改前失败、修改后通过。
临时目录每次新建并自动清理，不覆盖当前成功实现。

如需重新进行真实生成，应先在单独的实验副本恢复修改前快照、安装 mmx-cli、完成中国区登录，
运行 `checkpoint_progress.py` 后执行 `run_minimax_task.py`；会消耗 Plan 额度。
当前成功工作区会因基线摘要不同而拒绝重复覆盖。不要为复验删除现有证据。

## 独立部署与验收入口

要求 Linux/WSL、Python 3.12、uv、Docker 和 Docker Compose。
从参赛仓库进入 `minimax/` 后执行 `uv sync --locked --python python3.12`。
使用 `.env.example` 创建本地 `.env`，设置两个不同的随机密码
`SEEKDB_ROOT_PASSWORD` 与 `SEEKDB_PASSWORD`；已有本机实例不要重复启动相同端口。

```bash
docker compose --env-file .env up -d
.venv/bin/python scripts/bootstrap_database.py
.venv/bin/python -m sdd_context ingest
.venv/bin/python -m sdd_context prepare --task tasks/order-status-filter.md
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
.venv/bin/python scripts/verify_context.py
.venv/bin/python scripts/verify_task_memory.py
.venv/bin/python scripts/replay_evidence.py --run evidence/minimax/20261104T085127Z-f73a571f
```

`bootstrap_database.py` 只创建数据库及缺失账号，验证账号可用，不改已有账号密码。
显式停止用 `docker compose stop`，数据卷保留。重新导入替换当前项目资料；
前后代码重置通过 replay 的临时工作目录完成；状态验证使用独立临时 PowerContext 数据库。

也可一条命令验证全新数据库启动、账号初始化、入库、检索及全部单元测试：

```bash
.venv/bin/python scripts/verify_clean_setup.py
```

需要当前用户具有 Docker 权限；该命令使用随机独立 Compose 项目和端口，
结束后仅移除本次创建的容器及数据卷，不影响现有 `ob-minimax-seekdb`。
报告保存在 `evidence/clean-setup/`。新数据库验证及离线复验均不需要 MiniMax 密钥。
官方评审可以核对已有 MiniMax 开发记录，不要求重新生成同一个补丁。

## 从仅含交付文件的新目录完整复现

```bash
python3 scripts/verify_delivery.py
```

该入口先导出项目源码、锁文件、规格、测试和已审查证据，不带原 `.env`、`.venv`、`.git`、
`runtime/` 或 AMD 文件。随后在全新临时目录安装锁定依赖，创建独立 seekdb 实例和随机凭据，
依次运行初始化、入库、查询、所有单元测试、规格更新验证、PowerContext 跨进程恢复和前后快照复验。
不调用 MiniMax。集成脚本通过源码 SHA-256 记录实际代码身份，在无 Git 元数据时也可运行。
需要 uv、系统 Python 3.12、Docker Compose 及 Docker 使用权限；不需要预先激活本项目虚拟环境。
报告位于 `evidence/delivery/<run-id>/`，包含导出文件清单、安装日志、各命令退出码与新生成证据。
