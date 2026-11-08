# StepFun 浏览器本地文本知识库

本项目实现：导入文本 → 浏览器 Worker 内生成 embedding → Node 经 seekdb-js 写入 seekdb → 刷新索引 → 浏览器生成查询向量 → seekdb 内全文与向量检索、融合排序 → 展示原文。

**提交材料（2026-11-08整理）：** 当前实现对应的[一页技术说明 PDF](docs/technical-note.pdf)及[文字版](docs/technical-note.md)已更新为 quality-v2，引用2026-11-04独立复测的原始结果。[随源码交付的实测证据](docs/evidence/README.md)包含四组量化/后端、五策略对照、浏览器、降级及持久化记录，并附哈希；不是本次新跑的性能数据。原v1说明保留为[历史版本](docs/technical-note-v1.md)。实验室AMD主机及无缓存全新安装仍待实测。

**检索质量 v2 更新：** 新建库默认使用 IK max_word 和数据库内归一化分数融合（向量/全文 0.75/0.25）。同一 FP16/Chrome/Intel WebGPU 条件，Recall@5 0.583→0.633、nDCG@5 0.574→0.605、P@1 0.750→0.833。语料、查询、qrels 和文档向量均保持不变。完整原因分析、单项对照、同分抖动、失败方案与限制见 [检索质量报告](docs/retrieval-quality.md)。下文初版量化/性能结果完整保留。

实测日期：2026-11-04。Windows 11 / i9-12900H / 16 GiB / Chrome 157.0.8103.38、Edge 156.0.4314.58。两种浏览器完整流程已通过。WebGPU 实际适配器为 Intel gen-12lp，未使用 RTX 3070 Ti。测试开始可用内存约 2.38 GiB；一个模型实例串行运行。

## 本机启动（PowerShell）

```powershell
# 从仓库根目录进入本项目；已在stepfun目录时省略此步
Set-Location .\stepfun
npm ci
npm run db:download
npm run models:download
npm run build
npm start
```

访问 <http://127.0.0.1:4317>。已有依赖、模型和构建文件时，直接 `npm start`。无须 Docker、WSL、模型 API Key 或单独数据库服务。需要代理时，为 `npm ci` 添加本机实际的 `--proxy` 参数，并在下载前设置 `DOWNLOAD_PROXY` 为同一代理地址；不要照抄作者机器的代理端口。该变量只作用于当前进程及子进程，不修改系统设置。`Ctrl+C` 停止服务与数据库子进程；不要同时打开两个服务操作同一数据库目录。

1. 点击“加载并预热模型”，等待页面确认实际后端及精度。
2. 输入名称并新建知识库；该知识库绑定实际模型精度。
3. 粘贴文字、上传 UTF-8 `.txt/.md` 文件，或导入固定的 100 段测试语料。
4. 导入完成后索引自动刷新；输入“新增文档 索引刷新”尝试检索。
5. 可继续导入、切换库或刷新页面。待刷新写入会保留标记并阻止搜索，点击“刷新索引”恢复。
6. 精度切换后请加载对应模型，使用对应精度知识库；不同精度的数据不混用。FP16 自动降级至 WASM 时实际采用 FP32，此时需选择或新建 FP32 知识库。
7. 旧库会继续采用其原版检索配置。点击“优化索引（保留原库）”创建并选中独立优化副本；原库、原文和向量保留，副本刷新完成后才会出现在库列表。新建库直接采用优化配置，列表会标注“已优化”。

## 固定依赖与离线模型

- Node 24.14.0；`package-lock.json` 锁定依赖。seekdb 1.4.0、Transformers.js 3.8.1、ORT Web 1.22.0-dev.20250409-89f8206ba4。
- `.npmrc` 跳过可选默认 embedding peer：上游该插件的发布元数据包含 `workspace:*`，npm 默认解析失败。禁止 SDK 自动向量化，所有集合显式 `embeddingFunction:null`。安装脚本也被禁用，避免下载无用的 Node 推理二进制。构建使用 esbuild 的独立 Windows 二进制包，已实测。
- [中文 BGE 原始模型](https://huggingface.co/BAAI/bge-small-zh-v1.5)，[Xenova ONNX 发布](https://huggingface.co/Xenova/bge-small-zh-v1.5/tree/75c43b069aac4d136ba6bc1122f995fedcfd2781)，修订版 `75c43b069aac4d136ba6bc1122f995fedcfd2781`。完整文件清单及校验值在 `model-manifest.json`。
- 下载 FP32、FP16、Q8 及共享分词器到 `public/models/`；大文件验证 SHA-256，小文件验证 Git blob SHA-1 及长度。运行时禁止远程模型、所有 ORT/WASM 资源由本机提供，CSP 仅允许同源连接。
- FP16 使用发布者提供的半精度权重；Q8 使用其 `model_quantized.onnx`，发布配置为 per-channel、reduce-range、QInt8。没有训练或在后端推理。发布者未给出完整转换工具链版本，本项目复现的是固定 ONNX 文件，不声称重现上游导出过程。
- CLS 池化、L2 归一化、512 维；最多 256 tokens；仅查询增加官方中文检索前缀。导入窗口 220 字符、重叠 24 字符，较长内容分块存储，搜索展示该片段原文。

## seekdb 初始化与数据库内混合检索

`db:download` 获取固定构建 `469a55dc84ea7a9e077161a8b454871a9adaff35` 的官方 Windows x64 绑定（90,789,990 bytes；SHA-256 `40641c08ab488aff9ca278de814d6558169194cc75d61d51b102317732e0b796`），校验后保存到 `.cache/bindings/`。实际内核报告 `seekdb-v1.4.0.0`。

启动后首次 API 请求自动打开 `.data/seekdb` 并初始化 `stepfun_kbs`。每个库创建独立 SDK 集合，物理表为 `c$v2$<collection_id>`，包含 `_id VARBINARY(512)`、`document STRING`、`embedding VECTOR(512)`、`metadata JSON`、中文 IK 全文索引及 cosine/HNSW 向量索引。SDK 的复合配置必须使用 `configuration.hnsw.dimension=512`；顶层 dimension 与 fulltextConfig 并列时会被上游忽略。

Node 只接收、校验、存取浏览器生成的向量。写入先置 dirty，再按稳定 ID upsert；批量完成后执行 `CALL dbms_index_manager.refresh()`，成功才清 dirty。原始内容、来源、片段编号、模型修订版及精度都保存在 seekdb。相同来源、片段编号与内容生成相同 ID；修改后的文本视为新增片段，不做整文件同步删除。

原版 `baseline-v1` 保留：SDK 显式 `queryEmbeddings`、全文 `$contains`、向量候选 20、RRF constant=60/window=60、最终 Top5。已检查执行链：`SET @search_parm` → `DBMS_HYBRID_SEARCH.GET_SQL` → 数据库生成的单条 SELECT，包含全文匹配、向量近邻、FULL JOIN 和 RRF 排名。

当前 `quality-v2`：通过 seekdb-js 的 execute 接口执行一条 CTE SQL，向量与全文各取 50 个候选，在数据库内对距离/BM25 归一化，以 0.75/0.25 加权，再 FULL JOIN 和排序。最终相同分数使用文档 ID 决定次序。新建库的 IK 模式为 max_word，旧库不会被自动覆盖。两种策略均由数据库完成融合，前端和 Node 都不自行拼接两路排名；实际 SQL 和策略名写入 `test-results/hybrid-sql.jsonl`。

整个数据库操作串行化，避免共享连接的 `@search_parm` 并发串线。Windows 原生库会影响 stdout 并保留后台线程，所以放在独立子进程中，以 IPC 返回结果；服务关闭时终止该子进程。数据库启动/请求超时后返回明确错误，静态页面和模型加载仍可用。

可选本地 server 方式：复制 `.env.example` 为 `.env`，设置 SEEKDB_HOST/PORT/USER/PASSWORD/DATABASE；先在外部实例创建数据库并授权。本次只验证了 Windows 原生嵌入式方式，未启动或修复 Docker。凭据仅在 Node 端读取。

## 检索质量 v2 的同条件复现

保持 `npm start` 运行，在另一 PowerShell 窗口执行：

```powershell
$env:QUALITY_FRESH='1'
npm run benchmark:quality
```

脚本从固定语料在浏览器生成文档向量，创建原 smart/RRF 基线库，操作页面的优化按钮得到 max_word 副本，并对原版、仅索引、仅融合、组合及召回优先配置各运行 12 查询×3 轮，轮换执行顺序。每次查询向量均在浏览器重算，一个模型串行运行；输出到带时间戳的新目录。首次复现不需要已有数据库文件或预计算向量。固定语料 SHA-256 会被检查；试验不会改动 qrels。

原 RRF 的整数除法在此数据库默认只保留 4 位小数，存在同分后按内部行号排序的情况。因此全新导入的原版基线可在 0.567/0.583 间变化；原集合、初版记录和这一波动都保留，不能把波动误算成优化收益。新配置在已测从头复现中仍为 0.633，使用文档 ID 打破最终同分。

## 初版量化与性能基线（保留）

```powershell
npm test
# 保持 npm start 运行，依次执行，不并发运行模型测试
npm run test:browser
npm run benchmark
# 模拟 GPU 不可用、FP16 文件初始化故障；均实际降级并检索
node tests/fallback.mjs
# 第二种浏览器，单独记录
$env:CHROME='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
$env:BROWSER_NAME='edge'
npm run test:browser
```

`data/fixture.json` 为自编固定 100 段中文帮助文档 / 12 查询 / 分级相关性标注，`scripts/make-fixture.mjs` 可重建。同主题五篇均标相关，首篇等级 2、其余等级 1；它是工程回归集，不是独立专家标注或通用中文基准。Recall@5 分母为该查询的全部相关文档，nDCG 使用 `(2^grade-1)/log2(rank+1)`。每组查询重复 3 遍，不选择最快一次。脚本不包含任何预计算向量或检索结果。

| 配置 | 权重 MB | Recall@5 | nDCG@5 | 预热后查询向量 ms | 数据库 ms | 端到端 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| FP32 / WebGPU | 94.852 | 0.567 | 0.568 | 28.59 | 5.12 | 47.84 |
| FP16 / WebGPU | 47.497 | 0.583 | 0.574 | 19.14 | 4.79 | 43.58 |
| FP32 / WASM | 94.852 | 0.567 | 0.568 | 14.62 | 4.53 | 29.39 |
| Q8 / WASM | 24.011 | 0.583 | 0.575 | 10.71 | 4.93 | 24.65 |

均为同机 Chrome 实测中位数；WASM 组通过浏览器启动参数实际禁用 WebGPU，自动选择路径报告 `No WebGPU adapter`，随后真实推理、写入、混合检索成功。小查询上 WASM 比此 Intel WebGPU 更快，不能据此推广到其他设备或大批量负载。

模型部署体积按“单个权重 + config.json / tokenizer.json / tokenizer_config.json（合计 440,208 bytes）”统一口径，FP32/FP16/Q8 分别为 95,292,085 / 47,937,635 / 24,451,050 bytes，压缩比 1.988x / 3.897x。全部权重均已经下载且验证，浏览器冷加载来自本机 HTTP，不包含广域网首次下载。

FP32/FP16 WebGPU 冷加载 session 分别约 1088/728 ms、首次模型预热 769/320 ms；FP32/Q8 WASM 分别约 961/569 ms、55/65 ms。原始记录包含本地模型资源请求时间、缓存重载、首条及后续查询、文档 embedding、写入、刷新和 DOM 更新后的端到端耗时。FP16 批大小 1→4，在同一已填充集合中交替顺序测量 3 次：100 段 embedding 中位数 1752→423 ms，导入总时间 3393→1105 ms；这一优化比较不混入首次空库创建成本。

功能测试验证 100 段完整流程、增量写入、dirty 拦截与恢复、空库隔离、刷新页面恢复、重复 upsert、Chrome/Edge 和零外部运行请求。原始 JSON、SQL 和截图在忽略 Git 的 `test-results/`；选定的当前v2独立复测原始JSON已归档到 `docs/evidence/2026-11-04/`，随Git提交交付，无需作者本机测试目录。`docs/technical-note.md` 和同名PDF为当前v2一页说明；上面的v1表保留作历史比较，不能混用不同运行轮次宣称收益。

## 边界与文件

- 本地单用户演示，最多单次 1000 段 / 后端批次 32，未做多用户、图片、OCR、附件解析或生产规模压测。
- 有完整实测但召回率仍有限，不能宣称具备通用知识库的检索质量；未做 C-MTEB、大规模索引或 NVIDIA 适配器测试。
- 断电可能留下 dirty 状态；重启后刷新恢复。没有跨“文本写入+索引刷新”的事务承诺。
- `.cache/`、`.data/`、`.env`、模型、构建资源、`test-results/` 均被 Git 忽略；模型和原生绑定通过固定版本下载脚本获取，生成资源通过build重建。选定的合成测试证据位于可提交的 `docs/evidence/`，不包含运行数据库或密钥。
- `server/`：SDK 与本地 API；`src/`：页面与浏览器推理 Worker；`scripts/`：固定文件下载、构建、诊断；`tests/`：功能及评测；`data/`：固定文本与 qrels。
- 独立数据库检查：先停止 `npm start`，运行 `npm run db:check`，证据写入 `test-results/db-probe.json`；运行过浏览器测试后可用 `node scripts/inspect-db.mjs` 核验持久化原文和向量，再重新启动服务，用 `node tests/persistence.mjs` 验证重启后的检索。

官方参考：[seekdb-js](https://github.com/oceanbase/seekdb-js)、[Transformers.js WebGPU](https://huggingface.co/docs/transformers.js/v3.8.1/en/guides/webgpu)、[精度选择](https://huggingface.co/docs/transformers.js/v3.8.1/en/guides/dtypes)。
