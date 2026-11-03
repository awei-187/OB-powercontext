# 研续 Yanxu · 开发验证记录（M1 + M2）

本文件只记录**真实执行过的命令与真实输出**。没有跑过的不写，跑失败的原样保留。
需求与验收标准定义见 [PROJECT.md](PROJECT.md)，快速上手见 [README.md](README.md)。

验证日期：2026-11-02（本机时区 -0700）。

> **M2 更正说明（2026-11-02）**
>
> 下面 §1–§11 是 M1 的原始记录，**一字未改地保留**，包括其中后来被证明说过头的结论。
> 每处需要更正的地方就地加了一个「⚠ M2 更正」小块，写明原结论错在哪、现在的真实状态是什么。
> 需要更正的共四处：§6 开头的「真实浏览器」表述、§7.3 的「本期已解决」小节命名、
> §10 里 A7 的通过结论、§11 里对 M2 剩余项的预估。
> M2 本轮实际做的事与新证据在 §12–§17。
>
> 最关键的一条更正：**M1 宣称的界面验收不成立。**
> M1 期间 Qoder 内置浏览器面板不可见（`viewport=0x0`、`visibilityState=hidden`），
> 我当时用「驱动真实 DOM 事件」的方式跑完了全部界面流程并据此写下 §6，
> 但协调人在真实可见的 Edge 里打开同一页面时，历史抽屉与新建弹窗一进页面就同时压在界面上、
> 关掉也隐藏不了（[evidence/ui/m1-ledger.png](evidence/ui/m1-ledger.png)）。
> 也就是说：DOM 事件跑得通 ≠ 人能用。这个 P0 的根因与修复见 §12。
> M2 期间浏览器面板依然不可见，因此**界面可用性验收再次移交协调人**，见 §12.4。

---

## 1. 验证环境

| 项 | 实测值 |
|---|---|
| 操作系统 | Windows 11，`10.0.26200` |
| Python | `3.11.17 \| packaged by Anaconda, Inc. \| (main, Oct 1 2026, 20:16:54) [MSC v.1942 64 bit (AMD64)]` |
| 解释器路径 | `D:\conda\envs\oceanbase\python.exe`（既有环境，未新建） |
| Node | `v24.21.0` |
| powercontext | `1.2.0` |
| fastapi / starlette | `0.162.0` / `1.10.0` |
| uvicorn / httpx | `0.54.0` / `0.28.1` |
| pydantic / pydantic-settings | `2.14.2` / `2.16.2` |
| sqlalchemy / aiosqlite | `2.1.6` / `0.22.1` |
| pytest | `9.2.0` |
| 模型密钥 | **未配置任何一项**。`InferenceConfig()` 全字段为 None |

依赖快照：

- 安装前 `pip freeze`：[evidence/dependencies/pip-freeze-before.txt](evidence/dependencies/pip-freeze-before.txt)
  —— 该 Conda 环境安装前只有 `packaging==26.3`、pip、setuptools、wheel，因此安装不存在覆盖既有包的风险。
- 完整安装日志：[evidence/dependencies/pip-install.log](evidence/dependencies/pip-install.log)（433 行）
- 安装后 `pip freeze`：[evidence/dependencies/pip-freeze-after.txt](evidence/dependencies/pip-freeze-after.txt)（124 个包）

实际安装命令：

```powershell
python -m pip install "powercontext[cli,client,server]==1.2.0" pytest
```

`requirements.txt` 收敛为 `powercontext[client,server]==1.2.0` + `pytest==9.2.0`：
`client` extra 提供 `PowerContextClient` 与 httpx，`server` extra 提供 `create_server_app`、
fastapi、uvicorn，以及 SQLite 持久化所需的 `sqlalchemy[asyncio]` / `aiosqlite` / `sqlite-vec`。
`cli` extra 研续并不使用（当时一并装了，故日志里可见）。

---

## 2. API 核对方式

按要求「API 从官方资料核对，不能猜」。实际做法有三层，全部只读，未修改 `E:\Ocean Base\dot-tasks\powercontext-delta`，
也未读取其中任何凭据配置：

1. 阅读该目录下的 `README_CN.md`、`docs/`、`openapi/powercontext.yaml` 与 `examples/jupyter/_tutorial.py`；
2. 对已安装的 `powercontext==1.2.0` 做运行时自省（`inspect.signature` / `model_fields` / `dir(client)`）；
3. 用真实请求打内嵌 Server，按返回结果修正。

第 2、3 步纠正了多处凭文档容易猜错的细节，例如：

- `CurrentWorkHandoff` 的字段名是 `schema_`（alias `schema`），且 `extra="forbid"`；
- `HandoffCitation` 是 `RootModel`，只有一个 `root` 字段；
- `PreparedContext` 的字段是 `{schema_, status, content, content_bytes}`；
- `handoff_current_work(request)` 只接受 `HandoffCurrentWorkRequest` 对象，传 scope 字符串会在客户端就抛
  `TypeError: Request must serialize to an object.`（实测）；
- PowerContext **没有** list-scopes 端点，这是研续保留一个极薄本地项目索引的唯一原因。

内嵌 Server 的启动方式直接沿用官方 `examples/jupyter/_tutorial.py` 的既有模式
（`create_server_app` + 自选空闲回环端口 + `uvicorn.Server` 跑在 daemon 线程），未复制、未改写 PowerContext 源码。

---

## 3. 持久化 smoke test（A2）

完整记录：[evidence/powercontext/smoke-persistence.md](evidence/powercontext/smoke-persistence.md)。

两个**独立 OS 进程**共用同一个 SQLite 文件：

```console
$ python scripts/smoke_persistence.py write
[write] PowerContext Server 已启动: http://127.0.0.1:60141
[write] SQLite 文件: E:\Ocean Base\qoder-competition\qoder\data\smoke\smoke.db
[write] capabilities.memory_extraction = False
[write] capabilities.search_modes      = [<MemorySearchMode.AUTO: 'auto'>, <MemorySearchMode.FTS: 'fts'>]
[write] scope_id = scp_3qwxhmv549mb3j8q0j0adb4snv (version=1)
[write] 已写入记忆 entry_id=mem_ent_6a820588293844d58d52e3a5eb0cce5b
[write]            entry_version_id=mem_ver_8a5af46692e0425a8a08b3e838a221cf
[write]            memory_ref={'family': 'memory', 'artifact_id': 'memory', 'revision': 1}
[write] 写后立即 FTS 检索 'Decimal': 1 命中, mode=fts
[write] Server 已停止，进程即将退出。
exit=0
```

进程完全退出后，新进程重开同一文件：

```console
$ python scripts/smoke_persistence.py read
[read] 新进程重开 PowerContext Server: http://127.0.0.1:57290
[read] 复用同一 SQLite: ...\data\smoke\smoke.db (exists=True)
[read] Scope 幂等复用: scp_3qwxhmv549mb3j8q0j0adb4snv == scp_3qwxhmv549mb3j8q0j0adb4snv -> True
[read] list_memory_entries 返回 1 条活跃记忆
[read] get_memory_entry(旧 citation) -> kind=decision version=1 state=active
[read] 结论: 通过 —— 记忆跨进程真实持久化，读回内容与写入完全一致。
exit=0
```

落盘文件：`data/smoke/smoke.db`，610304 字节。无 mock、无内存数据库。

---

## 4. 测试套件

```console
$ python -m pytest -v
============================= test session starts =============================
platform win32 -- Python 3.11.17, pytest-9.2.0, pluggy-1.7.0
rootdir: E:\Ocean Base\qoder-competition\qoder
configfile: pytest.ini
testpaths: tests
plugins: anyio-4.16.0, platformdirs-4.14.3
collected 15 items

tests\test_api_e2e.py .......                                            [ 46%]
tests\test_codec.py ........                                             [100%]

============================= 15 passed in 11.77s =============================
```

15 个测试全部通过，**没有任何 mock**：每个端到端测试都通过 `app.router.lifespan_context` 拉起
真实的内嵌 PowerContext Server（真实 SQLite，临时目录），再用 `httpx.ASGITransport` 打真实 HTTP 路由。

上面这段是 §7 全部修复完成**之后**的最终代码状态上跑的；收尾时又复跑一次确认，
同样 `15 passed in 11.60s`。

| 测试 | 覆盖 |
|---|---|
| `test_codec.py` ×8 | YX1 编解码：字段往返、空头部键省略、正文含 `---`、头部换行被拒、标签去重、CRLF 归一、外来文本容忍、NFC/UTF-8 字节数 |
| `test_full_continuity_loop` | A5 / A6 / A7：录入 → 交接 → 恢复 → 周报全链路 |
| `test_project_isolation` | A1：跨项目命中数为 0 |
| `test_revision_history_and_conflict` | A3 / A4：revise 后 entry_id 不变、旧快照可读回、`op` 序列 `add → revise → deactivate`、真实 409 |
| `test_real_error_surfacing` | A8：422 超长、404 项目不存在、400 交接状态为空、直连 `prepare_handoff` 得到真实 503 `handoff_generation_unavailable` |
| `test_transport_error_when_server_stopped` | A8：内嵌 Server 停止后必须是可归因于 PowerContext 的 5xx 真实错误 |
| `test_no_model_keys_required` | A9：版本 1.2.0、sqlite、`memory_extraction=False`、`handoff_generation=False`、`search_modes` 含 fts |
| `test_data_survives_full_restart` | A2 / A10：两个独立 app 实例共用同一数据目录 |

`pytest.ini` 里设了 `--basetemp=.pytest-tmp`：本机 `%TEMP%\pytest-of-wjp` 目录不可写
（`PermissionError: [WinError 5]`），改用项目内临时目录绕开，**没有修改任何系统权限**。

---

## 5. 示例数据播种（clean-reproduction）

从**空数据目录**跑通完整流程，脚本只调用研续自己的 HTTP API：

```console
$ python scripts/seed_demo.py --force
研续示例数据播种 · 全部写入真实 PowerContext
  PowerContext 版本        1.2.0
  内嵌 Server              http://127.0.0.1:55189
  存储后端                   sqlite
  记忆数据库                  ...\data\demo\powercontext\powercontext.db
  自动记忆提取                 False
  可用检索方式                 auto, fts

[1/7] 创建两个项目（各自独立 Scope）
  【示例】高吞吐量 KV 存储的写放大治理   prj_feebd19e15de4a19 / scp_4vas6p9m2kezdcp8fr1qbsdzw8
  【示例】多模态检索的召回优化         prj_7760a03ab5b64975 / scp_2we65vk1xcn43v98bpenkvghyh

[2/7] 向台账项目写入 7 条记忆
  工作记录 · 基线复现：默认 leveled 合并 mem_c3ad1bcd@v1 state=active
  已确认决策 · 合并策略改为 size-tiered + 每日凌 mem_f8501fc4@v1 state=active
  未解决问题 · 写入抖动是否完全来自 flush 抢占 IO mem_99d5ef22@v1 state=active
  下一步 · 用 blktrace 抓一次抖动现场的 IO 队 mem_cec3e1e1@v1 state=active
  待办 · 补齐 4KB / 16KB value 的对比矩 mem_2b129983@v1 state=active
  资料出处 · OceanBase LSM-Tree 合并策略设 mem_1ade2280@v1 state=active
  工作记录 · 一次录错的工作记录（稍后会被退役） mem_3c67bd70@v1 state=active

[3/7] 修订一条未解决问题（revise 保留 entry_id，推进版本）
  修订前 / 修订后              mem_99d5ef22@v1 → mem_99d5ef22@v2
  entry_id 是否不变          True
  工件修订号                  r8 → r9

[4/7] 用过期引用再修订一次，确认服务端真的会拒绝
  HTTP 状态                409
  错误码                    powercontext_server_response
  服务端错误码                 revision_conflict
  服务端消息                  The Memory Revision is stale.
  研续给出的提示                记忆已被另一次修订推进，请刷新后基于最新版本重试。

[5/7] 退役一条误写记忆（无物理删除，历史保留）
  退役后 state              inactive
  可读回的历史快照数              1
  变更操作序列                 add → deactivate

[6/7] 保存交接（本人撰写，引用真实记忆 → basis=verified）
  预填已确认状态                2 条（均带真实 MemoryCitation）
  交接工件                   handoff/handoff@r1
  边界 Source              yanxu-handoff-20261102-090844-0d0a40
  未核对就接手 →               HTTP 400 handoff_ack_requires_check
  核对后接手 →                receipt Source yanxu-ack-20261102-090845-9d7ce1

[7/7] 校验隔离并生成周报
  另一项目检索「合并」             命中 0 条（应为 0）
  恢复简报 · 活跃记忆            7
  恢复简报 · 上次交接            Revision 1
  证据回溯检查                 3/3 条仍可回溯

周报 Markdown 已写出：...\data\demo\示例周报.md（2870 字符）
```

第 4 步是**故意**用过期引用触发冲突，因此内嵌 Server 会打印一段 `RevisionConflictError` 回溯，
脚本已在输出里说明这是预期的。示例内容全部带【示例】前缀，符合
[evidence/acceptance-plan.json](evidence/acceptance-plan.json) 的 `measurement_policy`
（合成数据必须标注为合成数据）。

---

## 6. 浏览器端真实验证

启动：

```powershell
$env:YANXU_DATA_DIR = "$PWD\data\ui-verify"; $env:YANXU_PORT = "8123"
python -m app.main
```

`GET /api/system/status` 实测返回内嵌 Server 地址、`powercontext_version: "1.2.0"`、
`storage_backend: "sqlite"`，以及 12 个 prompt 能力全部 `status: "disabled"` /
`reason: "provider_not_configured"`。页面顶栏据此显示
「PowerContext 1.2.0 · sqlite · 已连接 · 检索 auto/fts」，并诚实列出能力边界。

以下每一步都是在真实浏览器页面里驱动真实 DOM 事件、打真实后端完成的。

> **⚠ M2 更正：上面这句「真实浏览器」说过头了，本节结论降级为「后端与 DOM 行为已验证，界面可用性未验证」。**
>
> - 准确的说法是：页面运行在真实 Chromium 渲染引擎里，后端是真实的内嵌 PowerContext，
>   交互是用脚本派发 DOM 事件完成的。但那个浏览器面板**没有可见表面**
>   （M1 实测 `viewport=0x0`、`visibilityState=hidden`；M2 复测 `outerWidth=0`、`visibilityState=hidden`，
>   截图工具直接报 `NATIVE_BROWSER_VIEWPORT_UNAVAILABLE`）。
> - 因此本节**不能**作为「人能用鼠标完成这些流程」的证据。反例已经出现：
>   本节全部步骤跑通的同一份代码，在可见 Edge 里一进页面就同时弹出历史抽屉和新建弹窗，
>   遮挡主界面且关不掉（§12 的 P0）。脚本派发的事件绕过了「元素是否真的可见、可点」这一层，
>   所以它对 CSS 层叠导致的遮挡是盲的。
> - 本节中**仍然成立**的部分：所有后端行为、返回体、PowerContext 引用与版本号、
>   错误码与 `request_id`、下载/复制产物的字节数——这些与浏览器可见性无关，
>   且大多已由 §4 的自动化测试独立覆盖。
> - 本节中**不再成立**的部分：任何关于「界面显示正确」「样式生效」「用户能看到/点到」的描述，
>   包括 §6.9 里「字节计数器变红」「红色横幅显示」这类纯视觉断言。这些需要可见浏览器复验。
> - 原文按要求保留，不删除、不改写。

### 6.1 创建项目与录入

创建「高吞吐量 KV 存储的写放大治理」，得到独立 Scope `scp_23z1j4vhe9df8pdr4zg1hph10k`；
研究目标作为第一条记忆写入，引用 `mem_10b577cd@v1`，变更操作 `add`，原因「创建项目时录入」。

随后通过表单依次写入 工作记录 / 已确认决策 / 未解决问题 / 下一步 / 待办 / 资料出处，
共 7 条活跃记忆。类型切换会联动状态选项、占位符与「出处链接」字段的可见性
（实测选到「资料出处」时 URL 字段可见）。

### 6.2 检索（FTS）

在检索框输入「合并」：

```
PowerContext FTS 命中 3 条（检索限定在本项目 Scope 内）。
  decision       合并策略改为 size-tiered + 每日凌晨 major compaction   mem_9846e69e@v1
  record         基线复现：默认 leveled 合并                        mem_e55eb27f@v1
  source         OceanBase LSM-Tree 合并策略设计说明                 mem_eca9b47c@v1
```

### 6.3 修订与历史抽屉

把「写入抖动是否完全来自 flush 抢占 IO」从未解决改为已解决：引用从 `mem_3764b3a9@v1`
推进到 `mem_3764b3a9@v2`，**entry_id 不变**，状态胶囊显示「已解决」，提交按钮文案变为「提交修订（revise）」。

历史抽屉实测内容（全部由 PowerContext 读回）：

```
类型 未解决问题 · entry_id mem_ent_3764b3a9e4204d79bd135c5948db2e46
mem_3764b3a9@v2 · 当前   条目版本 v2 · 工件 r9 · active
  已确认：blktrace 抓到抖动现场 flush 与前台写共用同一 IO 队列，队列深度峰值 64。…
  PowerContext 原始 memory text：YX1 title=… status=resolved tags=待验证 --- …
mem_3764b3a9@v1          条目版本 v1 · 工件 r4 · active
  改成 size-tiered 后仍有 2ms 量级抖动。…
  PowerContext 原始 memory text：YX1 title=… status=open tags=待验证 --- …
变更日志（list_memory_changes）
  r4  add     原因 —                            entry_version_id b6f8d5cd4dcb
  r9  revise  原因 blktrace 证据到位，问题已关闭      entry_version_id c18a59bf99c9
```

### 6.4 退役

对一条误写入的记忆执行退役（弹出原因输入，原因写入 PowerContext 变更历史）：
提示「已退役 · 历史完整保留」，活跃条目从 8 条降为 7 条。
勾选「显示已退役」后回到 8 条，且该条带 `is-inactive` 样式；取消勾选回到 7 条。

### 6.5 保存交接

切到「保存交接」，表单按当前记忆自动预填，且引用是**真实 MemoryCitation**：

```
交接目标   把 P99 写延迟从 12ms 降到 8ms 以内，且写放大因子不超过 6
交接判定   continuable
已确认状态  ✓ mem_9846e69e   合并策略改为 size-tiered + 每日凌晨 major compaction
          ✓ mem_e55eb27f   基线复现：默认 leveled 合并
下一步     ✓ mem_e274ce87   用 blktrace 抓一次抖动现场的 IO 队列深度
```

提交后得到 `handoff/handoff@r3`，右侧「当前交接状态」显示每条状态同时带两类引用：
`source · 来源 yanxu-handoff-20261102-074602-884872`（系统溯源 Source）与
`memory · 记忆 mem_ent_9846e69e…@r10`（研续附上的真实记忆引用）。

**新会话接手**的约束门实测：`status=accepted` 但未勾选「我已核对上述状态与当前实际情况一致」时被拒绝——

```
接手失败 × PowerContext 规定：status=accepted 时 receiver_checks 必须全部为 confirmed。
请先勾选「我已核对上述状态与当前实际情况一致」。
HTTP 400 · 错误码 handoff_ack_requires_check
```

勾选后接手成功，落下真实 receipt Source：`yanxu-ack-20261102-075351-e66783`。

### 6.6 恢复工作

「恢复工作」面板一屏返回（全部实时读自 PowerContext）：

- 交接英雄区：`上次交接 · Revision 3`、目标、`判定：可继续`、`信任级别：untrusted_history`、下一步；
- **证据回溯检查**（PowerContext 自己的 `evidence_checks`）：
  `✓ state #0 所引证据仍可回溯`、`✓ state #1 所引证据仍可回溯`、`✓ next_action 所引证据仍可回溯`；
- 交接时明确未覆盖：`尚未评估 io_uring 批量提交对前台延迟的影响`；
- 7 张分类卡片：研究目标 1 / 已确认决策 1 / 未解决问题 1 / 下一步 1 / 未完成待办 1 / 最近工作记录 1 / 资料出处 1，
  每条带 `mem_xxxxxxxx@vN` 引用；
- `PowerContext 打包上下文 ready · 1764 B`，展开可见 `BEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1`
  原文与其 `trust: untrusted_history` 前导语。

### 6.7 组会 / 周报

生成周报得到 2855 字符 Markdown，八个章节 + 来源追溯附录。附录把每条引用展开为完整可回溯信息：

```
| 引用 | 类型 | entry_id | entry_version_id | 条目版本 | 记忆工件版本 | 状态 | 变更序列 |
| mem_3764b3a9@v2 | 未解决问题 | mem_ent_3764b3a9e4204d79bd135c5948db2e46 | mem_ver_87f89b76df5240baa173c18a59bf99c9 | 2 | 10 | active | add → revise |
…
_本报告由「研续 Yanxu」基于 PowerContext 记忆自动生成，共引用 7 条记忆、1 条资料出处。_
```

已退役条目**不出现**在报告里（引用 7 条而非 8 条）。报告头明确标注 Scope、统计区间，
并说明「工作记录与已完成待办按区间过滤；目标、决策、未解决问题、下一步、资料出处为当前有效状态」。

下载与复制实测（通过拦截 `URL.createObjectURL` 与 `navigator.clipboard.writeText` 取真实产物）：

- 下载：Blob `4378` 字节、`text/markdown;charset=utf-8`、文件名 `周报 · 高吞吐量 KV 存储的写放大治理-2026-11-02.md`；
- 复制：`clipboard.writeText` 收到 2855 字符且与页面报告**完全一致**；因页面未聚焦而被拒后，
  按设计回退到 `document.execCommand("copy")`，提示「Markdown 已复制」。

### 6.8 项目隔离

创建第二个项目「多模态检索的召回优化」（Scope `scp_59t9w49gnvg688w8wpyhf7f6jk`），
它只显示自己的 1 条研究目标。在第二个项目里检索同一个词「合并」：

```
PowerContext FTS 命中 0 条（检索限定在本项目 Scope 内）。
```

切回第一个项目，7 条记忆与各自引用完好。

### 6.9 错误路径（A8）

**超长正文 → 真实 422。** 正文填 4000 个汉字，字节计数器在提交前就变红显示 `12030 / 8192 字节`
（class `byte-counter is-over`）；仍然提交，红色横幅显示 PowerContext 原文：

```
写入失败 × The request is invalid.
内容超过 PowerContext 单条记忆 8192 UTF-8 字节上限，请拆分或精简正文。
HTTP 422 · 错误码 powercontext_server_response · 服务端码 invalid_request
· request_id 34c872fadb8ff9a6
· details {"code":"text-too-long","message":"memory entry text must not exceed 8192 UTF-8 bytes"}
```

**陈旧引用 → 真实 409。** 打开某条记忆的修订表单（持有 v1 引用），
在表单背后用另一个请求把同一条推进到 v2，再提交表单：

```
修订失败 × The Memory Revision is stale.
记忆已被另一次修订推进，请刷新后基于最新版本重试。
HTTP 409 · 错误码 powercontext_server_response · 服务端码 revision_conflict
· request_id 25751f9e0950469e
```

在此之前，研续自己的前置校验先拦下了「修订未填依据」：
`HTTP 400 · 错误码 reason_required · 修订必须填写依据，这是日后回溯的关键。`

**服务不可用 → 5xx，绝不返回空列表。** 由 `test_transport_error_when_server_stopped` 覆盖，见 §7.2。

浏览器控制台在整个验证过程中**没有任何 JS 异常**；唯一的两条 error 记录是上面故意触发的 422 与 409。

### 6.10 重启与清空浏览器存储（A2 / A10）

杀掉服务进程后重新 `python -m app.main`（同一数据目录），页面重新打开：

- 项目列表、7 条记忆、引用与版本号（含 `mem_e55eb27f@v2`、`mem_3764b3a9@v2`）、
  变更序列 `add → revise`、交接 Revision、恢复简报全部从 PowerContext 读回；
- 交接草稿重新预填出带真实引用的已确认状态。

随后执行 `localStorage.clear(); sessionStorage.clear();` 并重载页面。
清空前 localStorage 里**只有一个键**：

```json
{ "yanxu.ui.lastProjectId": "prj_4268d78bba5a4534" }
```

清空重载后，2 个项目与 7 条记忆依然完整显示，localStorage 里只重新写回同一个 UI 偏好键。
业务数据没有任何一项来自浏览器存储。

---

## 7. 验证中发现并修复的问题

### 7.1 交接草稿在切换标签页时是陈旧的（真实缺陷）

`loadHandoffPanel()` 原本只在选中项目时调用一次。在「工作台账」里录入若干决策之后切到「保存交接」，
预填的仍是录入之前的草稿——用户可能据此提交一份**漏掉真实决策**的交接。

修复：切换标签页时按面板重新拉取数据（`refreshActivePanel`）。
同时引入 `handoffDirty` 标记：用户已经在交接表单里动过手就不覆盖其输入，
只刷新右侧只读的「当前交接状态」，预填留给显式的「按当前记忆重新预填」按钮；
`refreshAll()` 也遵循同一规则，避免退役操作顺带清掉用户正在写的交接。

修复后实测：录入 7 条记忆 → 切到「保存交接」→ 预填出 2 条带真实引用的已确认状态与带引用的下一步。

### 7.2 verified 引用靠文本回查，会被静默降级（真实缺陷）

提交交接时，原实现用 `draftState.find(item => item.text === claim.text)` 把界面上的声明
匹配回草稿里的引用。一旦用户改过某个预填声明的文字，匹配失败，`citation` 变成 `null`，
这句话就会以 `basis="declared"` 提交——**界面上却仍显示 ✓ verified**。这是一处会误导用户的不诚实。

修复：引用改为绑定在 DOM 行上（`data-citation` / `data-cited-text`），
提交时直接读行上的引用；并新增 `syncClaimCitation()`——正文一旦被改得与所引记忆不一致，
当场把标记降级为 `declared`，并在 tooltip 里说明原因
（「正文已与所引记忆不一致，自动降级为本人陈述（basis=declared）」）。
「下一步」引用走同一套机制。

### 7.3 周报把已解决的问题挂在「未解决问题」标题下（真实缺陷）

`## 四、未解决问题` 原本把 `status=resolved` 的条目也列进去，只用 `- [x]` 区分，
读者会误以为该问题仍然悬着。

修复：拆成「四、未解决问题」（只列 open / blocked）与子节「本期已解决」。修复后实测输出：

```markdown
## 四、未解决问题

_当前没有未解决的问题。_

### 本期已解决

- [x] **写入抖动是否完全来自 flush 抢占 IO** — 已确认：blktrace 抓到… `mem_3764b3a9@v2`
```

> **⚠ M2 更正：「本期已解决」这个命名本身又是一处不诚实，已改掉。**
>
> 子节挂在「统计区间」之下、又叫「**本期**已解决」，读者自然会理解成
> 「这个问题是在本统计区间内解决的」。但研续根本没有解决时间可用：
> PowerContext 的 `EntryChange` 只有 `revision / op / reason / entry_version_id`，**没有时间戳**，
> 条目自己的 `date` 是「记录日期」，不是「解决日期」。把记录日期当解决时间报出去就是编造。
>
> 现在的实现：子节标题改为 `### 已解决（当前有效状态，不按区间过滤）`，
> 并在其后追加一句说明「研续不记录问题的解决时间，此节按当前状态列出，不代表发生在统计区间内」；
> 报告头部也新增一行「时间口径」，把区间到底过滤什么、不过滤什么写进正文。
> 回归测试 `test_report_time_semantics_and_citation_honesty` 现在断言
> `"本期已解决" not in markdown`，防止这个说法回来。详见 §13.4。

### 7.4 `ref_label` 用了会漂移的修订号（真实缺陷）

原先短引用取 `memory_ref.revision`（形如 `mem_20f8a201@r2`）。但那是**整个记忆工件**的全局修订号，
任何一条记忆写入都会让它前进——同一条记忆在两次读取之间会显示成不同引用，
周报断言也因此失败过（期望 `@r2`，实际 `@r7`）。

修复：短引用改用条目自身的 `version`（`mem_20f8a201@v2`），
周报附录把「条目版本」与「记忆工件版本」拆成两列分别呈现，不再混淆两个不同层级的版本号。

### 7.5 TransportError 丢掉了真正的失败原因（可观测性缺陷）

PowerContext SDK 用 `raise TransportError(path) from exc` 把真实的 httpx 异常链在 `__cause__` 上，
而研续的错误映射只显示「无法连接 PowerContext Server」，把超时、协议错误和连接被拒混为一谈。

修复：`describe_powercontext_error()` 现在把 `__cause__` 的类型与消息放进 `details.cause`，
并按异常类型补一句中文提示（`ConnectTimeout` / `ReadTimeout` / `PoolTimeout` / `ConnectError` /
`RemoteProtocolError` 等）。

### 7.6 seed 脚本的两处真实错误

- `sys.insert(...)` 写错，应为 `sys.path.insert(...)`——首次运行即 `AttributeError`，已修。
- 用**写入时**拿到的 citation 去 revise，被服务端以 409 拒绝：
  `powercontext.errors.RevisionConflictError: artifact is not the latest revision`。

第二条是本次验证最有价值的一条认知：`MemoryCitation.memory_ref.revision` 指向的是
**整个记忆工件**的修订号，写完一条记忆后再写别的记忆，先前那个 citation 就过期了。
因此每次 revise / retire 之前都必须重新读回条目拿当下有效的 citation。
脚本已加 `_fresh()` 帮助函数并在注释里写明原因；研续的 UI 本来就是「每次进入台账都重新拉取列表」，
所以界面上的引用是新鲜的，只有在真正并发修改时才会撞上 409——那时会如实显示冲突（见 §6.9）。

Windows 控制台默认 GBK 会把中文示例数据打成乱码，脚本已对本进程的 stdout/stderr 做 UTF-8 reconfigure
（不改系统区域设置）。

---

## 8. 环境发现（非研续缺陷，但影响判读）

### 8.1 本机有组件会在无监听的回环端口上代答 HTTP 502

写 `test_transport_error_when_server_stopped` 时观察到：内嵌 Server 停止后，
对该端口发请求**有时**得到连接被拒（`TransportError`），**有时**得到一个
`HTTP 502`、响应头为 `connection: close, content-length: 0`、**没有响应体**的应答
（PowerContext 归类为 `ServerResponseError`，其 `code` / `server_message` / `request_id` 均为 `None`）。

已排除的可能：进程内没有任何代理环境变量；PowerContext 构造的是
`httpx.AsyncClient(timeout=timeout)`，未覆盖代理设置。该行为与本机已知的
网络拦截组件（Clash TUN）在无监听端口上代答网关错误的表现一致。

因此该测试断言的是**诚实的不变量**——「必须是可归因于 PowerContext 的 5xx 真实错误，
且不得返回空列表冒充成功」——而不是某一个具体分类；两种分类都算通过。
`describe_powercontext_error()` 也对空响应体的网关状态码补了相应提示。

### 8.2 一次未能复现的瞬时 502

UI 验证过程中，某个已运行约 25 分钟的服务实例上，「保存交接」连续两次返回
502 `powercontext_transport`（路径 `/v1/work/handoffs/prepare-current`）。同一实例上
其它所有调用（记忆读写、检索、恢复、交接读取）都正常返回 200；
用一个**独立进程**新建客户端对同一实例调用 `handoff_current_work` 也成功。

已排除「keep-alive 连接陈旧」这一假设：单独构造空闲 3s / 6s / 12s 后重试的探针，三次全部成功。

重启服务后，同样的交接流程（含带真实 MemoryCitation 的 verified 声明）在 UI 中一次成功，
提交为 `handoff/handoff@r3`；此后多次重复均未再出现。**该现象未能复现，原因未确定，
在此如实记录而不作猜测性归因。** §7.5 的修复保证了下次再出现时，
横幅会直接给出底层 httpx 异常类型与消息，可据此定位。

### 8.3 PowerContext 官方把 Windows 标注为 experimental

本机实测：smoke test 通过、15 个测试全部通过、浏览器端完整流程通过。
未遇到 Windows 特有问题。仍按官方口径把它列为已知边界。

---

## 9. 性能实测

| 指标 | 实测值 | 测量方式 |
|---|---|---|
| 冷启动到 HTTP 可访问 | **10.54 s** | `subprocess` 启动 `python -m app.main`，轮询 `/api/system/status` 至首个 200 |
| 其中：模块导入 | **7.28 s** | `python -X importtime -c "import app.main"` |
| 其中：应用 lifespan（拉起内嵌 Server + 客户端 + 索引） | **0.72 s** | 进程内 `lifespan_context` 计时 |
| 启动后首个 `/api/system/status` | **0.05 s** | 进程内 httpx ASGITransport 计时 |
| 注册 API 路由数 | **16** | `len(app.openapi()["paths"])` |
| 静态资源 | `/` 14482 B、`/app.css` 25141 B、`/app.js` 47479 B，均 200 | curl |

冷启动的大头是 PowerContext 服务端模块的导入，实测最慢的几条累计耗时：
`powercontext.server.factory` 3.29 s、`powercontext.server.access` 2.51 s、
`fastmcp.server` 2.31 s、`powercontext.builtin.persistence.sqlite` 1.07 s。
注意 `fastmcp` 即使研续把 `McpConfig(enabled=False)` 也仍会被上游 eager import。
这属于上游导入图，研续没有绕过它。

---

## 10. 验收对照

| # | 验收项 | 结论 | 证据 |
|---|---|---|---|
| A1 | 项目隔离 | **通过** | §6.8：第二个项目检索「合并」命中 0 条；`test_project_isolation`；seed 第 7 步 |
| A2 | 记忆持久化 | **通过** | §3 跨进程 smoke test；§6.10 杀进程重启后数据完整；`test_data_survives_full_restart` |
| A3 | 修订与历史 | **通过** | §6.3：entry_id 不变、v1→v2、旧快照读回、变更日志 `r4 add` / `r9 revise` 带原因 |
| A4 | 陈旧引用冲突 | **通过** | §6.9：真实 409 `revision_conflict` + `request_id 25751f9e0950469e`；seed 第 4 步 |
| A5 | 交接与恢复 | **通过** | §6.5–6.6：`handoff@r3`，`evidence_checks` 3/3 available |
| A6 | 恢复简报 | **通过** | §6.6：7 张分类卡片 + 上次交接 + PreparedContext `ready · 1764 B` |
| A7 | 带来源报告 | **通过** | §6.7：每条要点带 `mem_xxxxxxxx@vN`，附录展开 entry_id / entry_version_id / 变更序列 |
| A8 | 真实错误提示 | **通过** | §6.9：422（带 request_id 与 details）、409、400；`test_real_error_surfacing` 覆盖 503 `handoff_generation_unavailable` 与 Server 停止后的 5xx |
| A9 | 无模型密钥 | **通过** | 全程未配置任何密钥；§5 输出 `自动记忆提取 False`、`可用检索方式 auto, fts`；`test_no_model_keys_required` |
| A10 | 不用 localStorage 承载数据 | **通过** | §6.10：清空前仅 1 个 UI 偏好键，清空重载后业务数据完整读回 |

> **⚠ M2 更正：上表的「结论」列有 5 项在 M1 结束时并不成立，协调人独立验收把它们逐条打回。**
>
> 原表按要求保留。真实情况是：
>
> | # | M1 写的 | M2 复验发现的真实状态 | 现在的结论 |
> |---|---|---|---|
> | A3 | 通过 | `memory.entry_history` 用裸 `except Exception: continue` 吞掉了逐版本读取失败，历史会**静默变短**——看起来正常，其实丢了快照 | 已修（§13.1），`test_entry_history_never_silently_truncates` 覆盖 |
> | A5 | 通过 | ① 带陈旧 `revision` 的接手请求被静默接受：用户核对的是 r1，后端确认的是 r2；② 未解决问题全已解决、下一步全已完成/放弃时，草稿判定仍写 `blocked` | 已修（§13.2 / §13.3），4 个回归测试覆盖 |
> | A6 | 通过 | 恢复简报把 `resolved` 的问题仍列进「未解决问题」、把 `done` / `dropped` 的下一步仍列进「下一步」，新会话读到的是假待办 | 已修（§13.3） |
> | A7 | 通过 | ① 起止倒置的区间返回 200 空报告；② `20261102` 这类 ISO 基本格式能通过校验却打乱字典序区间比较；③「本期已解决」冒充区间过滤（见 §7.3 更正）；④ `dropped` 的下一步被渲染成待完成项；⑤ 附录与 `citation_count` 把没进正文的条目也算进去；⑥ 资料 URL 只做 HTML 转义，`javascript:` 仍是可点击链接 | 已修（§13.4 / §13.5），2 个回归测试覆盖 |
> | A9 | 通过 | 结论本身成立，但 `GET /api/projects/{id}/handoff?selection=exact&revision=1` 返回 `handoff_revision_required`——官方的精确版本读取根本没实现 | 已实现（§13.6），`test_exact_handoff_revision_read` 覆盖 |
>
> 另外，A1/A2/A4/A8/A10 的证据大量引用 §6，而 §6 的界面部分已降级（见 §6 更正）：
> 这几项的**后端**结论仍由 §3、§4、§5 的独立证据支撑，因此结论不变；
> 但凡涉及「界面上显示正确」的部分，一律需要协调人在可见浏览器里复验。
>
> M2 修复后的完整复跑结果见 §14。

对照 [evidence/acceptance-plan.json](evidence/acceptance-plan.json) 的 8 个 `core_scenarios`：
`persist-resume`、`project-isolation`、`revision-history`、`source-traceability`、
`handoff-roundtrip`、`service-failure`、`report-export`、`clean-reproduction` **均已按上述证据执行**。
其中 `source-traceability` 的一点补充说明：用户自己填写的资料 URL 只作为「资料出处」原文呈现，
研续不抓取、不校验其内容；真正可独立回溯的是 PowerContext 的 `MemoryCitation`
与交接的 `evidence_checks`。该文件的 `status` 字段仍写着 `planned, not executed`，
按角色分工由协调人更新。

`delivery_gates` 中「通过 Qoder Sites 发布展示网站」按本阶段要求**未执行**（暂不发布网站）。

---

## 11. 尚未完成 / 已知边界

**未做（按本阶段要求）**

- M2 UI 精修的剩余项、M3 Qoder Sites 发布、M4 证据包整理与提交材料。
- 本文件§6 的浏览器验证以 DOM 结构快照 + 计算样式 + 真实产物拦截方式完成；
  验证期间 Qoder 内置浏览器面板不可见（`viewport=0x0, visibilityState=hidden`），
  截图与真实鼠标点击不可用，因此**没有由我生成的界面截图**。
  界面截图需由协调人在可见的浏览器中补拍。CSS 已确认生效：
  样式表 221 条规则加载，`--paper: #f6f3ec` 等设计令牌解析正常，
  `body` 背景实测 `rgb(246, 243, 236)`，顶栏渐变实测生效。

> **⚠ M2 更正：这一段虽然交代了面板不可见，但「CSS 已确认生效」的推论是错的。**
>
> 我当时量的都是「某条规则的计算值对不对」，而 P0 恰恰是**两条规则都各自生效、
> 层叠结果错了**：`.drawer{display:flex}` 与 `.modal-backdrop{display:grid}` 都正常生效，
> 浏览器默认的 `[hidden]{display:none}` 属于 UA 样式，被作者样式无条件盖掉（与选择器优先级无关）。
> 于是「规则都解析正常」和「覆盖层常驻遮挡」同时为真。
> 教训：显隐这类**跨规则层叠**的性质不能靠逐条读计算样式来验收，
> 必须直接量「带 hidden 时的计算 display」，或者干脆用眼睛看。
> M2 已按前者补了自动化断言（§12.2、§12.3）。
>
> 「M2 UI 精修的剩余项」这一条也低估了工作量：实际精修见 §15。

**能力边界（源于未配置模型，属预期）**

- 检索只有 FTS 关键词匹配，没有语义召回（无 embedding 模型）。
- `/v1/handoff/prepare`、`/v1/handoff/activate` 需要生成模型，实测返回 503
  `handoff_generation_unavailable`。研续不使用这两个端点，改用
  `handoff_current_work` → `commit_handoff` 的本人撰写路径。
- 无自动记忆提取（`memory_extraction=False`）：所有记忆都由用户显式录入。

**工程边界**

- 单用户本地工具，无鉴权，只应监听回环地址。
- 本地项目索引（`registry.db`）只存 `project_id / name / summary / scope_id / 时间戳 / archived`，
  存在的唯一原因是 PowerContext 没有 list-scopes 端点；所有实质内容只在 PowerContext 里。
- `data/`、`.tmp/`、`.pytest-tmp/` 已在 `qoder/.gitignore` 中排除，不入库。

---
---

# M2 记录（2026-11-02）

以上是 M1 原文。以下全部是 M2 本轮**实际执行**的修复与验证。
协调人先用 `oceanbase` 环境独立复跑了当时已有的 15 个测试（全部通过），
再用 [evidence/review_m1.py](evidence/review_m1.py) 做探针验收，
原始结果保存在 [evidence/independent-review-m1.json](evidence/independent-review-m1.json)（**未覆盖、未修改**）。
M2 的全部工作围绕这两份材料展开。

---

## 12. P0：一进页面就同时弹出历史抽屉和新建弹窗

### 12.1 现象与根因

协调人在**真实可见的 Edge** 里打开页面：历史抽屉与「新建项目」弹窗同时压在界面上，
主界面被遮住，点关闭也隐藏不了（[evidence/ui/m1-ledger.png](evidence/ui/m1-ledger.png)）。

根因是 CSS 层叠，不是 JS 逻辑：

- `index.html` 里 `#history-drawer`、`#project-modal` 等**确实**带了 `hidden` 属性；
- `app.css` 里 `.drawer { display: flex; }`、`.modal-backdrop { display: grid; }` 是作者样式；
- 浏览器的 `[hidden] { display: none; }` 属于 **UA 样式**。作者样式的 `display` 声明
  **无条件覆盖** UA 样式——这与选择器优先级（specificity）无关，`.drawer` 的 0,1,0
  并不比 `[hidden]` 的 0,1,0 高，赢的是「作者 > UA」这一层来源顺序。

于是 `hidden` 属性形同虚设：只要 CSS 里写了 `display`，元素就一定显示。
点关闭时 JS 把 `hidden` 设回 `true`，计算样式依旧是 `flex` / `grid`，所以「关不掉」。

这也解释了 M1 为什么没发现：我当时用脚本派发 DOM 事件，元素在不在视觉上遮挡根本不影响
`element.click()` 成功；而我逐条读计算样式时，读到的 `.drawer{display:flex}` 本身是「正确生效」的，
错的是它与 `[hidden]` 的**组合**结果。

### 12.2 修复

`app/static/app.css` 在 `* { box-sizing: border-box; }` 之后加了一条全局规则，
把 `hidden` 抬回最高层，作为覆盖层唯一的显隐开关：

```css
[hidden] { display: none !important; }
```

`.drawer{display:flex}` 与 `.modal-backdrop{display:grid}` **保留不动**——
它们负责的是「显示时长什么样」，不是「要不要显示」。

`app/static/app.js` 另外补了三道防线：

1. `hideAllOverlays()` 作为 `boot()` 的**第一条语句**执行，强制所有覆盖层 `hidden=true` 并清空栈。
   即使 HTML 里漏写 `hidden`，加载后也不会常驻。
2. 覆盖层改为**栈式管理**（`OVERLAYS` 表 + `overlayStack`）：`openOverlay` 记录
   `returnFocus = document.activeElement`，`closeOverlay` 还原焦点；
   Esc 只关最上层；Tab 在当前覆盖层内做焦点陷阱。
3. 可见性判定用 `getClientRects().length > 0` 而不是 `offsetParent`——
   覆盖层本身是 `position: fixed`，`offsetParent` 在固定定位子树里会给出误导结果。

覆盖层打开时给 `body` 加 `has-overlay { overflow: hidden; }`，禁止背景滚动。

### 12.3 真实浏览器引擎里的实测

用 browser-use MCP 连到真实 Chromium 页面（`http://127.0.0.1:8123/`，服务为本轮独立数据目录
`qoder/.tmp/m2-verify` 上启动的实例），量到的原始数据存在
[evidence/ui/m2-overlay-state.json](evidence/ui/m2-overlay-state.json)。

**页面刚加载完、未做任何交互时**：

| 节点 | class | `hidden` | 计算 `display` | 盒尺寸 |
|---|---|---|---|---|
| `#history-backdrop` | `drawer-backdrop` | true | `none` | 0×0 |
| `#history-drawer` | `drawer` | true | `none` | 0×0 |
| `#project-modal` | `modal-backdrop` | true | `none` | 0×0 |
| `#status-modal` | `modal-backdrop` | true | `none` | 0×0 |

`body.className` 为空（无 `has-overlay`）；可访问性树快照里**没有任何 dialog / drawer 节点**，
只有顶栏、侧栏、「继续工作」英雄区、合成演示横幅、标签页、录入表单、检索框与台账分组。
这一屏正是 M1 出问题的位置。

**同一节点上切换 `hidden` 属性**，证明层叠冲突确实被消除、而作者样式没被删掉：

| 节点 | 带 `hidden` | 去掉 `hidden` | 去掉后的盒尺寸 | 恢复 `hidden` 后 |
|---|---|---|---|---|
| `#history-backdrop` | `none` | `block` | 515×554 | `none` |
| `#history-drawer` | `none` | `flex` | 530×554 | `none` |
| `#project-modal` | `none` | `grid` | 515×554 | `none` |
| `#status-modal` | `none` | `grid` | 515×554 | `none` |

即：M1 那个「作者 `display` 盖掉 `[hidden]`」的机制已经反转，
`hidden` 现在是唯一开关，去掉它才恢复 `flex` / `grid` 并拿到真实非零盒尺寸。

### 12.4 界面可用性验收：**移交协调人，本轮未通过验证**

必须如实写清：**上面的数据不是可视化验收，本轮我没有能力做可视化验收。**

- 该浏览器面板没有可见表面：`outerWidth = 0`、`outerHeight = 0`、`visibilityState = "hidden"`、
  `document.hasFocus() = false`（`innerWidth/Height` 是 530×554，有视口但没有窗口）。
- 截图被工具自己拒绝，原文：
  `NATIVE_BROWSER_VIEWPORT_UNAVAILABLE: In-app Browser did not provide a visible surface with a positive viewport within 1000ms (operation=screenshot, viewport=530x554, visible=false, attached=true, cdpAttached=true, visibilityState=hidden). Open the in-app Browser before retrying this visual action.`
  **本轮没有产出任何一张页面像素证据。**
- 连脚本点击都不成立：MCP 的 `click` 对「第一条记忆的历史按钮」和「首屏顶栏技术详情按钮」
  都返回 `Successfully clicked on the element`，但点击后复测四个覆盖层仍然
  `hidden=true / display:none`，`body` 没有 `has-overlay`，`document.activeElement` 始终是 `BODY`。
  在这个不可见视口里 CDP 鼠标输入是空操作，**工具的成功回执不代表事件落到了页面上**。

按协调人指示「无法可视操作就交协调人」，本轮做的移交动作：

```powershell
Start-Process "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" -ArgumentList "--new-window","--window-size=1440,980","http://127.0.0.1:8123/"
```

已启动一个**真实可见**的 Edge 窗口，`netstat` 确认 8123 上出现多条 `ESTABLISHED`；
服务与数据目录留在原处未停，供协调人直接做鼠标验收。协调人的 8124 验收进程全程未被触碰
（`netstat` 显示其仍在 `LISTENING`，PID 25296）。

留给协调人的验收清单（逐项都还没人验过）：

1. 首屏是否只有主界面，没有任何抽屉 / 弹窗叠加；
2. 顶栏「技术详情」是否只弹一个窗，Esc 是否只关最上层；
3. 侧栏「新建项目」弹窗内 Tab 焦点是否被限制在弹窗内，关闭后焦点是否回到该按钮；
4. 记忆的「历史」抽屉是否只滑出一个，点遮罩或 Esc 是否关闭并还原焦点；
5. 先开抽屉再开新建弹窗，两层是否按栈叠加、Esc 是否逐层关闭；
6. 覆盖层打开时背景是否禁止滚动；
7. 窗口拖窄到约 520px 时首屏、按钮、抽屉是否仍可用；
8. 「保存记录」「创建项目」是否有可见 loading，失败后是否能重试。

**结论：P0 的根因已定位、代码已修、层叠机制已在真实渲染引擎里量到反转；
但「人能用鼠标正常操作」这一条仍未验证，不能宣称通过。**

---

## 13. M2 后端修复

以下每条都对应协调人探针或代码审查里的一个具体发现，
并各有一个 `tests/test_m2_regressions.py` 里的测试，测试 docstring 写明「修复前的错误行为」。

### 13.1 `entry_history` 静默丢快照

修复前：逐个版本读回快照时用裸 `except Exception: continue`，
任何失败（超时、网关错误、Server 退出）都让历史**悄悄变短**，界面看起来正常。

修复后 `app/memory.py`：只允许「这个版本确实读不回来」降级——
`ServerResponseError` 且 `status_code == 404` 时记一条 `UnavailableSnapshot`
（带 `entry_version_id / revision / op / error` 原文），其余异常**原样抛出**变成 5xx。
`EntryHistoryView` 新增 `unavailable` 列表，前端把不可读的版本渲染成
`.snapshot.is-unavailable` 卡片加一句 `.history-note` 说明，而不是当作不存在。

测试 `test_entry_history_never_silently_truncates`：健康状态下 `unavailable == []`、
快照按版本正序、`change_ops == ["add", "revise"]`；
随后 `app.state.host.stop()` 停掉内嵌 Server，断言响应 `>= 500`、
错误码以 `powercontext_` 开头、且响应体里**不含** `changes` 字段（不许拿半截历史冒充成功）。

### 13.2 接手请求必须绑定用户核对过的那个 Revision

修复前：`POST /handoff/acknowledge` 忽略请求里的版本，直接对**最新版**落 receipt。
用户核对的是 r1，回执写着 r2 —— 探针已实测服务端会静默接受陈旧 revision。

在两条路线里选了**409 要求刷新**（而不是精确接手旧版）：
交接的语义是「接手当前工作」，对一个已被推进的旧版本落 accepted receipt，
等于宣称核对过一份已经过时的状态，正是要避免的那种不诚实。

`app/routes/handoff.py` 现在的顺序：

1. `payload.revision is None` → 400 `acknowledge_revision_required`（不猜、不悄悄换最新版）；
2. 用 `selection="exact"` 精确读回用户看过的版本，读不到 → 404 `handoff_not_found`
   （这一步同时挡住了跨项目与不存在的版本）；
3. 与最新版比对，不一致 → **409 `handoff_revision_stale`**，
   `details` 里同时给出 `viewed` 与 `latest` 两个完整 `ArtifactRef`；
4. 一致才调 `memory.acknowledge_handoff(...)`，且向 SDK 传
   `selection="exact"` + `revision=`，回执后**按同一 exact revision 读回**，
   所以返回体里的 `selected_revision` 就是用户核对过的那个。

**checkbox 文案与真实 `ReceiverChecks` 的对应关系已核对**（运行时自省 `powercontext.http`）：
`ReceiverChecks` 的字段恰好是 `['live_state', 'capability', 'authorization']`，
`ReceiverReadinessCheckStatus` 是 `['CONFIRMED', 'INSUFFICIENT', 'NOT_CHECKED']`。
三个复选框文案与之一一对应，后端错误消息里引用的也是同样三句原文：

| UI 复选框 | 请求字段 | SDK `ReceiverChecks` |
|---|---|---|
| 我已逐条核对交接中的状态与当前实际情况一致 | `live_state_checked` | `live_state` |
| 我具备继续这项工作所需的环境与工具 | `capability_checked` | `capability` |
| 我有权接手并继续这项工作 | `authorization_checked` | `authorization` |

未勾选的传 `not_checked`；`status=accepted` 且任一项非 `confirmed` →
400 `handoff_ack_requires_check`，消息里点名还差哪几项。
`needs_clarification` / `declined` 不要求三项全 confirmed（这正是它们的用途），实测返回 200。

前端配套：`#ack-version` 常显「你将接手 `Revision N`（`handoff/handoff`）· 请先核对上方「当前交接状态」再确认」，
没读到版本时「确认接手」按钮直接 `disabled`；
提交后回执区把读回的 Revision 与用户核对过的做**显式比对**并写出「一致 / 不一致」，
附 `receipt_source_id`；撞上 409 时清掉三个勾选、给出警示块、并自动刷新交接状态。

测试 `test_acknowledge_binds_the_revision_actually_reviewed`（陈旧 r1 → 409 且 details 含 viewed/latest；
`declined` 带陈旧版本同样 409；新鲜的 r2 → 200 且目标一致；三种非法 ref → 400 `invalid_handoff_revision`）
与 `test_acknowledge_receiver_checks_are_all_three`（5 种部分勾选组合 → 400；两种非 accepted 状态 → 200）。

### 13.3 有效状态语义：已解决 / 已关闭不再冒充待办

修复前探针实测：未解决问题只剩 `resolved`、下一步全是 `done`/`dropped` 时，
交接草稿判定仍写 `blocked`；`/restore` 还把这些条目原样塞回「未解决问题」和「下一步」，
新会话读到的是一份假待办。

`app/routes/handoff.py`：

- `_split_questions` → `unresolved` / `resolved`；没有状态标注的问题**按未解决处理**
  （不知道它已解决，就不能当已解决展示）。
- `_split_steps` → `actionable` / `closed`（`done` 或 `dropped`）。已放弃的下一步绝不是待完成项。
- `_draft_disposition`：`blocked` 只属于「还有悬着的问题**且**没有可行动的下一步」；
  问题全解决、步骤全关闭时是 `complete`；其余为 `continuable`。
- `RestoreBrief` 新增 `resolved_questions` 与 `closed_next_steps` 两个字段，
  历史可查，但与 `open_questions` / `next_steps` 分开呈现，不再混进「待办」语义里。
- 交接草稿的 `omissions` 只由**未解决**问题生成，`next_action` 只从**仍可行动**的步骤里取。

测试 `test_effective_state_semantics`：`continuable → blocked → complete` 三段推进各自断言，
并检查 restore 的分类归属。

### 13.4 报告的时间口径、区间过滤与引用计数

修复前探针实测四个问题：起止倒置的区间返回 200 空报告；「本期已解决」冒充按区间过滤；
`dropped` 的下一步被渲染成待完成项；附录与 `citation_count` 把根本没进正文的条目也算进去。

`app/schemas.py`：`ReportRequest` 的 `date_from` / `date_to` 与 `EntryInput.date`
都过 `parse_iso_date`，并用 `model_validator` 拒掉 `date_from > date_to`（422，消息含「不能晚于」）。

`app/reports.py`：

- 报告头新增一行**时间口径**，把规则写进正文而不是让读者猜：
  区间只过滤「带日期的工作记录」与「已完成待办」（按条目自己的记录日期）；
  目标 / 决策 / 未解决问题 / 下一步 / 资料出处是**当前有效状态**，不按区间过滤；
  研续不记录「解决 / 完成的发生时间」——PowerContext 的 `EntryChange` 不含时间戳，
  所以绝不把记录日期冒称成解决时间。
- 「本期已解决」改名为 `### 已解决（当前有效状态，不按区间过滤）`，其后附一句同样口径的说明。
- `dropped` 的下一步单列在「已放弃（不再计划）：」下，渲染为 `- ~~…~~`，不再出现在待完成清单里。
- 新增 `_Citations` 收集器：**只有真正在正文里调用过 `cited.ref(entry)` 的条目**才进名单，
  附录表格、`citation_count`、`source_count` 全部只认这份名单。
  区间外的记录既不进正文也不进计数。

测试 `test_report_time_semantics_and_citation_honesty`：倒置区间 → 422；
三种非法日期 → 422；区间内记录的 `ref_label` 在正文、区间外的不在正文也不在附录；
断言 `"本期已解决" not in markdown`；已解决问题渲染为 `- [x]`、已放弃下一步渲染为 `- ~~…~~`；
附录行数 `== citation_count == 7`（目标 + 区间内记录 + 决策 + 已解决问题 + 已放弃下一步 + 待办 + 资料出处）。

### 13.5 资料 URL 只有 http/https 可点击

修复前：任何 `url` 都被渲染成 `<a href>`，只做 HTML 转义。
转义防不住 `javascript:` / `data:` / `vbscript:`——那是**协议**问题不是转义问题，等于一处存储型 XSS。

`app/memory.py` 的 `safe_href()` 成为前后端**共用**的唯一口径：
只有 `http://` / `https://` 前缀（大小写不敏感）才原样返回，其余一律返回空串。
`EntryView` 因此同时带 `url`（用户填的原文）与 `url_href`（可点击时才非空）。
前端 `sourceLinkHtml()`：`url_href` 非空才渲染 `<a target="_blank" rel="noopener noreferrer">`，
否则渲染成纯文本 `<span class="entry-url-plain">`（前面加「标识 ·」）。
报告里同理：可点击的写 `<https://…>`，不可点击的写 `（标识：10.1000/zenodo.1234567）`。
这样 DOI 这类纯标识符能原样呈现，而不会变成一个能点的链接。

测试 `test_source_url_only_http_https_is_clickable`：9 种 scheme
（含 `javascript:`、`data:`、`file:`、`vbscript:`、`JavaScript:` 大小写变体、裸 DOI）
断言 `url_href == ""`；并断言报告正文出现 `<https://…>` 与 `（标识：10.1000/zenodo.1234567）`，
且**从不**出现 `<javascript:`。

### 13.6 交接的精确版本读取

修复前探针实测：`GET /api/projects/{id}/handoff?selection=exact&revision=1`
返回 `handoff_revision_required` —— 路由签名里根本没有 `revision` 参数，官方的精确版本读取没实现。

`app/routes/handoff.py` 的 `current_handoff` 现在接受 `selection` + `revision`
（`Query(ge=1)`），`selection=exact` 时构造真实 `ArtifactRefView(family="handoff", artifact_id="handoff", revision=N)`
传给 `memory.restore_handoff`。

按官方语义实测的边界（探针 + 回归测试双向确认）：

| 请求 | 实测结果 |
|---|---|
| `selection=exact&revision=1`（存在） | 200，`status=resolved`，读回 r1 的内容 |
| `selection=exact&revision=2`（存在） | 200，读回 r2 |
| `selection=latest` | 200，最新版 |
| `selection=exact&revision=999` | **404** `powercontext_server_response`，服务端码 `artifact_not_found`，带真实 `request_id` 与中文提示 |
| 项目 B 里 exact 读项目 A 的版本 | **404**（PowerContext 按 Scope 隔离交接工件，项目隔离成立） |
| `selection=exact` 不带 `revision` | 400 `handoff_revision_required` |
| `selection=exact&revision=0` | 422（`ge=1` 校验） |
| `selection=prepared` | 400 `invalid_selection`（研续只支持 latest / exact） |

测试 `test_exact_handoff_revision_read` 覆盖以上全部八行。

### 13.7 超长研究目标不再留下半成品项目

修复前：创建项目时先 `registry.insert` 再写目标记忆。
目标 4000 个汉字经 YX1 编码后约 12000 UTF-8 字节，超过 PowerContext 的 8192 上限，
写入被 422 打回——**但项目记录已经落库**，留下一个没有目标的半成品项目。
原先那段 `idempotency_key` 注释也站不住：它绑定的是本次请求生成的 `project_id`，
用户重试是一次全新的 POST（新 `project_id`、新 Scope），根本不提供跨请求幂等。

`app/routes/projects.py` 现在把顺序反过来：

1. **先**用研续自己的 YX1 编码算真实 UTF-8 字节数（`codec.encode` + `codec.byte_length`），
   超限就在创建 Scope **之前**拒掉：400 `goal_too_long`，
   `details = {byte_length, limit: 8192}`，并附提示「中文每字约 3 字节；4000 字的目标必然超限」；
2. 通过后 `create_scope`；
3. 再写目标记忆。这一步若失败，注册表里**不会有**这个项目，
   用户看到的是干净的失败，重试即全新创建。代价是 PowerContext 里可能留下一个
   没有注册表记录的孤儿 Scope——它没有 list 入口、不出现在任何项目列表里，
   也不会被误当成可用项目。这个取舍写在代码注释里；
4. 最后 `registry.insert`。

前端在项目创建表单里加了实时字节计数器（`#project-goal-bytes`），超限前就变红。

测试 `test_oversized_goal_never_leaves_a_half_made_project`：4000 字目标 → 400 `goal_too_long`
且 `details.limit == 8192`、带 hint；随后 `GET /api/projects` 返回 **`[]`**（没有半成品）；
同参数重试仍然干净失败；改成 2600 字（编码后仍在限内）→ 201 创建成功。

### 13.8 本轮新发现：Python 3.11 的 `fromisoformat` 会放过 ISO 基本格式

写回归测试时原本打算断言 `"20261102"` 被拒，实测却返回 **201**。
探针确认：Python 3.11 的 `date.fromisoformat("20261102")` **成功**（3.11 起支持 ISO 8601 基本格式）。

这在研续里是个真 bug 而不只是宽松：区间过滤靠**字符串字典序**比较，
而 `"20261102" > "2026-11-07"` 为真——一条 11 月 2 日的记录会被判成「晚于 11 月 7 日」，
悄悄给出错误的区间结果，且没有任何报错。

修复：`parse_iso_date` 不只校验，还**归一化**——返回 `parsed.isoformat()`（`YYYY-MM-DD`）。
`EntryInput.date`、`ReportRequest.date_from`、`ReportRequest.date_to` 三处共用。

测试 `test_invalid_entry_date_is_rejected`：`20261102` → 201 且存回为 `2026-11-02`，
并被 `date_from=2026-11-01&date_to=2026-11-07` 的报告正确命中；
`2026-1-5` → 201 且归一为 `2026-01-05`；`2026-13-45`、`昨天`、`2026-02-30` → 422 且消息含「ISO 日期」；
报告端 `date_to=20261107` 同样归一后返回 200。

---

## 14. M2 测试套件

```console
$ python -m pytest -v
============================= test session starts =============================
platform win32 -- Python 3.11.17, pytest-9.2.0, pluggy-1.7.0
rootdir: E:\Ocean Base\qoder-competition\qoder
configfile: pytest.ini
testpaths: tests
plugins: anyio-4.16.0, platformdirs-4.14.3
collected 43 items

tests\test_api_e2e.py .......                                            [ 16%]
tests\test_codec.py ........                                             [ 34%]
tests\test_m2_regressions.py .........                                   [ 55%]
tests\test_site_contract.py .......                                      [ 72%]
tests\test_ui_contract.py ............                                   [100%]

============================= 43 passed in 26.48s =============================
```

15 → **43** 个测试，全部通过，仍然**没有任何 mock**：每个端到端测试都通过
`app.router.lifespan_context` 拉起真实的内嵌 PowerContext Server（真实 SQLite，`tmp_path` 数据目录），
再用 `httpx.ASGITransport` 打真实 HTTP 路由。

新增三个文件：

| 文件 | 数量 | 性质 |
|---|---|---|
| `tests/test_m2_regressions.py` | 9 | 行为回归：每个测试的 docstring 写明「修复前的错误行为」，全部打真实 Server |
| `tests/test_ui_contract.py` | 12 | 结构契约：解析 `index.html` / `app.css` / `app.js` 源文件，锁定 P0 与精修要求 |
| `tests/test_site_contract.py` | 7 | 展示页诚实性契约：锁定 `site/` 的六条写作红线（见 §18） |

`test_m2_regressions.py` 的 9 个测试对应 §13 的各条：
`test_effective_state_semantics`、`test_acknowledge_binds_the_revision_actually_reviewed`、
`test_acknowledge_receiver_checks_are_all_three`、`test_exact_handoff_revision_read`、
`test_report_time_semantics_and_citation_honesty`、`test_source_url_only_http_https_is_clickable`、
`test_oversized_goal_never_leaves_a_half_made_project`、`test_invalid_entry_date_is_rejected`、
`test_entry_history_never_silently_truncates`。

`test_api_e2e.py::test_full_continuity_loop` 也已按新契约改写：
新增「不带 revision 的接手 → 400 `acknowledge_revision_required`」探针，
`declined` 探针补上 revision，成功接手时三项核对全勾并断言
`receipt["selected_revision"]["revision"]` 等于用户核对过的那个。

`test_ui_contract.py` 的 12 个测试是**为 P0 这类「肉眼才发现」的缺陷补的自动化网**，
每条都对应一个具体回退：

| 测试 | 锁住什么 |
|---|---|
| `test_css_hidden_beats_author_display` | CSS 里存在 `[hidden] { display: none !important; }`，**同时** `.drawer{…display:flex` 与 `.modal-backdrop{…display:grid` 仍在（证明是靠层叠修复，不是靠删样式蒙混） |
| `test_every_overlay_starts_hidden` | HTML 里每个覆盖层节点初始都带 `hidden` |
| `test_overlays_are_accessible_dialogs` | 覆盖层是 `role=dialog` + `aria-modal` + `aria-labelledby` |
| `test_js_forces_overlays_hidden_on_boot` | `boot()` 函数体的第一行必须是 `hideAllOverlays();` |
| `test_js_manages_focus_and_escape` | JS 里**从不**出现 `$("#<overlay-id>").hidden` 这类逐个硬写，显隐只走覆盖层管理器 |
| `test_links_only_from_backend_validated_href` | 前端只用后端给的 `url_href` 造 `<a>`，不自己拼 href |
| `test_first_screen_is_research_not_infrastructure` | 顶栏不含 `scp_` / `Scope` / `sqlite` / `embedding` / SDK 函数名；并用 `re.sub` 证明 SDK 函数名**只**出现在 `<details class="tech-details">` 内部 |
| `test_buttons_use_plain_language` | 按钮文案精确等于：保存记录 / 创建项目 / 新建项目 / 保存交接 / 生成 Markdown / 确认接手 |
| `test_acknowledge_exposes_all_three_receiver_checks` | 三个复选框与 `ReceiverChecks` 三项一一对应 |
| `test_visible_loading_error_and_empty_states_exist` | loading / 错误横幅 / 空状态三类节点都在 |
| `test_narrow_screen_is_supported` | CSS 里有窄屏媒体查询 |
| `test_demo_data_is_clearly_synthetic` | 示例横幅与 seed 数据都带合成标注 |

`pytest.ini` 仍设 `--basetemp=.pytest-tmp`（本机 `%TEMP%\pytest-of-wjp` 不可写，见 §4）。
运行需要 `PYTHONIOENCODING=utf-8`，否则 Windows 控制台的 GBK 会把中文断言输出打成乱码。

---

## 15. M2 UI 精修

保留原有的温暖纸色（`--paper: #f6f3ec`）与蓝绿主色，改的是**信息层级**：

**首屏只讲研究，不讲基础设施。**
顶栏状态从原来的「PowerContext 1.2.0 · sqlite · 已连接 · 检索 auto/fts」
改成一句人话：「记忆已连接 · 数据全在本机」，右侧一个「技术详情」按钮。
Scope ID、项目 ID、创建/更新时间、归档状态、活跃记忆条数、最新交接 Revision、
SDK 版本、存储后端、检索方式、能力边界全部收进可折叠的 `<details class="tech-details">`
（自定义 ▸/▾ 标记，`::-webkit-details-marker{display:none}`），默认折叠。
侧栏项目项的副标题也从 `scp_…` 改成「更新于 2026-11-02」。

**「正常不需要模型密钥」不再是黄色警告。**
能力边界（无 embedding、无语义召回、`handoff_generation` 不可用）是设计前提，不是故障，
因此从警示横幅降级为「技术详情」里的普通说明行。原先那个常驻的 `#notice-banner` 已整体删除
（连同 `showNotice()`、`.banner-info`、`.banner-notice` 等死代码）。

**主视图突出「继续工作」。**
新增 `.continue-hero`（主区 + 侧区）：已解决交接时显示交接目标、`下一步 · …`、
`上次交接 rN · 可继续` 判定胶囊与「查看恢复简报」按钮；
没有交接时显示第一条研究目标与一个「去保存交接」按钮。项目简介移到 `.project-summary`。

**按钮改成看得懂的动词**：保存记录 / 创建项目 / 新建项目 / 保存交接 / 生成 Markdown / 确认接手
（`test_buttons_use_plain_language` 精确锁定这六个文案）。

**可见的 loading、错误恢复与空状态**：
`withBusy(button, task)` 给按钮加 `.is-busy`（文字透明 + `::after` 旋转圈）、`aria-busy` 与 `disabled`；
错误横幅统一带「重试」回调；台账、检索、报告、历史各有空状态文案。

**窄屏可用**：响应式断点扩到 1080px / 820px / 520px——顶栏换行、英雄区堆叠、按钮全宽、
`.drawer{width:100vw}`。（**注意：窄屏的实际观感仍属 §12.4 未验证范围。**）

**引用与修订保留可展开追溯**：台账每条记忆仍带 `mem_xxxxxxxx@vN` 短引用、
状态胶囊、标签与 `add → revise` 变更序列，「历史」抽屉展开可见逐版本快照与
PowerContext 原始 memory text；不可读的版本显示为 `.snapshot.is-unavailable` 而不是消失（§13.1）。

**合成演示数据醒目标注**：`#demo-banner` 用紫色左边框（`border-left: 4px solid #8a6fc0`）与
其它横幅区分，正文明确写「本项目由 seed 脚本生成，标题带【示例】前缀；
其中的延迟、命中率等数字均为虚构，不是实测结果，请勿当作真实性能数据引用」。
`scripts/seed_demo.py` 也把同一句话写进了**数据本身**：
两个示例项目的 `summary` 与 `goal` 都带前缀
「【示例】合成演示数据，全部数字均为虚构、非实测。」，
所以即使有人只从 PowerContext 读回记忆、不看界面，也不会把 12ms 当成实测值。
（本轮播种输出实测可见：`演示目标：把 P99 写延迟从 12ms 降到 8ms 以内…` 前面就带着这句标注。）

---

## 16. M2 复跑：播种脚本与独立数据目录

用**独立数据目录** `qoder/.tmp/m2-verify`（`.gitignore` 已排除）从空目录重新播种，
端口 8123，与协调人的 8124 验收进程完全隔离：

```console
$ python scripts/seed_demo.py --data-dir .tmp/m2-verify --force
研续示例数据播种 · 全部写入真实 PowerContext
  PowerContext 版本        1.2.0
  内嵌 Server              http://127.0.0.1:...
  存储后端                   sqlite
  自动记忆提取                 False
  可用检索方式                 auto, fts
...
[4/7] 用过期引用再修订一次，确认服务端真的会拒绝
  HTTP 状态                409
  服务端错误码                 revision_conflict
  服务端消息                  The Memory Revision is stale.
  研续给出的提示                记忆已被另一次修订推进，请刷新后基于最新版本重试。
[6/7] 保存交接（本人撰写，引用真实记忆 → basis=verified）
  交接工件                   handoff/handoff@r1
  不带核对版本就接手 →            HTTP 400 acknowledge_revision_required
  未核对三项就接手 →             HTTP 400 handoff_ack_requires_check
  核对后接手 →                Revision 1 · receipt Source yanxu-ack-20261102-113252-f6abbb
[7/7] 校验隔离并生成周报
  另一项目检索「合并」             命中 0 条（应为 0）
  恢复简报 · 活跃记忆            7
  证据回溯检查                 3/3 条仍可回溯
周报 Markdown 已写出：...\.tmp\m2-verify\示例周报.md（3067 字符）
```

第 6 步的三个探针是 M2 新加的，对应 §13.2：
不带 revision → 400 `acknowledge_revision_required`；
带 revision 但 `live_state_checked=False` → 400；
三项全勾 + revision → 成功，并且脚本**当场比对回执**：
`receipt["selected_revision"]["revision"] != revision["revision"]` 就 `SystemExit("回执里的 Revision 与本人核对过的 Revision 不一致。")`。
本次实跑通过，回执 Revision 与核对的 Revision 一致（都是 r1）。

`GET /api/system/status` 实测（本轮服务）：
`powercontext_version: "1.2.0"`、`powercontext_running: true`、`storage_backend: "sqlite"`、
`database_path` 指向 `.tmp/m2-verify/powercontext/powercontext.db`、
`capabilities.prompts.*` 全部 `status: "disabled"` / `reason: "provider_not_configured"`——
**未配置任何模型密钥，核心流程照跑**。

静态资源实测（curl 本服务）：`/` 16908 B、`/app.css` 31948 B、`/app.js` 63726 B，均 200。

关于 §8.2 那次未能复现的 502：按协调人指示**没有做任何猜测性配置改动**。
本轮播种 + 服务启动 + 全部 43 个测试期间未再出现，无新异常可记录。

---

## 17. M2 验收对照

| 项 | 结论 | 证据 |
|---|---|---|
| P0 覆盖层常驻 | **代码已修，可用性未验证** | §12.2 修复；§12.3 真实渲染引擎里量到 `[hidden]` 已压过作者 `display`；§12.4 截图与鼠标输入均不可用，移交协调人 |
| 探针 1 有效状态语义 | **通过** | §13.3；`test_effective_state_semantics` |
| 探针 2 接手版本竞争 | **通过** | §13.2；409 路线 + 回执可验证；`test_acknowledge_binds_the_revision_actually_reviewed`、`test_acknowledge_receiver_checks_are_all_three`；§16 seed 三探针 |
| 探针 3 精确版本读取 | **通过** | §13.6 八行边界表；`test_exact_handoff_revision_read` |
| 探针 4 报告口径与引用诚实 | **通过** | §13.4；`test_report_time_semantics_and_citation_honesty` |
| 审查 1 历史静默丢失 | **通过** | §13.1；`test_entry_history_never_silently_truncates` |
| 审查 2 URL scheme | **通过** | §13.5；`test_source_url_only_http_https_is_clickable` |
| 审查 3 半成品项目 | **通过** | §13.7；`test_oversized_goal_never_leaves_a_half_made_project` |
| 新发现 ISO 基本格式 | **通过** | §13.8；`test_invalid_entry_date_is_rejected` |
| UI 精修（结构层面） | **通过** | §15；`test_ui_contract.py` ×12 |
| UI 精修（视觉与鼠标可用性） | **未验证** | §12.4：无可见表面、截图被拒、CDP 点击是空操作 |
| 窄屏可用 | **未验证** | 断点已写进 CSS 并有结构测试，但实际观感需可见浏览器 |
| 展示页源码 | **已准备，未发布** | §18；`site/`，`test_site_contract.py` ×7 |
| Qoder Sites 发布 | **未执行** | 按本轮要求不发布；等协调人复验后再发 |

**一句话总结：本轮 9 项后端问题全部修复并有回归测试锁定（43 passed）；
P0 的根因已定位、层叠机制已在真实渲染引擎里量到反转；
但界面可用性因为拿不到可见浏览器表面，仍未验证，已开好可见 Edge 窗口连同运行中的服务一并移交。**

---

## 18. M2 展示页源码（`qoder/site/`，未发布）

按本轮要求准备了静态参赛展示页源码，**没有发布**、没有创建任何站点描述符、
没有调用 Qoder Sites 相关能力。

| 文件 | 说明 |
|---|---|
| `site/index.html` | 展示页正文（39108 B）：痛点、五步产品流程、真实 PowerContext 集成对照表、五条诚实性不变量、界面（含截图占位）、安装与复现命令、已验证 / 未验证状态板、证据清单、约束红线 |
| `site/styles.css` | 样式（11903 B）。沿用产品本体的设计令牌（纸 / 墨 / 靛），含 720px 窄屏断点 |
| `site/assets/m1-p0-overlays.png` | `evidence/ui/m1-ledger.png` 的副本——M1 那个 P0 的真实现场截图 |
| `site/README.md` | 这个目录是什么、怎么本地预览、发布前要逐条复查的六条写作红线 |

**纯静态**：0 个 `<script>`、无构建步骤、无外部依赖、无追踪、**无任何外部链接**。

本地预览实测（临时起在 8125，用完即停；协调人的 8124 与本轮的 8123 均未受影响）：

```console
$ python -m http.server 8125 --bind 127.0.0.1
/                        -> HTTP 200, 39108 bytes
/styles.css              -> HTTP 200, 11903 bytes
/assets/m1-p0-overlays.png -> HTTP 200, 34214 bytes
```

离线结构校验实测（脚本化解析 `index.html` + `styles.css`）：

```console
parse errors: none
script tags: 0
external links in <a href>: none
missing local targets: none
broken in-page anchors: none
css external refs: none
css braces balanced: True
img files exist: [('assets/m1-p0-overlays.png', True)]
```

**页面里的诚实性处理**（每条都有 `test_site_contract.py` 的断言锁定）：

1. 顶部状态条与页脚都写明「本页是参赛展示页的**源码预览，尚未发布，没有线上地址**」；
   全文不出现任何 `qoder.site` 之类的虚构地址。
2. **不主张量化时间节省**：痛点一节明写「不主张任何量化的时间节省」，
   并交代 PROJECT.md 初稿那个凭印象填的分钟区间已删除、标注为未验证假设。
   页面上**不复述那个具体数字**——即使是在否认它的句子里，读者也会被锚定。
3. **截图只有一张真的**：`assets/m1-p0-overlays.png`（协调人在可见 Edge 里拍的 P0 现场），
   并说明它是缺陷现场而不是产品美图；其余五个位置是**明确标注「截图待补」的斜纹占位框**。
   本轮没有生成、渲染或伪造任何界面截图。
4. 验收状态板把「界面视觉与鼠标可用性」「窄屏实际观感」「Qoder Sites 发布」
   三行如实标为 `未验证` / `未执行`，并写清截图为什么拿不到
   （直接引用工具原文 `NATIVE_BROWSER_VIEWPORT_UNAVAILABLE`）。
5. §12.4 那条教训写在展示页上：**「DOM 事件跑得通 ≠ 人能用」**。
6. 证据清单里的仓库路径一律是 `<code>` **纯文本而不是超链接**——
   仓库相对路径发布到线上会 404，所以宁可不加链接，也不放一个会坏的链接。
7. 合成演示数据的标注方式单独说明：界面横幅 + 写进 PowerContext 的数据本身都带
   「合成演示数据，全部数字均为虚构、非实测」。

`tests/test_site_contract.py`（7 个测试）把上面六条红线各锁一条断言，
外加一条结构校验（标签闭合、id 不重复、img 有 alt、CSS 花括号平衡、有窄屏断点、CSS 不引外部资源）。
写这段测试时它立刻抓到一处自相矛盾：页面为了交代「那个分钟区间已删除」而**复述了该数字**，
与「不得出现未测量的时间区间」的断言冲突。按上面的第 2 条改为只说明「曾给出一个区间、已删除」，
不再复述具体数字。
