# 提交用实测证据

`2026-11-04/` 保存独立复测使用合成语料产生的原始 JSON，取自本机原有测试目录。2026-11-08 归档进提交材料，没有重新运行或改写历史结果。`SHA256.json` 记录各文件哈希。

- `quantization.json`：当前 quality-v2 下四组精度/后端、原始逐查询计时、加载与预热、批处理对照。
- `retrieval-quality.json`：从固定原文重新在浏览器生成向量，五策略同轮查询与质量对照。
- `independent-metrics.json`：独立重算摘要；上面两份原始结果为数值来源。
- `browser-chrome.json`、`browser-edge.json`：完整流程、增量、隔离、恢复、重复导入及运行期外部请求检查。
- `fallback.json`：无GPU适配器及模型初始化故障两条真实WASM降级路径。
- `storage-inspection.json`、`after-restart.json`：真实数据库读取与重启后检索。
- `source-and-model-audit.json`：当时前端重建比对及模型文件校验。

历史日志保留当时本机绝对路径，仅用于来源说明；复现不依赖这些路径、知识库ID、历史数据库或预计算向量。启动和复测应使用 README 的相对目录命令。固定语料与相关性标注在 `data/fixture.json`，模型获取及哈希在 `model-manifest.json` 和下载脚本中。

当前一页说明引用这批历史复测，未将旧v1数据冒充当前默认v2结果。AMD新主机及从空依赖重新安装仍待实测。完整SQL实现在 `server/retrieval.mjs`，真实执行时另生成 `test-results/hybrid-sql.jsonl`，体积较大不纳入版本控制。

重建一页说明（可选文档依赖 `reportlab`，不属于应用运行依赖）：

```powershell
python scripts/build-technical-note.py
```

非Windows环境使用 `--font` 指定支持中文的TrueType字体。脚本读取已归档结果、核验哈希并生成Markdown和PDF，不运行实验，不生成新性能数据。
