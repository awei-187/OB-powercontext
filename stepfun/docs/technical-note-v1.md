# 浏览器端中文向量化与 seekdb 混合检索（v1 基线，保留）

当前 v2 检索实现、同条件对比与原因分析见 [检索质量报告](retrieval-quality.md)。本文及原版 PDF 作为初版基线保留，不代表当前默认融合策略。

**StepFun 赛题 · 2026-11-04 实测 · Windows 原生嵌入式方案**

模型为 [Xenova/bge-small-zh-v1.5](https://huggingface.co/Xenova/bge-small-zh-v1.5/tree/75c43b069aac4d136ba6bc1122f995fedcfd2781)，固定修订版 `75c43b069aac4d136ba6bc1122f995fedcfd2781`，基于 BAAI 中文 BGE。Transformers.js 3.8.1 / ORT Web 1.22.0-dev.20250409-89f8206ba4；CLS、L2、512 维、256 tokens，仅查询添加中文检索前缀。文档与查询均在浏览器 Worker 内计算；Node 不运行推理，集合明确关闭自动向量化，运行时无外部请求。

采用发布者提供的 FP32、FP16 和 Q8 文件；FP16 为半精度权重，Q8 发布配置为 per-channel / reduce-range / QInt8。下载固定文件并校验哈希，不训练模型；上游未披露完整转换工具链版本。权重分别 94,851,877 / 47,497,427 / 24,010,842 bytes；加上相同的三个配置与分词器文件，部署体积分别 95,292,085 / 47,937,635 / 24,451,050 bytes，压缩比 1.988x / 3.897x。

显式 `device:webgpu`，真实模型预热及设备队列完成后才宣告就绪，记录 ORT 实际适配器。不可用或初始化失败自动转 WASM；FP16 降级实际采用 FP32并显示，知识库仍要求精度匹配。Chrome 禁用 WebGPU 后实测返回 No WebGPU adapter，WASM 完成全流程。

seekdb-js 1.4.0 + 官方固定 Windows 原生绑定，内核 seekdb-v1.4.0.0。独立 Node 子进程规避原生库 stdout/后台线程问题。每库独立集合保存 ID、原文、512 维向量及 JSON 元数据，中文 IK 全文索引与 cosine/HNSW 向量索引。已取证实际执行链：SET 参数 → DBMS_HYBRID_SEARCH.GET_SQL → 数据库执行包含 MATCH、向量近邻、FULL JOIN 和 RRF 排序的 SQL；前端不融合排名。数据库操作串行，避免会话变量并发干扰。

稳定片段 ID 支持重复 upsert；增量写入先持久化 dirty，批量后显式 CALL dbms_index_manager.refresh()，成功才开放搜索。库编号随请求传递，浏览器恢复选择，数据库恢复原文与状态。Chrome/Edge 均通过 100 段导入、增量刷新、空库隔离、页面恢复与重复导入验证。

| 配置 | Recall@5 | nDCG@5 | 查询向量 ms | 数据库 ms | 端到端 ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| FP32 / WebGPU | .567 | .568 | 28.59 | 5.12 | 47.84 |
| FP16 / WebGPU | .583 | .574 | 19.14 | 4.79 | 43.58 |
| FP32 / WASM | .567 | .568 | 14.62 | 4.53 | 29.39 |
| Q8 / WASM | .583 | .575 | 10.71 | 4.93 | 24.65 |

同机 i9-12900H / 16 GiB / Chrome 157；实际 GPU 为 Intel gen-12lp，非 RTX。固定 100 段 / 12 查询 / 分级 qrels，每查询 3 遍，计时为后续 35 次中位数。自编工程回归集，召回率有限，不代表通用中文基准。一个模型串行；WASM 2 线程。FP32/FP16 GPU 冷加载 1088/728 ms、预热 769/320 ms；本地 HTTP 加载，不含首次互联网下载。

FP16 在同一已填充集合中交替顺序测量 3 次，批大小 1→4：100 段向量化中位数 1752→423 ms，导入总时间 3393→1105 ms。没有以单次最快值代替统计。原始结果和实际 SQL 在 test-results/，完整步骤见 README。未做大规模质量、NVIDIA 适配器与多用户测试；没有启动 Docker、WSL 或更改显卡设置。
