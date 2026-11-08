import {readFile,writeFile} from 'node:fs/promises';
const base='test-results/retrieval-quality/',report=JSON.parse(await readFile(base+'final/comparison.json'));
const diagnosis=JSON.parse(await readFile(base+'diagnosis.json')),snapshot=JSON.parse(await readFile(base+'baseline-v1/snapshot.json'));
const baseline=report.cases.find(c=>c.name==='baseline'),best=report.cases.find(c=>c.name==='quality-v2');
const freshAudit=JSON.parse(await readFile(base+'fresh-audit.json')),fresh=JSON.parse(await readFile(base+'fresh-confirmed/comparison.json'));
const old=baseline.summary,now=best.summary;
const fmt=(x,d=3)=>Number(x).toFixed(d),pct=(a,b)=>((b-a)/a*100).toFixed(2)+'%';
function interval(metric){
  const differences=best.perQuery.map((q,i)=>q[metric]-baseline.perQuery[i][metric]),means=[];let seed=20261104;
  for(let n=0;n<10000;n++){let total=0;for(let k=0;k<12;k++){seed=(Math.imul(seed,1664525)+1013904223)>>>0;total+=differences[Math.floor(seed/4294967296*12)];}means.push(total/12);}
  means.sort((a,b)=>a-b);return {delta:differences.reduce((s,x)=>s+x,0)/12,low:means[249],high:means[9749],queryUnits:12,bootstrapSamples:10000,seed:20261104};
}
const stats={recall:interval('recall'),ndcg:interval('ndcg'),precisionAt1:interval('precisionAt1')};
const per=best.perQuery.map((q,i)=>({queryId:q.id,query:q.text,baseline:baseline.perQuery[i],optimized:q}));
const experiments=[];
for(const file of ['variants.json','variants-no-instruction.json','analyzers.json','weights.json']){
  const j=JSON.parse(await readFile(base+file));for(const r of j.runs)experiments.push({file,analyzer:r.analyzer||'ik-smart',strategy:r.strategy,...r.summary,queries:r.queries});
}
const table=report.cases.map(c=>`| ${c.name} | ${fmt(c.summary.recallAt5)} | ${fmt(c.summary.ndcgAt5)} | ${fmt(c.summary.precisionAt1)} | ${fmt(c.summary.queryEmbeddingMedianMs,2)} | ${fmt(c.summary.searchMedianMs,2)} | ${fmt(c.summary.endToEndMedianMs,2)} |`).join('\n');
const perTable=per.map(x=>`| ${x.query} | ${fmt(x.baseline.recall)} | ${fmt(x.optimized.recall)} | ${fmt(x.optimized.recall-x.baseline.recall)} | ${fmt(x.baseline.ndcg)} | ${fmt(x.optimized.ndcg)} |`).join('\n');
const explorationTable=experiments.map(e=>`| ${e.file==='variants-no-instruction.json'?'无查询前缀':'保留查询前缀'} | ${e.analyzer} | ${e.strategy} | ${fmt(e.recall)} | ${fmt(e.ndcg)} |`).join('\n');
const trace=diagnosis.rows,mean=key=>trace.reduce((s,r)=>s+r.metrics[key].recall,0)/12;
const md=`# 检索质量分析与改进（v2）

2026-11-04，同一台 Windows 11 / i9-12900H / 16 GiB 电脑。实现及测量已经完成，以下数值均来自实际 seekdb 和浏览器运行。

## 结论

默认配置由 IK smart + RRF 改为 IK max_word + 数据库内归一化分数融合（向量/全文 0.75/0.25，候选各 50）。同条件 Recall@5 **${fmt(old.recallAt5)} → ${fmt(now.recallAt5)}**（+${fmt((now.recallAt5-old.recallAt5)*100,2)} 个百分点，相对 +${pct(old.recallAt5,now.recallAt5)}）；nDCG@5 **${fmt(old.ndcgAt5)} → ${fmt(now.ndcgAt5)}**；P@1 **${fmt(old.precisionAt1)} → ${fmt(now.precisionAt1)}**。相当于 60 个相关文档机会中，Top5 命中从 35 增至 38；首条命中从 9/12 增至 10/12。

没有采用召回最高的 0.650 配置：它使用 0.5/0.5 权重，P@1 降至 0.667。默认选择三项质量指标都好于原基线的 0.75/0.25 配置，而非只挑 Recall 最高值。

## 为什么原来只有 0.583

1. **不是 HNSW 近似检索漏掉 Top5。** 12 条查询的精确向量 Top5 与近似向量 Top5 完全相同；纯向量平均 Recall@5 为 ${fmt(mean('exact'))}，全文单路为 ${fmt(mean('fts'))}。向量 Top20 已包含 56/60 个相关文档（93.3%），候选改成 50 后，原 RRF 的 Recall 仍为 0.583。
2. **RRF 忽略了分数间距，而且此实例的除法精度过粗。** 原 constant=60 下，排名第一与第二十的倒数排名差距较小；同时出现在两路的泛词命中文档会压过只在向量侧强相关的文档。Wi-Fi 查询的精确向量 Top5 全相关，而原混合结果仅有三篇相关，并引入访客停车和显卡文档。另查得 @@div_precision_increment=${freshAudit.division[0].division_digits}，1/61 实际返回 ${freshAudit.division[0].rrf_rank1}；生成 SQL 的 1/(rank+60) 出现较多同分，最终又以内部行号排序。新算法保留实际分数幅度，并以文档 ID 打破最终同分。
3. **中文分词影响词项覆盖。** 原索引实际 SHOW CREATE TABLE 为 ik_mode=smart；同样的文本与向量复制到 max_word 后，单独保持 RRF 就使 Recall 达到 0.633。不过其 nDCG/P@1 下降，因此还需要分数融合，不能只改分词器。
4. **短问句与同主题标注之间有距离。** 每个查询把该主题五篇全部算作相关，即使只问其中一个事实。GPU 查询有三篇相关文档在向量第 20 名或之后；模型难以单凭“显卡/向量化”把所有“推理后端”资料都排进 Top5。索引、GPU、导入等查询仍有明显不足。
5. **FP16 不是本轮应优先替换的因素。** 初版 FP32 基线 Recall@5 为 0.567，未优于 FP16 的 0.583。去掉 BGE 查询提示词、简单停用词过滤、降低 RRF 常数的对照均未改善总分，因此最终保留模型、提示词、池化与文档向量。

这些解释中，排名、候选覆盖、分词模式和指标均有原始记录；“泛词造成跨主题竞争”是结合原文、排名和分词/融合对照得到的工程解释，不是对所有语料的普遍结论。

## 保持不变的条件

- 100 段原文、12 条查询、相关性等级、指标定义均未变。整个 data/fixture.json SHA-256：\`${report.fixtureSha256}\`。该哈希同时覆盖文本、查询和 qrels。
- 模型修订、512 维 CLS/L2、256 tokens、查询前缀、FP16 精度、浏览器 Chrome ${report.browser}、实际 Intel gen-12lp WebGPU、seekdb 1.4.0 均相同。
- 对照库与优化副本逐项验证：100 组 ID、原文、元数据和已由浏览器生成的向量完全一致。优化副本仅改变全文索引；没有在 Node 端计算 embedding。
- 一个浏览器模型实例串行运行，每次查询重新在浏览器生成向量；每查询每配置测 3 次，共 180 次测量，配置顺序随查询与轮次轮换。每配置单独预热；表中延迟为全部 36 次测量中位数。
- 质量按 12 条不同查询统计；3 次重复用于检验稳定性与延迟，不能当成 36 条独立样本。

## 同轮实际对照

| 配置 | Recall@5 | nDCG@5 | P@1 | 查询向量 ms | 数据库 ms | 端到端 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
${table}

baseline：原 IK smart/RRF；index-only：只改 max_word；fusion-only：原 smart 索引改用分数融合；quality-v2：max_word + 0.75/0.25 分数融合（默认）；recall-priority：max_word + 0.5/0.5（未选为默认）。分数融合同时使用 50 个向量/全文候选；候选数量单独对照已证明不是收益的充分原因。

端到端 ${fmt(old.endToEndMedianMs,2)} → ${fmt(now.endToEndMedianMs,2)} ms，约 +${fmt(now.endToEndMedianMs-old.endToEndMedianMs,2)} ms，基本持平；数据库阶段变短，但未宣称整体提速。初版会话中的 43.58 ms 保留为历史记录，不与本次 30 ms 直接比较。不同会话的系统负载、GPU 频率和缓存会影响绝对延迟。

## 逐查询结果

| 固定查询 | 原 Recall@5 | 新 Recall@5 | 差值 | 原 nDCG@5 | 新 nDCG@5 |
| --- | ---: | ---: | ---: | ---: | ---: |
${perTable}

每次返回的具体 ID、三轮稳定性、计时均在 comparison.json；没有隐藏单查询下降或仅展示最好的一次。

## 从头复现与原 RRF 的同分波动

另从固定原文在浏览器重新生成 100 段文档向量、创建新库再跑完整对照。原文和文档向量与历史库逐项相同：${freshAudit.drift.changedComponents} 个向量分量变化、最大差值 ${freshAudit.drift.maxAbsoluteDifference}。会议室查询的 room-4 与 library-1 实际 RRF 分数同为 0.0305；历史库把 room-4 放在第五，新库因内部行号不同把 library-1 放在第五。这使新建库原 RRF Recall 从历史 0.583 变为 0.567。

确认复现结果：新建基线 Recall@5 ${fmt(fresh.cases[0].summary.recallAt5)}、nDCG@5 ${fmt(fresh.cases[0].summary.ndcgAt5)}；新配置仍为 ${fmt(fresh.cases[3].summary.recallAt5)} / ${fmt(fresh.cases[3].summary.ndcgAt5)}、P@1 ${fmt(fresh.cases[3].summary.precisionAt1)}。主对照使用原历史集合，仍以 0.583→0.633 报告提升，不借用较低的新库基线夸大收益。

第一次从头复现的严格“必须恰好等于历史 Recall”断言曾失败；完整失败记录仍在 fresh-reproduction/comparison.json。定位同分原因后，测试改为报告新库与历史差值，并核验数据/配置和实际结果；成功记录在 fresh-confirmed/comparison.json。没有改动任何历史结果来消除这次差异。

## 实现

- 新建库默认创建 IK max_word。旧库维持原有检索配置，点击“优化索引（保留原库）”创建独立副本并选中，不覆盖原库。复制文档、元数据和原有向量，经条数检查和索引刷新后才公布副本；失败时清理未公布的副本。
- 每路取 50 个候选。dense_score = (max(distance)-distance)/(max(distance)-min(distance))；lexical_score = BM25/max(BM25)。零分母显式处理；缺失某路的文档该路为 0。
- 最终 score = 0.75*dense_score + 0.25*lexical_score。候选、窗口归一化、FULL JOIN、融合及排序全部由 seekdb 一条 CTE SQL 执行；前端只展示最终结果。通过 seekdb-js 的 execute 接口调用，不在浏览器或 Node 中拼接两路排名。
- 原 baseline-v1 保留可调用；没有针对查询文本、文档 ID、主题前缀或相关性标注的答案映射，没有根据 qrels 注入检索特征。
- 主要源码：server/retrieval.mjs、server/db.mjs、src/app.mjs；成对测试：tests/retrieval-quality.mjs。SQL 原始记录继续写入忽略 Git 的 test-results/hybrid-sql.jsonl，含具体 strategy。

## 统计边界与下一步

按“查询”为单位的成对 bootstrap（10,000 次，固定 seed=20261104）：Recall 差值 ${fmt(stats.recall.delta)}，95% 区间 [${fmt(stats.recall.low)}, ${fmt(stats.recall.high)}]；nDCG 差值 ${fmt(stats.ndcg.delta)}，区间 [${fmt(stats.ndcg.low)}, ${fmt(stats.ndcg.high)}]。两个区间均包含 0。样本很小，且方案在同一组查询上开发选择，这不是独立测试集，也不能声称显著或可推广的中文质量提升。

仍较差的“索引/显卡/导入”查询需要新的独立评测集验证方法。后续可在另建开发集上研究查询词形/同义表达、段落上下文与更强的小型 embedding；现有测试集和标注继续冻结，本轮不加入按主题或答案硬编码的扩展规则。

## 复现

先按 README 安装、下载模型、构建，在一个窗口运行 npm start；另一个 PowerShell 窗口：

\`\`\`powershell
$env:QUALITY_FRESH='1'
npm run benchmark:quality
\`\`\`

脚本会用原文在浏览器重新生成文档向量，建立 smart/RRF 基线库，点击实际页面升级按钮得到 max_word 副本，再进行同条件对照。默认写入带时间戳的新目录，不覆盖任何历史结果。已有本次历史数据时可省略 QUALITY_FRESH，复用原基线文档向量；查询向量仍每次重新计算。

保留基线：test-results/retrieval-quality/baseline-v1/（35 份原源码/配置文件、初版 benchmark.json 和哈希快照）；本次完整对照：final/comparison.json；数据一致性：final/data-integrity.json；诊断：diagnosis.json；全部探索性结果如下。

## 所有探索性配置（包含未采用方案）

以下为数据库侧诊断，使用当次浏览器真实生成的查询向量；它们不能作为端到端延迟测试。索引试验复用完全相同的文档向量。

| 查询编码 | 全文索引 | 检索策略 | Recall@5 | nDCG@5 |
| --- | --- | --- | ---: | ---: |
${explorationTable}

官方接口依据：[seekdb-js](https://github.com/oceanbase/seekdb-js)；[BGE 模型及查询编码说明](https://huggingface.co/BAAI/bge-small-zh-v1.5)。具体效果以本项目实际 SQL 和原始结果为依据。
`;
await writeFile('docs/retrieval-quality.md',md);await writeFile(base+'final/statistics.json',JSON.stringify({stats,per,baseline:old,optimized:now},null,2));
console.log({stats,document:'docs/retrieval-quality.md'});
