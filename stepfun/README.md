# StepFun 浏览器本地知识库

本项目已在 AMD 实验室主机完成真实闭环：导入文本 -> 浏览器 Worker 本地 embedding -> seekdb-js 1.4.0 -> Docker Linux 官方 seekdb Server -> 数据库内向量/全文混合检索 -> 展示原文。没有云端推理、预计算回放、SQLite、内存检索或客户端双路拼合。

当前提交说明：[一页技术说明](docs/technical-note.pdf) / [Markdown](docs/technical-note.md)。本轮可提交原始证据位于 [docs/evidence/2026-11-08-amd-server](docs/evidence/2026-11-08-amd-server/README.md)；旧 Intel 结果仍保留在 `docs/evidence/2026-11-04/` 和 `docs/technical-note-v1.md`，不得与 AMD 结果混写。

## 已验证环境

- Windows 11，AMD Ryzen 7 7700X，32 GiB；AMD RDNA-2 WebGPU。
- Chrome 156.0.8078.80；Edge 157.0.4341.42。
- Node 24.14.0；Transformers.js 3.8.1；ORT Web 1.22.0-dev.20250409-89f8206ba4。
- seekdb-js 1.4.0；服务端 `5.7.25-OceanBase seekdb-v1.4.0.0`。
- 官方镜像 `oceanbase/seekdb:1.4.0-100000172026082615`；Linux/amd64 manifest `sha256:f9e45426cdd6f26db6f967753fa3258829e462e32715211265227f1be5575ce4`。
- 仅发布 `127.0.0.1:12881`，数据库 `stepfun_lab`；named volume `stepfun_seekdb_data` 挂载 `/var/lib/seekdb`。
- 容器 2 CPU / 3 GiB，seekdb 内存 2 GiB，pids 1024；未修改 WDAC、Application Control、Code Integrity、杀毒或证书校验，未影响 Dify/PowerContext 容器与卷。

Windows 原生 `seekdb.node/seekdb.dll` 在该受管主机上被 Code Integrity 拒绝。本轮不绕过系统策略，默认采用已获准的 Docker Linux Server；`SEEKDB_HOST` 分支只走 mysql2，嵌入式 addon 不会加载。

## 首次部署

要求 Docker Desktop 使用 Linux engine。不要使用 `latest`，不要把 1.4+ 数据目录直接绑定到 NTFS，也不要运行 `docker compose down -v`。

```powershell
Set-Location .\stepfun

# 生成本机随机秘密；只写入被 Git 忽略的 deploy/seekdb/.env 与项目 .env
.\deploy\seekdb\configure.ps1

# 启动固定官方镜像，等待真实 SELECT 1，再创建/授权应用账号并输出 VERSION()
.\deploy\seekdb\start.ps1
.\deploy\seekdb\status.ps1

npm ci
npm run models:download
npm run build
npm start
```

访问 <http://127.0.0.1:4317>。健康接口必须同时满足 `ok:true`、`mode:"server"` 并返回 seekdb 版本，端口开放或容器 running 不能代替 SQL 就绪。

停止数据库但保留数据：

```powershell
.\deploy\seekdb\stop.ps1
```

配置模板见 `.env.example`。真实密码不得写入日志、源码或交付证据。独立服务模式诊断：

```powershell
$env:RESULT_DIR='test-results/manual-server-check'
npm run db:check:server
```

旧 `npm run db:check` / `scripts/check-db-child.mjs` 是嵌入式路径，只用于允许原生 addon 的环境；其 Windows native 失败不代表 Server 失败。

## 浏览器 embedding

模型为公开的 [Xenova/bge-small-zh-v1.5](https://huggingface.co/Xenova/bge-small-zh-v1.5)，固定修订 `75c43b069aac4d136ba6bc1122f995fedcfd2781`。完整路径、字节数和哈希在 `model-manifest.json`。

- CLS pooling、L2 归一化、512 维、最多 256 tokens；仅查询增加中文检索前缀。
- FP16 为发布者半精度 ONNX；Q8 为 per-channel、reduce-range、QInt8。
- FP32/FP16/Q8 的部署体积为 95,292,085 / 47,937,635 / 24,451,050 bytes；压缩比 1.988x / 3.897x。
- 文档和查询均在浏览器 Worker 推理；模型与 ORT 资源同源，远程模型禁用。
- 显式优先 WebGPU；无适配器或 FP16 初始化失败自动降级 WASM/FP32，并在 UI 显示实际后端和精度。
- 所有集合都使用 `embeddingFunction:null`；Node/容器不生成 embedding。

## seekdb 数据与混合检索

每个知识库使用独立集合/物理表，保存稳定文档 ID、原文、`VECTOR(512)` 和 JSON 元数据，建立 IK max_word 全文索引与 cosine/HNSW 向量索引。

`quality-v2` 使用一条参数化 CTE SQL：

1. 在 seekdb 中各取 50 个向量和全文候选。
2. 用窗口函数分别归一化 cosine distance 与 BM25。
3. 在 seekdb 内按 0.75 / 0.25 加权并 `FULL JOIN`。
4. 由数据库排序并返回 Top K；前端和 Node 不拼合两路结果。

seekdb-js 1.4.0 的通用 `execute()` 不把 `WITH` 开头识别为行集，因此 Server 模式通过 SDK 已建立的 mysql2 连接执行同一条 CTE；SQL、参数化、融合位置均未改变。代表性实际 SQL 已归档为 `hybrid-sql-sample.json`。

每个串行业务请求前用只读 `SELECT 1` 检查 SDK 连接；若容器重启使 mysql2 旧连接失效，只关闭 SDK 连接并以有界短退避重连，业务写入/查询本身不重放。容器重启后使用 `-NoProxy` 的首个应用健康请求已直接返回 200；PowerShell 本机代理可能对 127.0.0.1 产生假 502，诊断命令须使用 `-NoProxy` 或 `curl.exe`。

写入前持久化 dirty，批量 upsert 后执行 `CALL dbms_index_manager.refresh()`，成功才清 dirty 并允许搜索。已验证 100 段导入、增量新增、dirty 拦截/刷新、重复 upsert、空库隔离、切库、页面恢复，以及容器和应用重启后的持久化。

## AMD Server 实测结果

固定语料：100 段、12 查询、每查询 3 次、Top 5、batch=4、WASM 2线程、单模型串行。下表为 Chrome 预热后中位数；查询 embedding 在浏览器，检索为真实 seekdb Server。

| 配置 | 部署 MB | Recall@5 | nDCG@5 | 查询向量 ms | seekdb ms | 端到端 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| FP32 / WebGPU | 95.292 | 0.633 | 0.605 | 14.81 | 1.88 | 24.28 |
| FP16 / WebGPU | 47.938 | 0.633 | 0.605 | 13.73 | 2.00 | 22.08 |
| FP32 / WASM | 95.292 | 0.633 | 0.605 | 12.69 | 1.97 | 20.99 |
| Q8 / WASM | 24.451 | 0.633 | 0.617 | 8.48 | 1.98 | 16.66 |

Q8 在这个小型回归集的 nDCG 高 0.012，不能外推为普遍质量提升。冷加载 session / 首次预热分别为 FP32-WebGPU 555/225 ms、FP16-WebGPU 432/228 ms、FP32-WASM 525/37 ms、Q8-WASM 348/43 ms；模型来自本机 HTTP，不含互联网下载。

FP16 batch 1 -> 4：100 段 embedding 中位数 927.65 -> 744.21 ms，导入总计 2597.08 -> 1819.25 ms。UI 完整流程一次实测为 embedding 840.67 ms、写入 426.86 ms、刷新 813.28 ms、总计 2265.25 ms。五策略独立对照中 baseline -> quality-v2：Recall@5 0.567 -> 0.633，nDCG@5 0.568 -> 0.605，seekdb 中位数 3.35 -> 1.93 ms。

这套 12 查询是自编工程回归集，不是独立通用中文基准；未做大规模、多用户、图片/OCR 或断电事务测试。

## 复测命令

保持 `npm start` 运行；真实模型测试串行，使用独立测试库和新的 `RESULT_DIR`：

```powershell
npm test
$env:EXPECT_DB_MODE='server'
$env:RESULT_DIR='test-results/amd-server-<timestamp>'
npm run test:browser
node tests/fallback.mjs
npm run benchmark
$env:QUALITY_FRESH='1'
npm run benchmark:quality

$env:CHROME='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
$env:BROWSER_NAME='edge'
npm run test:browser
```

重启持久化验证使用 `node tests/persistence.mjs`；持久化原文/向量核验使用 `node scripts/inspect-db.mjs`。不要把两文本微测当作 100 段数据库全链路性能。

## 安全审计

默认 `npm audit --json` 为 5 个 high 节点、0 critical，原始报告随证据归档；详细依赖链、公告和升级边界见 [安全审计](docs/security-audit-2026-11-08.md)。未运行 `audit fix --force`。

- Transformers 3.8.1 -> sharp 0.34.5：修复需要 Transformers 4.3.2 主版本迁移。
- seekdb 1.4.0 -> 可选 `@seekdb/js-bindings` -> adm-zip 0.5.18：Server 模式不加载该嵌入式链；npm 建议降级 seekdb 1.1.1，与已验证 1.4 Server 不兼容。
- `npm audit --omit=optional` 仍报告 Transformers/sharp 两个 high；这是暴露面分析，不宣称锁文件已清零。

当前没有在声明范围内且不改变运行基线的兼容锁文件修复。后续应在独立分支迁移 Transformers 4.3.2+，并等待/验证 seekdb-js 使用修复后的归档依赖，再重跑完整模型和数据库矩阵。

## 目录

- `deploy/seekdb/`：固定 compose、非秘密示例、配置/启动/状态/停止脚本。
- `server/`：API、seekdb Server/embedded 模式与数据库内混合检索。
- `src/`：页面和浏览器 Worker 推理。
- `tests/`：浏览器功能、降级、性能、质量和持久化。
- `docs/evidence/2026-11-08-amd-server/`：本轮无秘密原始证据及哈希。
- `test-results/`：本机完整时间戳原始记录，Git 忽略。

官方参考：[seekdb Docker 镜像](https://github.com/oceanbase/docker-images/blob/main/seekdb/README.md)、[seekdb-js](https://github.com/oceanbase/seekdb-js)、[Transformers.js WebGPU](https://huggingface.co/docs/transformers.js/v3.8.1/en/guides/webgpu)。
