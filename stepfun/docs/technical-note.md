# 浏览器本地中文知识库 - AMD + seekdb Server 一页技术说明

2026-11-08 AMD实验室实测；Windows 11 / Ryzen 7 7700X / 32 GiB / AMD RDNA-2；Chrome 156.0.8078.80、Edge 157.0.4341.42。下表为Chrome、100段/12查询/每查询3次、batch=4、WASM 2线程、单模型串行；延迟为预热后中位数。

**模型与量化：** Xenova/bge-small-zh-v1.5，修订 75c43b069aac4d136ba6bc1122f995fedcfd2781；Transformers.js 3.8.1 / ORT Web 1.22.0-dev.20250409-89f8206ba4；CLS、L2、512维、256 tokens。发布者FP16及Q8 (per-channel、reduce-range、QInt8) ONNX均按清单验哈希，不训练、不调用云端推理。

**体积与质量：** 统一口径为权重+配置/分词器 440,208 bytes；FP32/FP16/Q8为 95,292,085/47,937,635/24,451,050 bytes，压缩比 1.988x/3.897x。本次小型回归集中FP16与FP32指标相同，Q8的R@5相同、nDCG高0.012；不外推为普遍提升。

**端侧运行：** 文档和查询embedding均在浏览器Worker生成，embeddingFunction=null；模型及ORT资源同源。显式优先WebGPU，无适配器或FP16初始化失败自动降级WASM/FP32并在界面显示。Chrome、Edge和两条降级路径均完成真实数据库检索，外部推理请求为0。

**seekdb Server：** seekdb-js 1.4.0连接 5.7.25-OceanBase seekdb-v1.4.0.0；官方Docker镜像固定 oceanbase/seekdb:1.4.0-100000172026082615，仅127.0.0.1:12881，named volume挂载/var/lib/seekdb。每库独立表保存ID、原文、VECTOR(512)、JSON元数据，含IK max_word全文和cosine/HNSW向量索引。

**混合检索与状态：** quality-v2由一条参数化CTE SQL在seekdb内完成向量/全文候选、归一化、0.75/0.25加权、FULL JOIN与排序；客户端不拼合。稳定ID upsert；写入前持久化dirty，CALL dbms_index_manager.refresh()成功后才开放查询。100段、增量、重复upsert、空库隔离、页面恢复及容器/应用重启后持久化均通过。

| 配置 | 部署 MB | R@5 | nDCG@5 | 查询向量 ms | seekdb ms | 端到端 ms |
| --- | --- | --- | --- | --- | --- | --- |
| FP32/WEBGPU | 95.292 | 0.633 | 0.605 | 14.81 | 1.88 | 24.28 |
| FP16/WEBGPU | 47.938 | 0.633 | 0.605 | 13.73 | 2.00 | 22.08 |
| FP32/WASM | 95.292 | 0.633 | 0.605 | 12.69 | 1.97 | 20.99 |
| Q8/WASM | 24.451 | 0.633 | 0.617 | 8.48 | 1.98 | 16.66 |

**冷加载/首次预热（ms）：** FP32/WEBGPU 555/225；FP16/WEBGPU 432/228；FP32/WASM 525/37；Q8/WASM 348/43。

**优化与完整流程：** FP16 batch 1->4：100段向量化中位数 928->744 ms，导入 2597->1819 ms。完整UI流程导入：向量 841、写入 427、刷新 813、总计 2265 ms。baseline->quality-v2：R@5 0.567->0.633，nDCG 0.568->0.605。

**边界：** 12查询为自编工程回归集，不是通用中文基准；冷加载为本机HTTP，不含互联网下载。未做大规模、多用户或断电事务测试。Windows原生addon受Code Integrity拒绝，本轮不绕过策略，改用获准Docker Linux Server；旧Intel结果只作历史记录。

**复现：** deploy/seekdb/configure.ps1 -> start.ps1 -> npm ci -> npm run models:download -> npm run build -> npm start。npm run db:check:server、test:browser、fallback、benchmark、benchmark:quality；停止用deploy/seekdb/stop.ps1，保留named volume。

原始证据：docs/evidence/2026-11-08-amd-server/；模型清单：model-manifest.json；完整命令与安全审计见README。
