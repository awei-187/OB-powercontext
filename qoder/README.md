# 研续 Yanxu · 科研与项目工作连续性助手

把「上次做到哪儿了」这件事交给 PowerContext 记住，而不是靠翻聊天记录和自己的脑子。

创建研究项目 → 录入实验记录 / 决策 / 待办 / 资料出处 → 结束工作时保存交接 →
新会话一屏恢复目标、已确认决策、未解决问题和下一步 → 导出带来源追溯的组会 / 周报 Markdown。

- 定位：**个人本地工具**，只监听 `127.0.0.1`。
- 零模型密钥：不配置任何 generation / embedding / rerank 模型也能跑完整个流程。
- 数据真源：所有业务内容只存在 PowerContext 的 SQLite 里。**不使用 localStorage 承载数据**，不 mock，不本地兜底。

需求、架构、验收标准与里程碑见 [PROJECT.md](PROJECT.md)；真实验证结果见 [DEVELOPMENT.md](DEVELOPMENT.md)。
参赛展示页（静态介绍页，不运行后端）已发布：<https://yanxu-research-022wcl7311d.qoder.zone>，
源码与发布事实见 [site/](site/) 与 [evidence/publication.json](evidence/publication.json)。
参赛材料、Qoder UID、验证样例与证据索引见 [SUBMISSION.md](SUBMISSION.md)。

---

## 快速上手

下面全部是 **Windows PowerShell** 命令。**每个代码块只有一条命令**，请逐块复制执行；
需要换目录的地方单独列一块。多行粘贴在 PowerShell 里容易把注释和命令黏成一行，所以这里不合并。

### 0. 环境版本（本机实测）

| 项 | 值 |
| --- | --- |
| 操作系统 | Windows 11，`10.0.26200` x64 |
| Shell | Windows PowerShell 5.1 |
| Python | `3.11.17`，解释器 `D:\conda\envs\oceanbase\python.exe`（既有 Conda 环境，未新建） |
| powercontext | `1.2.0` |
| fastapi / uvicorn | `0.162.0` / `0.54.0` |
| httpx / pydantic | `0.28.1` / `2.14.2` |
| sqlalchemy / aiosqlite | `2.1.6` / `0.22.1` |
| pytest | `9.2.0` |
| Node（仅 Qoder 自身需要，研续运行不依赖） | `v24.21.0` |
| 模型密钥 | **一项都没配**，核心流程照跑 |

完整依赖清单见 [evidence/dependencies/pip-freeze-after.txt](evidence/dependencies/pip-freeze-after.txt)。
下面的命令都写作 `python`；若你的 `python` 不指向这个环境，
请把它整条替换成 `D:\conda\envs\oceanbase\python.exe`。

### 1. 获取代码（参赛分支）

仓库默认分支不含研续，**必须指定分支**克隆：

```powershell
git clone --branch competition/qoder-yanxu --single-branch https://github.com/awei-187/OB-powercontext.git
```

```powershell
cd OB-powercontext/qoder
```

（本机的开发副本在 `E:\Ocean Base\qoder-competition\qoder`；评委与新用户一律从上面的分支克隆。）

### 2. 安装依赖

```powershell
python -m pip install -r requirements.txt
```

### 3. 播种一整套示例数据

从**空目录**跑通完整流程（创建两个项目、写入 7 条记忆、修订、故意触发 409、退役、
保存交接、接手三探针、校验隔离、生成周报）。脚本只调用研续自己的 HTTP API，全部真实写入 PowerContext。

```powershell
$env:PYTHONIOENCODING = "utf-8"
```

```powershell
python scripts/seed_demo.py --data-dir data/demo
```

不加 `--force`：目录非空时脚本会拒绝覆盖，不会删你的数据；确认要重建才加 `--force`。
`$env:PYTHONIOENCODING` 只是为了让 Windows 控制台（默认 GBK）正确显示中文示例数据，
不改系统区域设置。示例数据全部带【示例】前缀，且**数据本身**就写明
「合成演示数据，全部数字均为虚构、非实测」——请勿把其中 12ms、命中率等数字当作实测结果引用。

### 4. 用同一数据目录启动服务

seed 默认写 `data/demo`，而服务默认读 `data`，**两者不是同一个目录**，
所以启动前把 `YANXU_DATA_DIR` 指到第 3 步用的目录：

```powershell
$env:YANXU_DATA_DIR = "$PWD\data\demo"
```

```powershell
python -m app.main
```

服务在**前台**运行并占用这个窗口。看到下面两行即启动完成（冷启动约 10.5 秒，其中约 7.3 秒是 PowerContext 服务端模块的导入开销）：

```
研续 Yanxu → http://127.0.0.1:8000
数据目录   → …\qoder\data\demo
```

### 5. 打开页面（另开一个 PowerShell 窗口）

第 4 步的窗口被服务占用，**另开一个 PowerShell 窗口**执行：

```powershell
start http://127.0.0.1:8000
```

交互式接口文档在 <http://127.0.0.1:8000/api/docs>。

不想用示例数据，就跳过第 3 步、把第 4 步的 `YANXU_DATA_DIR` 指向一个空目录（或干脆不设，
默认 `qoder\data`），从空白开始建自己的项目。

> **端口冲突**：若 8000 已被占用，改 `YANXU_PORT` 即可。
> 内嵌 PowerContext Server 自己会挑一个空闲回环端口，不需要配置，
> 实际地址显示在页面顶栏「技术详情」里。

### 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `YANXU_DATA_DIR` | `qoder/data` | 数据目录。PowerContext SQLite、工作区与项目索引都在里面 |
| `YANXU_HOST` | `127.0.0.1` | 监听地址。请保持回环，本工具没有多用户鉴权 |
| `YANXU_PORT` | `8000` | 监听端口 |
| `YANXU_PC_TIMEOUT` | `120` | PowerContext 客户端超时（秒） |
| `YANXU_PC_START_TIMEOUT` | `60` | 内嵌 PowerContext Server 启动超时（秒） |
| `PYTHONIOENCODING` | 未设 | 建议设为 `utf-8`，否则控制台 GBK 会把中文输出打成乱码 |

---

## 目录

```
qoder/
├── PROJECT.md              需求、架构、验收标准 A1–A20、里程碑
├── DEVELOPMENT.md          真实验证记录：命令、输出、已知边界、M2 更正
├── requirements.txt        运行依赖
├── pytest.ini
├── app/
│   ├── main.py             FastAPI 入口 + lifespan（拉起/关闭内嵌 PowerContext）
│   ├── pc_host.py          内嵌 PowerContext Server（官方 _tutorial.py 模式）
│   ├── memory.py           记忆层：唯一真源，全部走官方 SDK
│   ├── codec.py            YX1 行式编码：结构化字段 ⇄ PowerContext memory text
│   ├── reports.py          组会 / 周报 Markdown 生成（确定性，无模型）
│   ├── registry.py         项目索引（SQLite，只存 id/name/scope_id 等元信息）
│   ├── errors.py           真实错误透传：不吞、不伪造成功、不编造 request_id
│   ├── schemas.py / deps.py / config.py
│   ├── routes/             system · projects · entries · handoff
│   └── static/             index.html · app.css · app.js（无框架、无构建步骤）
├── scripts/
│   ├── seed_demo.py        从空数据目录播种示例数据并跑通全流程
│   └── smoke_persistence.py  write → 退出 → 重开 → read 的持久化 smoke test
├── tests/                  43 个测试，全部打真实的内嵌 PowerContext Server
├── site/                   Qoder Sites 展示页源码（静态）
└── evidence/               验证证据：smoke 记录、依赖快照、验收计划、界面实测量值
```

---

## 核心机制

**项目隔离** —— 一个项目对应一个 PowerContext Scope。检索、恢复、周报都只在当前 Scope 内进行；
在另一个项目里搜同一个词命中 0 条。交接工件同样按 Scope 隔离：
在项目 B 里精确读项目 A 的交接 Revision 会得到 404。

**记忆修订与历史** —— 修订走 PowerContext 的 `revise`：`entry_id` 不变、版本号推进、
旧版本仍可读回，变更历史（`add` / `revise` / `deactivate`）带原因。
PowerContext 没有物理删除，「退役」后条目转为 `inactive`，历史完整保留。
历史**不会静默截短**：某个版本读不回来时，界面显式标出「该版本不可读」及其服务端原文，
而不是当作它不存在；服务端整体不可用时直接报 5xx，不返回半截历史。

**来源回溯** —— 每条记忆都带 `MemoryCitation`（`memory_ref` + `entry_id` + `entry_version_id`），
页面上显示为 `mem_9846e69e@v1` 这样的短引用，周报附录把它们展开成完整追溯表。
保存交接时，勾选的已确认状态会带上真实引用以 `basis=verified` 提交；
一旦正文被改得与所引记忆不一致，标记当场降级为 `declared` 并说明原因，不会假装仍是 verified。
恢复时 PowerContext 自己校验这些引用是否仍可回溯（`evidence_checks`），页面上逐条打勾。

**接手必须绑定你核对过的版本** —— 交接的每个 Revision 不可变，
「确认接手」请求必须带上你**实际核对过**的那个 Revision。
它已不是最新版时研续返回 409 并要求刷新，**绝不悄悄换成最新版**；
成功后回执里的 Revision 会与你的核对版本当场比对并显示「一致 / 不一致」。
三项接收方核对（状态一致 / 具备环境工具 / 有权接手）与 PowerContext 的
`ReceiverChecks{live_state, capability, authorization}` 一一对应，`accepted` 时三项缺一不可。

**报告的时间口径写在正文里** —— PowerContext 的变更日志**不含时间戳**，
所以研续没有「解决时间」「完成时间」这类数据，也不会拿记录日期去冒充。
周报头部固定印一行时间口径，说明统计区间只过滤「带日期的工作记录」与「已完成待办」，
而目标、决策、问题、下一步、资料出处是**当前有效状态**。
已解决的问题列在「已解决（当前有效状态，不按区间过滤）」下，已放弃的下一步带删除线单列。
附录与引用计数**只统计真正出现在正文里的条目**。

**真实错误提示** —— PowerContext 的 4xx / 5xx 原样透传：服务端消息、错误码、真实 `request_id`、
`details` 全部显示在红色横幅里，研续只在旁边补一句中文提示。
服务不可用时返回 5xx 错误，**绝不返回空列表冒充成功**。

**资料链接的可点击性由协议决定** —— 只有 `http://` / `https://` 才渲染成链接；
`javascript:` / `data:` / `file:` 以及 DOI 这类纯标识符一律作为纯文本原样展示。
HTML 转义挡不住危险协议，所以判定放在后端、前后端共用同一条规则。

**无模型密钥** —— `InferenceConfig()` 全字段为 None，`capabilities` 实测
`memory_extraction=False`、`search_modes=[auto, fts]`、`handoff_generation=False`。
研续只用显式记忆 + FTS 检索，交接由本人撰写（`handoff_current_work` → `commit_handoff`），
这条路径不需要生成模型。这是**设计前提**而不是故障，所以首屏不按警告呈现：
顶栏只写「记忆已连接 · 数据全在本机」，版本、存储后端、检索方式、能力边界与
Scope / 项目标识符都收进默认折叠的「技术详情」。

---

## 测试

```powershell
cd "E:\Ocean Base\qoder-competition\qoder"
```

```powershell
$env:PYTHONIOENCODING = "utf-8"
```

```powershell
python -m pytest -v
```

预期结果（本机实测）：

```
collected 43 items

tests\test_api_e2e.py .......                                            [ 16%]
tests\test_codec.py ........                                             [ 34%]
tests\test_m2_regressions.py .........                                   [ 55%]
tests\test_site_contract.py .....                                        [ 67%]
tests\test_ui_contract.py ..............                                 [100%]

============================= 43 passed in 25.91s =============================
```

43 个测试分五类，**没有任何 mock**——每个端到端测试都拉起真实的内嵌 PowerContext Server
（真实 SQLite，临时数据目录），再用 `httpx.ASGITransport` 打真实 HTTP 路由：

| 文件 | 数量 | 覆盖 |
| --- | --- | --- |
| `test_codec.py` | 8 | YX1 编解码纯函数：字段往返、空头部键省略、正文含 `---`、头部换行被拒、标签去重、CRLF 归一、外来文本容忍、NFC/UTF-8 字节数 |
| `test_api_e2e.py` | 7 | M1 端到端：完整闭环、项目隔离、修订与历史、陈旧引用 409、真实错误透传、Server 停止后的 5xx、无模型密钥、整体重启后数据仍在 |
| `test_m2_regressions.py` | 9 | M2 行为回归：有效状态语义、接手版本绑定、三项 ReceiverChecks、交接精确版本读取、报告时间口径与引用诚实、URL 协议白名单、超长目标不留半成品、日期归一化、历史不静默截断 |
| `test_ui_contract.py` | 14 | M2/M3 结构契约：解析 HTML/CSS/JS 源文件，锁定覆盖层显隐机制、可访问性、焦点管理、首屏信息层级、按钮文案、窄屏支持、合成数据标注、本地日期默认值 |
| `test_site_contract.py` | 5 | 展示页结构契约：HTML 结构、本地资源存在、页内锚点可达、外链只指向已核实仓库、产品页必备要素（源码入口 / 五步流程 / 三张真实截图 / 运行与局限） |

`test_m2_regressions.py` 里每个测试的 docstring 都写明「修复前的错误行为」，
断言失败时能直接看出是哪一处回退。
`test_ui_contract.py` 与 `test_site_contract.py` 是源文件契约测试，不需要起服务。

> `pytest.ini` 设了 `--basetemp=.pytest-tmp`：本机 `%TEMP%\pytest-of-wjp` 目录不可写
> （`PermissionError: [WinError 5]`），改用项目内临时目录绕开，没有修改任何系统权限。

---

## 已知边界

- PowerContext 官方把 Windows 支持标注为 experimental。本机（Windows 11 / Python 3.11.17）
  实测 smoke test 与全部 43 个测试通过，未遇到 Windows 特有问题。
- 未配置 embedding 模型，检索只有 FTS（关键词），没有语义召回。
- 未配置生成模型，`/v1/handoff/prepare`、`/v1/handoff/activate` 会返回
  503 `handoff_generation_unavailable`。研续不使用这两个端点，改用本人撰写路径。
- 没有自动记忆提取（`memory_extraction=False`）：所有记忆都由用户显式录入。
- 单用户本地工具，没有鉴权。请只监听回环地址。
- 桌面可见浏览器已独立验收建项、记忆修订、交接、恢复与复制报告，见
  [M2 界面记录](evidence/independent-m2-ui.json) 和 [M3 复现记录](evidence/independent-m3-ui.json)。
  文件下载落盘与窄屏视觉尚未独立验证；复制导出已验证。
- 研续**不主张任何量化的时间节省**。PROJECT.md 初稿里那个「重建一次要 20–60 分钟」
  没有测量支撑，已删除并标注为未验证假设。

细节与实测输出见 [DEVELOPMENT.md](DEVELOPMENT.md)。
