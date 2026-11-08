# 浏览器本地中文知识库 · 当前 v2 一页技术说明

2026-11-04真实运行；文档整理于2026-11-08。Windows 11 / i9-12900H / 16 GiB；Chrome 157.0.8103.38、Edge 156.0.4314.58；实际GPU Intel gen-12lp。下表Chrome，当前v2，100段/12查询/每查询3次，batch=4、WASM 2线程、单模型串行；质量用全部36次，延迟为首条后35次的中位数。

**模型与量化：** Xenova/bge-small-zh-v1.5（BAAI中文BGE），固定修订 75c43b069aac4d136ba6bc1122f995fedcfd2781；Transformers.js 3.8.1 / ORT Web 1.22.0-dev.20250409-89f8206ba4；CLS、L2、512维、256 tokens，仅查询加中文检索前缀。使用发布者FP16半精度及Q8（per-channel、reduce-range、QInt8）ONNX文件，全部校验哈希；不训练，上游完整转换工具链未公开。

**体积口径：** 单权重＋相同配置/分词器（440,208 bytes）；FP32/FP16/Q8为 95,292,085/47,937,635/24,451,050 bytes，压缩比 1.988x/3.897x。固定文件、来源与哈希见model-manifest.json。

**端侧与数据层：** 文档与查询均由浏览器Worker推理；禁止远程模型，资源同源，Node只校验并存取向量，SDK关闭自动embedding。显式WebGPU，真实预热后显示实际后端；无适配器或初始化失败自动WASM，FP16降级实际用FP32并明示。Chrome/Edge及两种降级均已实测，运行期外部请求为0。

**当前默认检索 quality-v2：** seekdb-js 1.4.0，官方Windows x64绑定，内核seekdb-v1.4.0.0。每库独立集合存ID、原文、VECTOR(512)、JSON元数据；IK max_word全文索引与cosine/HNSW向量索引。单条CTE SQL在seekdb内各取50候选、归一化距离/BM25、按0.75/0.25加权FULL JOIN并排序，以ID打破同分；前端与Node不拼合两路结果。旧库保留baseline-v1/RRF，优化按钮创建副本。

**状态与刷新：** 原生库独立子进程，数据库操作串行。稳定片段ID用于upsert；写入前持久化dirty，批量后CALL dbms_index_manager.refresh()，成功才开放查询。已验证增量导入、重复导入、切库隔离、页面恢复及服务重启后原文/向量和检索恢复。

| 配置 | 部署 MB | R@5 | nDCG@5 | 查询向量 ms | 数据库 ms | 端到端 ms |
| --- | --- | --- | --- | --- | --- | --- |
| FP32/WEBGPU | 95.292 | 0.617 | 0.599 | 21.78 | 4.27 | 46.76 |
| FP16/WEBGPU | 47.938 | 0.617 | 0.599 | 22.45 | 4.62 | 47.36 |
| FP32/WASM | 95.292 | 0.633 | 0.605 | 16.94 | 3.98 | 41.25 |
| Q8/WASM | 24.451 | 0.617 | 0.598 | 11.36 | 3.46 | 33.85 |

**冷加载/首次预热（ms）：** FP32/WEBGPU 1008/366；FP16/WEBGPU 843/358；FP32/WASM 957/61；Q8/WASM 599/73。

**优化：** 同集合交替3次，FP16 batch 1→4：100段向量化中位数 2613→657 ms，导入 4379→1594 ms。另一次同条件五策略对照中，baseline→v2的R@5 0.567→0.633、nDCG 0.568→0.605，端到端 41.29→45.14 ms，未提速。

**边界：** FP16并非必然比FP32快。Q8/WASM相对FP32/WASM的R@5下降0.017；不同新建库/运行存在候选波动，不全归因于量化。12查询为自编开发回归集，非独立通用基准，不宣称显著泛化提升。冷加载为本机HTTP，不含互联网下载；未验证实验室AMD主机、无缓存全新安装或大规模多用户。

**复现：** Windows x64 / Node 24.14.x：npm ci → npm run db:download → npm run models:download → npm run build → npm start；127.0.0.1:4317。npm test / npm run test:browser / node tests/fallback.mjs / npm run benchmark；QUALITY_FRESH=1后npm run benchmark:quality。源码、下载校验、固定语料、索引与逐阶段原始数据均随仓库交付。

模型：huggingface.co/Xenova/bge-small-zh-v1.5；SDK：github.com/oceanbase/seekdb-js；本轮原始证据：docs/evidence/2026-11-04/（SHA256.json）；完整步骤与边界见README。
