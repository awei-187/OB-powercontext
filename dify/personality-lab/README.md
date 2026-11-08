# 个人使用说明书

一个有明确终点的娱乐选择游戏。玩家先预判自己，再完成六个由 AI 每局重写的生活故事、两次条件反转、一次取舍和一次换位选择，最后得到一份附有真实选择证据的“个人使用说明书”。

本项目面向 Dify × OceanBase “Just for Fun”赛题。Dify 负责两段核心生成：新故事与配套选项、最终档案；PowerContext 保存并召回本局 15 项真实选择。服务器掌管题号、行为锚点、计分、历史原文和证据校验，模型不能修改分数或伪造玩家做过的选择。

生成来源说明：故事的标题格式和反转小节会由程序校正或按固定规则生成，页面会提示。报告主体必须来自模型并通过校验；模型缺失或格式不合适的反转对照、预判／取舍／换位小节目前由本地固定规则补齐，取舍事实句由服务器确定。这些规则段落不应被描述为全部由AI原创。题集与报告分别最多自动尝试两次，失败后的手动重试可能增加模型调用。

> 这是娱乐体验，不是心理诊断或科学量表。

## 已验证状态

2026-11-08 在 Windows 11 上完成真实全流程：

- Dify 1.19.0，自托管 Docker，Workflow 已导入并发布。
- PowerContext 1.5.0，官方 HTTP Server，SQLite 持久化。
- Node.js 24.22.1；项目要求 Node.js 22.18 或更高版本。
- 六项初选、两项反转、两项取舍、两项换位全部完成。
- 15 条真实选择均取得应用写入回执：15 个唯一 content `source_id` 和 15 个唯一 Atomic Memory Artifact；PowerContext 库存显示 30 个 Source（每项同时经过 content 与 remember 两条写入路径）。
- 报告前召回并核对全部 15 项；缺失、串 Scope 或内容不一致会阻止报告。
- 最终报告来源为 Dify，记忆来源为 PowerContext，召回证据 6384 字节。
- 自动测试 18/18，通过全部 4096 种初选组合和 36864 种初选／反转组合。

最终验收见 [`FINAL_ACCEPTANCE.md`](FINAL_ACCEPTANCE.md)，脱敏证据见 [`evidence/`](evidence/)，人工复验步骤见 [`VALIDATION.md`](VALIDATION.md)。

## 体验流程

```text
玩家浏览器
  │
  ▼
可信 Node 后端 ──开始新测试──▶ Dify Workflow ──▶ 六个新故事和配套选项
  │
  ├─每次确认选择──▶ PowerContext：Source + Atomic Memory
  │
  └─生成报告前──▶ PowerContext 召回并核对 15 项
                         │
                         ▼
                    Dify Workflow ──▶ 最终说明书
```

PowerContext 返回的历史被当作不可信资料：后端先检查 Scope、P1—P3、Q1—Q6、R1—R2、T1—T2、S1—S2标识和选择原文，再交给 Dify。题面、选项、报告也会经过服务器结构与证据校验。

## 目录

```text
.
├─ workflow/personal-manual.yml  # 从最终发布应用官方导出的 Dify 0.7.0 DSL
├─ powercontext/                  # 从零安装和运行 PowerContext
├─ evidence/                      # 脱敏的真实运行证据
├─ public/                        # 独立前端
├─ tests/                         # 核心、接口和故障测试
├─ scripts/                       # 浏览器与真实模型诊断工具
├─ server.mjs                     # HTTP 服务、会话和证据边界
├─ services.mjs                   # Dify、DeepSeek、PowerContext 接入
├─ core.mjs / extras.mjs          # 服务器掌管的规则和计分
├─ .env.example
└─ VALIDATION.md
```

## 1. 安装 PowerContext

评测机需要 PowerShell 7、网络和 [uv](https://docs.astral.sh/uv/getting-started/installation/)。在项目根目录执行：

```powershell
.\powercontext\Install-PowerContext.ps1
.\powercontext\Status-PowerContext.ps1
```

脚本安装固定版本 `powercontext[cli,server]==1.5.0` 和 CPython 3.11.18，生成仅当前用户可读的环境文件，并安装官方当前用户服务。若 Task Scheduler 不可用，可使用：

```powershell
.\powercontext\Run-PowerContextForeground.ps1
```

默认地址为 `http://127.0.0.1:8000`，Dashboard 为 `http://127.0.0.1:8000/dashboard/home`。只监听回环地址且关闭认证；不要把此配置暴露到局域网或公网。详见 [`powercontext/README.md`](powercontext/README.md)。

## 2. 导入并发布 Dify Workflow

1. 使用已验证的 Dify 1.19.0，打开“工作室”。
2. 导入 [`workflow/personal-manual.yml`](workflow/personal-manual.yml)。
3. 打开 LLM 节点“有边界地生成新题或档案”。导出时绑定为 `langgenius/openai/openai` / `gpt-4o-mini`；在另一环境导入后，需要绑定到该环境已配置、支持纯 JSON 输出的模型。
4. 建议关闭思考模式，保持输出为纯 JSON，输出上限至少 6000 tokens。
5. 发布 Workflow，在“访问入口 → 后端服务 API”创建该应用专用 API Key。

Workflow 输入：

- `task`：`scenes` 或 `report`
- `payload`：后端生成的 JSON 字符串

Workflow 输出：结束节点的 `result` 字符串。API Key 只配置在后端 `.env`，不要放进 DSL、前端、日志或提交证据。

## 3. 配置并启动应用

```powershell
Copy-Item -LiteralPath .env.example -Destination .env
```

填写 `.env`：

```dotenv
PROFILE_MODE=dify
PROFILE_HOST=127.0.0.1
PROFILE_PORT=8790

DIFY_API_URL=http://127.0.0.1:8080/v1
DIFY_API_KEY=app-请替换为本应用的密钥

POWERCONTEXT_URL=http://127.0.0.1:8000
POWERCONTEXT_TOKEN=
```

启动：

```powershell
npm.cmd start
```

打开 <http://127.0.0.1:8790/>。开始新测试和生成报告各会调用一次 Dify；若模型输出没有通过严格结构校验，题集最多自动重试一次。根据模型速度，这两步各可能需要几十秒。

## 4. 验证

基础测试：

```powershell
npm.cmd test
```

真实全流程按 [`VALIDATION.md`](VALIDATION.md) 操作。页面底部“运行信息”必须显示：

- `Dify 工作流`
- `PowerContext`

最终报告页脚必须显示：

- `Dify 生成档案`
- `已核对 PowerContext 初选与反转记录`

测试失败不会伪装成本地成功：AI 题集失败会明确使用固定题库；PowerContext 未写完或未召回全部 15 项时阻止报告；Dify 报告失败时保留选择供重试。

## 其他模式

`PROFILE_MODE=local` 用于无外部服务的界面预览；`PROFILE_MODE=deepseek` 用于模型直连调试。比赛验收必须使用 `PROFILE_MODE=dify` 且配置真实 PowerContext，不能把 local、mock 或 DeepSeek 结果称为 Dify + PowerContext 验收。

## 安全与提交

- `.env`、`.runtime/`、PowerContext 数据库、日志、安装缓存和部署备份不得提交。
- 不要压缩整个开发目录；按 [`SUBMISSION_CHECKLIST.md`](SUBMISSION_CHECKLIST.md) 清理后再交给比赛仓库维护者。
- 提交路径应为比赛仓库 `dify/personality-lab`。
- 最终 branch 和 commit SHA 必须由比赛仓库维护者确认并推送。
- 当前 DSL 不含知识库或预置数据；不需要导入用户人格资料。

关键设计取舍见 [`docs/DEVELOPMENT_NOTES.md`](docs/DEVELOPMENT_NOTES.md)。完整开发历史仍保留在本机，但不会进入比赛提交。

记忆语义必须准确表述：当前实现验证的是退出或服务重启后继续**同一轮**；每轮使用独立 PowerContext Scope，尚未实现“新一轮自动读取上一轮记录”。
