# StepFun AMD + seekdb Server 本机验收报告

日期：2026-11-08（Asia/Shanghai）
项目：`D:\67stepfun\stepfun-lab-2026-11-08\stepfun`

## 结论

真实数据库闭环已经完成，不是仅健康检查通过：Chrome/Edge 均完成 100 段浏览器本地 embedding、seekdb Server 写入/刷新、数据库内混合检索、增量/dirty/重复 upsert/空库隔离/页面恢复；两条 WASM 降级路径包含真实数据库检索；容器和应用重启后持久化通过；性能与质量均生成新的 AMD Server 原始数据。

本机运行与测试工作已完成，结果和可复现材料已整理。`npm audit` 的 5 个 high 节点没有可保持现有 1.4/Transformers 3.x 基线的兼容锁文件修复，已完整披露。代码提交、正式仓库整合及 GitHub 评阅不属于本机职责。

## 真实 Server

- 地址：`127.0.0.1:12881`；数据库：`stepfun_lab`；应用健康：`http://127.0.0.1:4317/api/health`。
- `SELECT VERSION()`：`5.7.25-OceanBase seekdb-v1.4.0.0`。
- SDK：`seekdb-js 1.4.0`；服务模式为 `mysql2`，未加载 Windows `seekdb.node/seekdb.dll`。
- 镜像：`oceanbase/seekdb:1.4.0-100000172026082615`。
- 本地镜像/索引 digest：`sha256:4db4961869d554313520d6081fca29265ba6da6db7313311bd8acbed771a956b`。
- Linux/amd64 manifest digest：`sha256:f9e45426cdd6f26db6f967753fa3258829e462e32715211265227f1be5575ce4`。
- 容器：`stepfun-seekdb-1`，2 CPU / 3 GiB / 1024 pids；seekdb 内存 2 GiB。
- 持久化：named volume `stepfun_seekdb_data` -> `/var/lib/seekdb`；只发布 `127.0.0.1:12881`。
- Docker：Desktop 4.98.0、Linux engine 29.9.2、Compose 5.6.1、linux/amd64。

可复现文件：

- `deploy/seekdb/compose.yml`
- `deploy/seekdb/.env.example`
- `deploy/seekdb/configure.ps1`
- `deploy/seekdb/start.ps1`
- `deploy/seekdb/status.ps1`
- `deploy/seekdb/stop.ps1`
- 项目 `.env.example`
- `scripts/check-db-server.mjs` / `npm run db:check:server`

停止脚本只停止专属容器，不删除容器或 named volume。真实凭据只在被 Git 忽略的本机 `.env` 中。

## 源码改动

1. 新增固定官方镜像的 Docker Linux Server 部署、健康检查、应用账号授权与安全停止脚本。
2. `.env.example` 默认描述 Server 模式；`.gitignore` 忽略 `.env`、旧秘密备份、缓存、数据库与测试目录。
3. `server/db.mjs` 支持 `RESULT_DIR`；Server 模式对 `WITH` 开头的 quality-v2 使用 SDK 已建立的 mysql2 连接取行结果，解决 seekdb-js 1.4.0 `execute()` 对 CTE 返回空值的问题。检索 SQL、参数化与数据库内融合不变；每个请求前用只读 `SELECT 1` 预检，失效时有界短退避重连，业务请求不重放。
4. 新增 `scripts/check-db-server.mjs`，从同一 `.env` 直连执行 `SELECT 1`、版本、数据库/账号和表计数，不再误用嵌入式诊断。
5. 浏览器、fallback、benchmark、quality、persistence 和 inspect 脚本增加 `RESULT_DIR`、Server 健康/模式校验；质量脚本支持空库等待；浏览器路径可由 `CHROME` 指定。
6. benchmark 的数据库条件改为实际 `/api/health` 返回的 `mode/version`，不再硬编码 `native Windows`。
7. 更新 README、一页技术说明、安全审计、AMD Server 证据包和 SHA-256 清单；旧 Intel 证据未覆盖。

## 数据库完整验收

| 检查 | 结果 |
| --- | --- |
| 直接 SQL 就绪 | 通过；`SELECT 1`、版本、数据库、应用账号、15 张表 |
| Chrome 100 段完整流程 | 通过；FP16/WebGPU/AMD；真实 Server |
| Edge 100 段完整流程 | 通过；FP16/WebGPU/AMD；真实 Server |
| 增量、dirty、刷新 | 通过；dirty 阻止查询，刷新后新增内容可检索 |
| 重复 upsert | 通过；稳定 ID，最终 101 段 |
| 空库/切库隔离 | 通过 |
| 页面恢复 | 通过 |
| WASM 降级 | 两条路径通过；无 GPU 和 FP16 初始化失败均真实检索 |
| SQL 融合 | 通过；单条 CTE 包含 cosine、MATCH、窗口归一化、FULL JOIN、0.75/0.25 排序 |
| 持久化 | 通过；容器和应用重启后原文、元数据、512-D 向量、检索恢复 |
| 单元测试 | 7/7 通过 |
| Windows 原生库 | 最终 Server 日志无 addon 引用；Server 验收期间 Code Integrity 日志无新相关事件 |
| 其他容器 | Dify 相关 16 个既有容器仍运行，健康容器仍 healthy；未删除/修改其卷 |

第一次 Server 浏览器运行在 CTE 行结果兼容点失败，原始记录保留为 `browser-attempt1-failed.json`；最小修复后 Chrome/Edge、fallback、benchmark、quality、persistence 全部通过。

## AMD 新性能与质量

设备：Ryzen 7 7700X、32 GiB、AMD RDNA-2；Chrome 156.0.8078.80、Edge 157.0.4341.42。固定 100 段、12 查询、每查询 3 次、Top 5、batch=4、WASM 2线程、单模型串行；下表为 Chrome 预热后中位数。

| 配置 | 部署 MB | R@5 | nDCG@5 | 查询 embedding ms | seekdb ms | 端到端 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| FP32 / WebGPU | 95.292 | 0.633 | 0.605 | 14.81 | 1.88 | 24.28 |
| FP16 / WebGPU | 47.938 | 0.633 | 0.605 | 13.73 | 2.00 | 22.08 |
| FP32 / WASM | 95.292 | 0.633 | 0.605 | 12.69 | 1.97 | 20.99 |
| Q8 / WASM | 24.451 | 0.633 | 0.617 | 8.48 | 1.98 | 16.66 |

- 部署体积：FP32/FP16/Q8 = 95,292,085 / 47,937,635 / 24,451,050 bytes；压缩比 1.988x / 3.897x。
- 冷 session/首次预热：555/225、432/228、525/37、348/43 ms。
- FP16 batch 1 -> 4：100 段 embedding 927.65 -> 744.21 ms；导入总计 2597.08 -> 1819.25 ms。
- UI 完整一次：embedding 840.67、写入 426.86、刷新 813.28、总计 2265.25 ms；首查询 embedding 15.28、数据库 6.55、端到端 38.95 ms。
- Q8 的 nDCG 在该小型回归集高 0.012，不宣称普遍质量提升。

五策略同条件结果：

| 策略 | R@5 | nDCG@5 | P@1 | seekdb ms | E2E ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| baseline | 0.567 | 0.568 | 0.750 | 3.35 | 30.77 |
| index-only | 0.617 | 0.572 | 0.667 | 3.43 | 30.75 |
| fusion-only | 0.600 | 0.614 | 0.833 | 1.89 | 30.76 |
| quality-v2 | 0.633 | 0.605 | 0.833 | 1.93 | 30.79 |
| recall-priority | 0.650 | 0.595 | 0.667 | 1.91 | 30.97 |

原始目录：`D:\67stepfun\stepfun-lab-2026-11-08\stepfun\test-results\amd-server-final-2026-11-08-140700`。提交安全副本：`docs/evidence/2026-11-08-amd-server/`，15 个文件哈希全部复核通过。

## npm 漏洞分析

`npm audit --json`：5 high、0 critical；没有运行 `audit fix --force`。

1. 直接生产依赖 `@huggingface/transformers 3.8.1`，因 `sharp 0.34.5` 被标 high；修复需要 Transformers 4.3.2（semver-major）。sharp 公告为 libvips、libheif、librsvg 三组。
2. 直接生产依赖 `seekdb 1.4.0` 的可选嵌入式链 `@seekdb/js-bindings 1.4.0 -> adm-zip 0.5.18` 被标 high；Server 模式不加载该链。npm 建议降级 seekdb 到 1.1.1，与本次 1.4 Server/SQL 不兼容。
3. adm-zip 最新修复为 0.6.1，但超出 js-bindings 声明的 `^0.5.16`；强制 override 会隐藏审计节点且未验证原生下载器，不作为兼容修复。
4. `npm audit --omit=optional` 为 2 high（Transformers/sharp），只用于说明 Server 运行时暴露面，不宣称默认锁文件已修复。

决定：本轮不做不兼容升级或降级。后续独立依赖分支迁移 Transformers 4.3.2+，并等待/验证 seekdb-js 使用修复后的归档依赖，必须重跑完整模型/数据库矩阵后再合并。

## 凭据与安全事件处理

一次容器环境诊断把旧 root 密码带入了诊断输出；旧 root 和应用密码随后都已轮换。第一次轮换脚本存在变量引用错误，造成短暂空密码；已立即修复为随机秘密、重建专属容器并通过应用账号 `SELECT 1`、Server 健康、7/7 单测和重启持久化。后续看到的 127.0.0.1 `502` 来自 PowerShell 本机代理，而不是 StepFun（应用错误只返回 400）；使用 `-NoProxy` 的容器重启首请求直接 200。交付证据不含任何新旧秘密。

未关闭或修改 Application Control、WDAC、Code Integrity、杀毒、证书校验；未复制/重命名原生库绕过拦截。

## 本机职责边界

- 本机工作范围为 StepFun 的部署、真实数据库闭环、浏览器测试、性能与质量测量、问题修复和本地证据整理。
- 当前项目来自 ZIP，目录没有 `.git`。这不影响本报告对本机运行结果的验证。
- 正式仓库整合、代码提交、推送、提测及 GitHub 评阅由其他负责方处理，不列为本机未完成工作。本机没有执行这些操作。

## 未完成项

1. npm 5 个 high 的上游兼容版本迁移：当前无保持既有运行基线的兼容修复；已披露并给出升级方案。
2. 无缓存全新安装尚未在本机完成独立复测；已验证现有依赖、模型和构建产物下的完整流程。

当前容器与 StepFun 服务保持运行，便于立即验收；停止前必须重新核对 4317 监听进程，数据库使用 `deploy/seekdb/stop.ps1` 保留卷。
