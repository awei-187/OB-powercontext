# 研续 Yanxu · 项目基线（PROJECT.md）

> OceanBase 2026 生态赛 · Qoder 赛题。科研与项目工作**连续性**助手。
> 本文件是需求与架构的唯一基线；实现偏差必须回写本文件并在 `DEVELOPMENT.md` 记录原因。

---

## 1. 问题与定位

科研和工程工作最大的隐性成本是**断点**：一次实验做到一半、一个会话结束、一周过去，
下一次坐下来时需要重新拼凑「我到底在做什么、已经确认了什么、什么还没解决、下一步是什么」。
这些状态散落在聊天记录、便签、脑子和过期文档里，重建一次很花时间，且经常重建错。

> **未验证假设（M2 标注）**：本文件 M1 初稿在这里写过「重建一次要 20–60 分钟」。
> 那个区间**没有任何测量或调研支撑**，是写文档时凭印象填的，已删除。
> 研续本轮没有做用户研究，也没有对自己的恢复流程计时，
> 因此**不主张任何量化的时间节省**。展示材料里同样不得出现这类数字。
> 若将来要给出量化收益，须先做可复核的测量（例如对同一项目分别用「翻聊天记录」与
> 「读恢复简报」两种方式重建状态并计时，样本与步骤一并记录）。

**研续**把这套状态显式落到 PowerContext 记忆上，使「结束工作」和「恢复工作」成为两个
可执行动作，并能一键产出**带来源**的组会/周报。

定位：**个人本地工具**。
- 单用户、回环地址、无鉴权（PowerContext Server 默认 loopback + auth disabled）。
- **零额外模型密钥**即可完成核心闭环：不配置 generation / embedding / rerank，
  全部走 PowerContext 的显式记忆（explicit memory）+ SQLite 持久化 + FTS 检索。
- 不追求多人协作、不追求云端同步、不做移动端。

---

## 2. 核心产品流程

```
① 创建研究项目
      └─ 1 个项目 = 1 个 PowerContext Scope（scope_id 为隔离键）
② 录入
      ├─ 工作/实验记录 record
      ├─ 已确认决策   decision（含决策依据 → PowerContext reason）
      ├─ 待办         todo（open / done）
      ├─ 资料出处     source（标题 + URL/DOI + 为什么相关）
      ├─ 未解决问题   open_question
      └─ 下一步       next_step
③ 结束工作 · 保存交接
      └─ handoff_current_work（本人撰写内容）→ commit_handoff
         每条陈述尽量绑定真实 MemoryCitation → basis=verified；
         正文与所引记忆不一致时当场降级为 basis=declared，界面标记同步变
         产出 Scope 单例 handoff 工件的一个不可变 Revision
④ 新会话 · 恢复工作
      ├─ continue_handoff(selection=latest)  → 上次交接 + evidence_checks
      │    （也支持 selection=exact + revision 读回任意历史 Revision）
      ├─ acknowledge_handoff                 → 必须绑定「用户实际核对过的那个 Revision」
      ├─ list_memory_entries                 → 目标/决策/未解决问题/下一步/待办/记录
      ├─ prepare_context                     → PowerContext 自己打包的上下文
      └─ 合成「恢复简报」一屏读完
⑤ 输出带来源的组会/周报 Markdown
      └─ 服务端确定性拼装，每一条都带真实 entry_id@version 引用
```

**贯穿能力**：记忆修订与历史（revise / retire / changes）、来源回溯（citation + source 条目 +
handoff evidence_checks）、真实错误提示（PowerContext 异常原样透传，禁止静默成功）。

---

## 3. 架构

### 3.1 组件

```
浏览器（原生 JS 单页应用，无构建步骤）
   │  JSON over HTTP
   ▼
FastAPI 应用  127.0.0.1:8000          ← qoder/app/main.py
   │
   ├─ 项目注册表 SQLite               ← qoder/data/yanxu/registry.db
   │    仅存「本地项目 ↔ scope_id」薄索引（PowerContext 无 list-scopes 接口）
   │
   └─ PowerContextClient（官方异步 SDK）
        │  HTTP loopback
        ▼
   内嵌 PowerContext Server            ← 后台线程 + uvicorn.Server
        · SQLite: qoder/data/yanxu/powercontext.db
        · InferenceConfig() 全 None（无任何模型密钥）
        · auth disabled / access disabled / mcp off / scheduler off
```

内嵌 Server 采用官方 `examples/jupyter/_tutorial.py` 的既有模式：
`create_server_app(settings=ServerSettings(...))` + 自选空闲端口的 socket +
`uvicorn.Server(...).run(sockets=[listener])` 跑在 daemon 线程里，退出时 `should_exit=True`。
**不复制、不改写 PowerContext 源码**，只按公开 API 调用。

### 3.2 为什么需要本地注册表

PowerContext 的 OpenAPI（`openapi/powercontext.yaml`）提供
`POST /v1/scopes`、`GET /v1/scopes/{id}`、`POST /v1/scopes/default`，
**没有「列出全部 Scope」接口**。因此本地必须保留一份项目名册，
用于 UI 的项目列表、排序、归档标记与 `scope_id` 解析。

**红线**：注册表只存索引字段（项目 id、名称、scope_id、创建/更新时间、归档标志、排序）。
所有**实质内容**（目标、记录、决策、待办、出处、未解决问题、下一步、交接）
**只存在于 PowerContext**。不使用浏览器 localStorage 承载任何业务数据，
不在本地库里复制一份记忆正文。

### 3.3 记忆条目编码

PowerContext 的 `RememberMemoryRequest.text` 是给模型和人读的**纯文本**（NFC 归一化后 ≤ 8192 UTF-8 字节），
不是 JSON 字段袋。为兼顾「可读 / 可 FTS 检索 / 可精确还原」，采用带头部的行式编码 `YX1`：

```
YX1
title=复现 baseline 指标
date=2026-11-02
status=open
tags=实验,基线
url=https://arxiv.org/abs/xxxx
refs=
---
正文可多行。保留原始换行与空行。
```

- 首行固定 `YX1` 作为格式版本标记，便于将来无损迁移。
- 头部只允许固定键白名单：`title` `date` `status` `tags` `url` `refs`；值内禁止换行，
  `---` 单独成行作为正文分隔符。编码/解码为纯函数，有单元测试覆盖往返一致性。
- 条目类型放在 PowerContext 的 `kind` 字段（自由字符串），不塞进 text。
- 用户填写的「依据/原因」映射到 PowerContext 的 `reason`，因此会进入官方变更历史
  （`list_memory_changes` 的 `EntryChange.reason`），这是审计价值最高的一列。

### 3.4 记忆类型（kind）

| kind | 中文 | 说明 |
|---|---|---|
| `goal` | 研究目标 | 项目长期目标；演进靠 revise，不新建 |
| `record` | 工作记录 | 实验/工作日志，带日期 |
| `decision` | 已确认决策 | `reason` = 决策依据 |
| `open_question` | 未解决问题 | `status`: open / resolved |
| `next_step` | 下一步 | `status`: open / done / dropped |
| `todo` | 待办 | `status`: open / done |
| `source` | 资料出处 | `title` = 文献/资料名，`url` = 链接，正文 = 为什么相关 |

「完成待办」= `revise` 把 status 改 done（保留历史），而不是删除。
「删除」= `retire`（PowerContext 无物理删除，retire 后 `state=inactive`，
仍可用 `include_inactive=True` 审计）——这与「记忆修订与历史」的要求天然一致。

### 3.5 交接与恢复

采用 PowerContext 一等公民的 **Work Handoff**，而非自制记忆条目：

- 结束工作：`handoff_current_work(HandoffCurrentWorkRequest{scope_id, source_id, handoff})`
  → 内容全部由本人撰写（`CurrentWorkHandoff`：`objective` / `state[]` / `disposition` /
  `next_action` / `omissions[]`），claims 用 `basis="declared"` + `evidence=[]`；
  Server 自动把本次捕获的 boundary Source 作为强制引用附到每条 statement 上。
  随后 `commit_handoff(CommitHandoffRequest{scope_id, handoff=preview.handoff})`。
- 恢复：`continue_handoff(ContinueHandoffRequest{scope_id, selection="latest"})`
  → `HandoffResolution{trust="untrusted_history", status, content, evidence_checks[]}`；
  `selection="exact"` + `revision` 可读回任意历史 Revision。
- **接手（M2 收紧）**：`acknowledge_handoff` 不再是「可选的收尾动作」，
  而是一道**诚实性闸门**。请求必须带上调用方实际核对过的 `revision`：
  缺失 → 400 `acknowledge_revision_required`；该版本读不回（不存在或跨项目）→ 404；
  与最新版不一致 → **409 `handoff_revision_stale`**（`details` 同时给出 `viewed` 与 `latest`），
  要求刷新后重新核对，**绝不悄悄换成最新版**。
  一致时才提交，且向 SDK 传 `selection="exact"` + `revision=`，
  提交后按同一 exact revision 读回，因此回执里的 Revision 可与用户核对过的当场比对。
  理由：探针实测服务端会**静默接受**陈旧 revision（核对 r1、确认 r2），
  所以这道门必须由研续自己把守。
- `ReceiverChecks` 恰好三项，运行时自省 `powercontext.http` 已核实：
  `live_state` / `capability` / `authorization`，取值 `confirmed` / `insufficient` / `not_checked`。
  UI 的三个复选框与之一一对应，文案即后端错误消息里引用的原句；
  `status=accepted` 时三项必须全为 `confirmed`，否则 400 `handoff_ack_requires_check` 并点名缺哪项。
  `needs_clarification` / `declined` 不要求全 confirmed——这正是它们的用途。
- **关键结论（已核实）**：`handoff_current_work` / `commit_handoff` / `continue_handoff` /
  `acknowledge_handoff` 路径**不调用任何生成模型**，无模型配置下可用；
  只有 `/v1/handoff/prepare` 与 `/v1/handoff/activate` 需要 generation model，
  未配置时返回 `503 handoff_generation_unavailable`。研续**不使用**这两个端点，
  并把该 503 作为可展示的真实错误处理。
- Handoff 是 Scope 单例，但 `commit` 从不覆盖历史：每次交接追加一个不可变 Revision。
  因此「多次交接历史」是保留的，`GET /api/projects/{id}/handoff?selection=exact&revision=N`
  即可读回旧版；**跨项目读同一 Revision 号返回 404**（PowerContext 按 Scope 隔离交接工件），
  这条已作为项目隔离的一部分写进回归测试。
- 不存在的 Revision（如 999）由服务端返回 404 `artifact_not_found`，
  研续原样透传状态码、`request_id` 与中文提示，不伪装成「暂无交接」。
- 提交时 `PreparedHandoff.base` 必须等于当前 head，否则 409（乐观并发），需重新 finalize。

### 3.6 检索

无 embedding 模型 ⇒ 只有 FTS 可用。所有 `search_memory` 显式传 `mode="fts"`。
启动时读取 `GET /v1/capabilities`，把真实的 `memory_extraction` 与 `search_modes`
展示在 UI 的「技术详情」里——**能力不足要显式告知，不假装支持语义检索**。

「无模型密钥」是研续的**设计前提**而不是故障，因此不按警告呈现：
首屏顶栏只写一句「记忆已连接 · 数据全在本机」，
版本、存储后端、检索方式、能力边界与 Scope/项目标识符全部收进默认折叠的「技术详情」。

### 3.7 错误处理

`PowerContextClient` 抛出的异常全部结构化透传，UI 显示真实横幅：

| 异常（`powercontext.client`） | 语义 | HTTP |
|---|---|---|
| `ServerResponseError` | 服务端非 2xx，带 `status_code` `code` `server_message` `details` `request_id` | 原状态码 |
| `UnauthorizedResponseError` / `ForbiddenResponseError` / `UnavailableResponseError` | 401 / 403 / 503 子类 | 原状态码 |
| `TransportError` | 没拿到 HTTP 响应（Server 挂了 / 端口不通） | 502 |
| `InvalidResponseError` | 响应不符合 schema | 502 |
| `ClientError` | 其余客户端错误 | 500 |

统一响应体：
```json
{"error": {"code": "powercontext_server_response", "status": 409,
           "server_code": "revision_conflict", "message": "…",
           "request_id": "…", "details": {…}}}
```
**禁止**：吞掉异常返回 200、编造 request_id、用缓存冒充实时结果、前端乐观更新后不回滚。

### 3.8 状态语义与诚实性不变量（M2 补）

M2 独立验收暴露的问题有一个共同形状：**数据是对的，呈现方式在撒谎**。
以下五条因此升级为架构级不变量，各自有回归测试锁定。

1. **有效状态语义。** 条目的 `kind` 是分类，`status` 才是状态；两者不能互相冒充。
   `resolved` 的未解决问题不得出现在「未解决问题」里，`done` / `dropped` 的下一步
   不得出现在「下一步」里。历史仍可查（`RestoreBrief` 单列
   `resolved_questions` / `closed_next_steps`），但必须与待办分开呈现。
   交接草稿判定按同一口径：`blocked` 只属于「还有悬着的问题**且**没有可行动的下一步」；
   问题全解决、步骤全关闭时是 `complete`。没有状态标注的问题**按未解决处理**。

2. **时间口径必须写进产物本身。** PowerContext 的 `EntryChange` 只有
   `revision / op / reason / entry_version_id`，**没有时间戳**——
   研续因此**没有**「解决时间」「完成时间」这类数据。
   条目的 `date` 是**记录日期**，绝不可冒称成解决/完成的发生时间。
   报告头部固定印一行「时间口径」，说明区间过滤作用于什么、不作用于什么；
   按当前状态列出的小节，标题就写明「当前有效状态，不按区间过滤」。

3. **引用计数只认真正出现的引用。** 报告附录、`citation_count`、`source_count`
   一律由「正文里实际调用过引用」的收集器产出。没进正文的条目不进附录、不进计数。

4. **降级必须可见，失败必须出声。** 逐版本读历史时，只有「该版本确实读不回来」
   （服务端 404）才允许降级为一条**显式的**不可用说明；超时、网关错误、Server 退出
   一律原样抛成 5xx。禁止用 `except Exception: continue` 把历史悄悄截短。

5. **可点击性由 scheme 决定，不由转义决定。** HTML 转义防不住 `javascript:` / `data:` /
   `vbscript:`。只有 `http://` / `https://` 才渲染成 `<a target="_blank" rel="noopener noreferrer">`，
   其余（含 DOI 这类纯标识符）一律作为纯文本原样展示。
   判定函数 `safe_href()` 为前后端**共用**的唯一口径，报告生成走同一条规则。

另外两条工程不变量：

6. **不留半成品。** 创建项目时，先按 YX1 编码算出目标的真实 UTF-8 字节数并预校验
   （超限 → 400 `goal_too_long`，附 `byte_length` / `limit` 与中文提示），
   **再**创建 Scope 与写目标记忆，**最后**才写注册表。
   目标写入失败时注册表里不会有这个项目，用户看到干净的失败、重试即全新创建。
   （注意：`idempotency_key` 绑定的是本次请求生成的 `project_id`，
   只防服务端重复执行造出两个 Scope，**不提供跨请求幂等**；
   真正的保证来自上述写入顺序。）

7. **日期必须归一化，不能只校验。** Python 3.11 的 `date.fromisoformat` 也接受
   `20261102` 这种 ISO 基本格式，而区间过滤靠**字符串字典序**比较——
   `"20261102" > "2026-11-07"` 为真，会给出错误区间且**不报错**。
   因此 `parse_iso_date` 校验之后一律返回 `YYYY-MM-DD`，
   `EntryInput.date`、`ReportRequest.date_from`、`ReportRequest.date_to` 三处共用。
   起止倒置的区间（`date_from > date_to`）直接 422，不返回一份看起来正常的空报告。

---

## 4. 目录结构

```
qoder/
├── PROJECT.md                  本文件
├── DEVELOPMENT.md              真实验证记录（命令 + 真实输出）
├── README.md                   快速上手
├── app/
│   ├── main.py                 FastAPI 入口 + lifespan（起/停内嵌 PowerContext Server）
│   ├── config.py               路径与端口
│   ├── pc_host.py              内嵌 PowerContext Server（官方 _tutorial.py 模式）
│   ├── codec.py                YX1 记忆文本编解码（纯函数）
│   ├── memory.py               PowerContext 记忆/交接/检索封装
│   ├── registry.py             项目注册表（薄索引 SQLite）
│   ├── errors.py               异常 → 结构化真实错误
│   ├── schemas.py              API Pydantic 模型
│   ├── reports.py              带来源的组会/周报 Markdown 生成
│   ├── routes/                 projects / entries / handoff / reports / system
│   └── static/                 index.html · app.css · app.js
├── scripts/
│   ├── smoke_persistence.py    write → 退出 → 重开 → read（两个独立 OS 进程）
│   └── seed_demo.py            演示数据（真实调用，可重复；含接手三探针）
├── tests/
│   ├── conftest.py             共享夹具：真实内嵌 Server + ASGITransport，无 mock
│   ├── test_codec.py           YX1 编解码纯函数
│   ├── test_api_e2e.py         M1 端到端：闭环 / 隔离 / 修订 / 错误 / 无密钥 / 重启
│   ├── test_m2_regressions.py  M2 行为回归：独立验收打回的每一条
│   ├── test_ui_contract.py     M2/M3 结构契约：解析 HTML/CSS/JS 源文件锁定 P0 与精修要求
│   └── test_site_contract.py   展示页结构契约：资源存在 / 链接结构 / 产品页必备要素
├── site/                       Qoder Sites 展示页（M3 已发布；dist/ 为发布包，git 忽略）
├── evidence/                   真实运行证据（探针原始输出、依赖快照、smoke test 记录）
│   ├── ui/                     界面证据：m1-ledger.png（P0 现场）、m2-overlay-state.json（M2 实测量值）
│   └── publication.json        M3 Qoder Sites 发布事实：站点 ID、操作 ID、产物 sha256、线上核验
└── data/                       运行时数据，git 忽略
```

---

## 5. 验收标准

每条都必须由**真实运行**证明，证据写入 `DEVELOPMENT.md`，不接受「代码看起来对」。

| # | 验收项 | 判定方法 |
|---|---|---|
| A1 | 项目隔离 | 两个项目写入同一关键词，各自 `search_memory(mode="fts")` 只返回本项目命中；测试断言跨项目命中数为 0 |
| A2 | 记忆持久化 | 进程 A 写记忆并正常退出 → 进程 B 重开同一 SQLite → `list_memory_entries` / `get_memory_entry` 读回，文本与 citation 一致 |
| A3 | 修订与历史 | revise 后 `entry_id` 不变、`entry_version_id` 改变；旧 citation 仍可 `get_memory_entry` 读回旧快照；`list_memory_changes(since_revision=0)` 出现 `op=revise` 且带 reason |
| A4 | 陈旧引用冲突 | 用旧 citation 再 revise → 真实 `ServerResponseError` 409，UI 显示冲突而非静默成功 |
| A5 | 交接与恢复 | `commit_handoff` → 全新 client `continue_handoff(latest)` → objective / state / next_action / omissions 一致，`evidence_checks` 全为 available |
| A6 | 恢复简报 | 恢复接口一次性返回目标、已确认决策、未解决问题、下一步、待办、最近记录、上次交接、PowerContext prepare_context 状态 |
| A7 | 带来源报告 | 生成的 Markdown 每条要点后带真实 `entry_id@rev` 引用，含「资料出处」章节；引用可在 UI 回溯到条目历史 |
| A8 | 真实错误提示 | ①超长文本 → 422 且 message 来自 Server；②Server 停止后请求 → 502 `TransportError`；③调用需要模型的端点 → 503 `handoff_generation_unavailable`。三者 UI 均显示红色横幅 |
| A9 | 无模型密钥 | `InferenceConfig()` 全 None 下 A1–A8 全部通过；`capabilities.memory_extraction=false`、`search_modes` 含 `fts` |
| A10 | 不用 localStorage 承载数据 | 前端仅存 UI 偏好（如当前选中项目）；清空浏览器存储后重开，全部业务数据仍从 PowerContext 读回 |

**M2 新增**（对应 §3.8 的不变量；A3 / A5 / A7 的判定方法也按此加严）

| # | 验收项 | 判定方法 |
|---|---|---|
| A11 | 覆盖层不常驻 | 页面刚加载完，四个覆盖层的计算 `display` 均为 `none`、盒尺寸为 0，可访问性树里无 dialog 节点；CSS 里 `[hidden]{display:none !important}` 存在**且** `.drawer{display:flex}` / `.modal-backdrop{display:grid}` 仍在；`boot()` 第一行强制隐藏 |
| A12 | 覆盖层可开可关、焦点可控 | 每次只出现一个（或按栈叠加）；Esc 只关最上层；Tab 焦点被困在当前覆盖层内；关闭后焦点回到触发它的元素；打开时背景禁止滚动。**须由人在可见浏览器里用鼠标验收** |
| A13 | 接手绑定核对过的版本 | 缺 revision → 400 `acknowledge_revision_required`；陈旧 revision → 409 `handoff_revision_stale` 且 `details` 含 `viewed` / `latest`；成功后回执的 `selected_revision` 与用户核对的一致；三项 `ReceiverChecks` 缺任一 → 400 并点名缺哪项 |
| A14 | 交接精确版本读取 | `selection=exact&revision=N` 读回第 N 版；不存在的 N → 404 `artifact_not_found` 原样透传（带 `request_id`）；跨项目读同号 → 404；`exact` 缺 revision → 400；`revision=0` → 422；`selection=prepared` → 400 |
| A15 | 有效状态语义 | 问题全 resolved、步骤全 done/dropped 时草稿判定为 `complete` 而非 `blocked`；`/restore` 不把 resolved / done / dropped 混进「未解决问题」与「下一步」，而是单列 |
| A16 | 报告时间口径与引用诚实 | 起止倒置 → 422；非法与非归一日期 → 422 或归一为 `YYYY-MM-DD`；正文写明时间口径且不出现「本期已解决」；`dropped` 的下一步渲染为删除线且不在待完成清单；附录行数 == `citation_count` == 真正进正文的条目数 |
| A17 | URL 可点击性由 scheme 决定 | `javascript:` / `data:` / `file:` / `vbscript:` / 裸 DOI 的 `url_href` 为空，前端渲染为纯文本；报告正文出现 `<https://…>` 与 `（标识：…）`，且不出现 `<javascript:` |
| A18 | 历史不静默截断 | 健康时 `unavailable == []` 且快照按版本正序；内嵌 Server 停止后 → 5xx、错误码以 `powercontext_` 开头、响应体不含 `changes` |
| A19 | 不留半成品项目 | 超长目标 → 400 `goal_too_long`（带 `byte_length` / `limit`）且随后 `GET /api/projects` 返回 `[]`；缩短后重试即成功 |
| A20 | 首屏讲研究不讲基础设施 | 顶栏不含 `scp_` / `Scope` / `sqlite` / `embedding` / SDK 函数名；SDK 函数名只出现在「技术详情」折叠块内部；六个主要按钮文案为易懂动词；示例数据在界面与数据本身两处都标注为合成、非实测 |

---

## 6. 里程碑

| 里程碑 | 内容 | 状态 |
|---|---|---|
| **M1** | PROJECT.md 基线；真实 PowerContext 持久化 smoke test（跨进程）；可启动纵向功能（建项目 → 录入 → 保存交接 → 恢复 → 出报告）；验证结果写入 DEVELOPMENT.md | **已完成**（界面可用性部分被 M2 独立验收打回，见 DEVELOPMENT §6 更正） |
| **M2** | 修复独立验收发现的 P0 与 8 项后端问题；界面精修（首屏信息层级、易懂按钮、loading/错误/空状态、窄屏、技术详情折叠）；补 21 个回归与契约测试；修订文档；准备展示页源码 | **已完成**（协调人独立复验：43 tests passed、四个边界探针修复正确、可见 Edge 真实点击走完全流程，见 evidence/independent-m2-*.json） |
| **M3** | 通过 Qoder Sites 发布展示网站 | **已完成**：<https://yanxu-research-022wcl7311d.qoder.zone>（public；发布事实见 evidence/publication.json） |
| M4 | 证据包整理（可见浏览器截图 / 日志 / Qoder 开发过程记录），提交材料 | 已完成；正式提测成功，评分待执行，见 evidence/submission.json |

---

## 7. 约束与红线

1. **不复制、不改写、不重实现 PowerContext**。只通过官方 PyPI 包 `powercontext==1.2.0`
   的公开 SDK / HTTP API 调用。
2. **不伪造调用成功**。任何 PowerContext 调用失败必须原样暴露给用户。
3. **不用 localStorage 替代 PowerContext**。业务数据的唯一真源是 PowerContext。
4. API 一律**从官方资料核对**（`README_CN.md` / `docs/` / `examples/jupyter/` /
   `openapi/powercontext.yaml` / `src/` 公开签名），不猜字段名。
5. 只写 `qoder/` 目录，不动其他赛题目录；不推送官方仓库；
   不修改 `E:\Ocean Base\dot-tasks\powercontext-delta`（只读参考），不读取其中凭据。
6. 不修改系统代理、安全设置或其他项目；使用既有 `D:\conda\envs\oceanbase\python.exe`，
   不新建 conda 环境。
7. Windows 上 PowerContext 官方标注为 **experimental**（macOS/Linux 正式支持）。
   这是已知风险，须在 `DEVELOPMENT.md` 记录实测结果。

---

## 8. 环境

| 项 | 值 |
|---|---|
| OS | Windows 10.0.26200 x64 |
| Python | `D:\conda\envs\oceanbase\python.exe`（3.11.17） |
| 关键依赖 | `powercontext[server,cli,client]==1.2.0`、`fastapi`、`uvicorn`、`httpx`、`pytest` |
| PowerContext 存储 | SQLite（`sqlite+aiosqlite:///…`，官方 URL 校验只接受该驱动） |
| 模型密钥 | **不需要**（显式记忆 + FTS + 本人撰写交接） |
| 端口 | 研续 UI/API `127.0.0.1:8000`；内嵌 PowerContext Server 自动选空闲回环端口 |
