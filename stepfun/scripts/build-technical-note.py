"""Build the current one-page note from committed, historical real-run evidence.

Optional documentation dependency: reportlab. This does not run any benchmarks.
Run from stepfun; use --font for a CJK TTF/TTC on non-Windows systems.
"""
from pathlib import Path
import argparse
import hashlib
import json
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'docs/evidence/2026-11-04'


def load(name):
    return json.loads((EVIDENCE / name).read_text(encoding='utf-8-sig'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--font', default='C:/Windows/Fonts/simsun.ttc')
    parser.add_argument('--output', default=str(ROOT / 'docs/technical-note.pdf'))
    args = parser.parse_args()
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.colors import HexColor, white
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.pagesizes import A4

    for name, digest in load('SHA256.json').items():
        assert hashlib.sha256((EVIDENCE / name).read_bytes()).hexdigest() == digest, name
    quant = load('quantization.json')
    quality = load('retrieval-quality.json')
    manifest = json.loads((ROOT / 'model-manifest.json').read_text(encoding='utf-8'))
    weights = {x['path'].split('/')[-1]: x['bytes'] for x in manifest['files'] if x['path'].endswith('.onnx')}
    shared = sum(x['bytes'] for x in manifest['files'] if x['path'] in ['config.json', 'tokenizer.json', 'tokenizer_config.json'])
    sizes = {k: weights[f] + shared for k, f in [('fp32', 'model.onnx'), ('fp16', 'model_fp16.onnx'), ('q8', 'model_quantized.onnx')]}
    rows = [['配置', '部署 MB', 'R@5', 'nDCG@5', '查询向量 ms', '数据库 ms', '端到端 ms']]
    for run in quant['runs']:
        assert run['ok'] and not run['unexpectedRequests'] and not run['pageErrors']
        s = run['summary']
        rows.append([run['config']['dtype'].upper() + '/' + run['coldLoad']['backend'].upper(),
                     f"{sizes[run['config']['dtype']] / 1e6:.3f}", f"{s['recallAt5']:.3f}", f"{s['ndcgAt5']:.3f}",
                     f"{s['queryEmbeddingMedianMs']:.2f}", f"{s['searchMedianMs']:.2f}", f"{s['endToEndMedianMs']:.2f}"])
    fp16 = next(r for r in quant['runs'] if r['config']['dtype'] == 'fp16')
    batches = {x['batch']: x for x in fp16['summary']['batchComparison']}
    cases = {x['name']: x['summary'] for x in quality['cases']}
    cold = '；'.join(f"{r['config']['dtype'].upper()}/{r['coldLoad']['backend'].upper()} {r['coldLoad']['sessionLoadMs']:.0f}/{r['coldLoad']['warmupMs']:.0f}"
                    for r in quant['runs'])
    sections = [
        ('模型与量化',
         'Xenova/bge-small-zh-v1.5（BAAI中文BGE），固定修订 ' + manifest['revision'] +
         '；Transformers.js 3.8.1 / ORT Web 1.22.0-dev.20250409-89f8206ba4；CLS、L2、512维、256 tokens，仅查询加中文检索前缀。使用发布者FP16半精度及Q8（per-channel、reduce-range、QInt8）ONNX文件，全部校验哈希；不训练，上游完整转换工具链未公开。'),
        ('体积口径',
         f"单权重＋相同配置/分词器（{shared:,} bytes）；FP32/FP16/Q8为 {sizes['fp32']:,}/{sizes['fp16']:,}/{sizes['q8']:,} bytes，压缩比 {sizes['fp32']/sizes['fp16']:.3f}x/{sizes['fp32']/sizes['q8']:.3f}x。固定文件、来源与哈希见model-manifest.json。"),
        ('端侧与数据层',
         '文档与查询均由浏览器Worker推理；禁止远程模型，资源同源，Node只校验并存取向量，SDK关闭自动embedding。显式WebGPU，真实预热后显示实际后端；无适配器或初始化失败自动WASM，FP16降级实际用FP32并明示。Chrome/Edge及两种降级均已实测，运行期外部请求为0。'),
        ('当前默认检索 quality-v2',
         'seekdb-js 1.4.0，官方Windows x64绑定，内核seekdb-v1.4.0.0。每库独立集合存ID、原文、VECTOR(512)、JSON元数据；IK max_word全文索引与cosine/HNSW向量索引。单条CTE SQL在seekdb内各取50候选、归一化距离/BM25、按0.75/0.25加权FULL JOIN并排序，以ID打破同分；前端与Node不拼合两路结果。旧库保留baseline-v1/RRF，优化按钮创建副本。'),
        ('状态与刷新',
         '原生库独立子进程，数据库操作串行。稳定片段ID用于upsert；写入前持久化dirty，批量后CALL dbms_index_manager.refresh()，成功才开放查询。已验证增量导入、重复导入、切库隔离、页面恢复及服务重启后原文/向量和检索恢复。'),
    ]
    conditions = ('2026-11-04真实运行；文档整理于2026-11-08。Windows 11 / i9-12900H / 16 GiB；Chrome 157.0.8103.38、Edge 156.0.4314.58；实际GPU Intel gen-12lp。下表Chrome，当前v2，100段/12查询/每查询3次，batch=4、WASM 2线程、单模型串行；质量用全部36次，延迟为首条后35次的中位数。')
    optimization = (f"同集合交替3次，FP16 batch 1→4：100段向量化中位数 {batches[1]['embeddingMedianMs']:.0f}→{batches[4]['embeddingMedianMs']:.0f} ms，导入 {batches[1]['totalMedianMs']:.0f}→{batches[4]['totalMedianMs']:.0f} ms。另一次同条件五策略对照中，baseline→v2的R@5 {cases['baseline']['recallAt5']:.3f}→{cases['quality-v2']['recallAt5']:.3f}、nDCG {cases['baseline']['ndcgAt5']:.3f}→{cases['quality-v2']['ndcgAt5']:.3f}，端到端 {cases['baseline']['endToEndMedianMs']:.2f}→{cases['quality-v2']['endToEndMedianMs']:.2f} ms，未提速。")
    limits = ('FP16并非必然比FP32快。Q8/WASM相对FP32/WASM的R@5下降0.017；不同新建库/运行存在候选波动，不全归因于量化。12查询为自编开发回归集，非独立通用基准，不宣称显著泛化提升。冷加载为本机HTTP，不含互联网下载；未验证实验室AMD主机、无缓存全新安装或大规模多用户。')
    reproduce = ('Windows x64 / Node 24.14.x：npm ci → npm run db:download → npm run models:download → npm run build → npm start；127.0.0.1:4317。npm test / npm run test:browser / node tests/fallback.mjs / npm run benchmark；QUALITY_FRESH=1后npm run benchmark:quality。源码、下载校验、固定语料、索引与逐阶段原始数据均随仓库交付。')
    links = '模型：huggingface.co/Xenova/bge-small-zh-v1.5；SDK：github.com/oceanbase/seekdb-js；本轮原始证据：docs/evidence/2026-11-04/（SHA256.json）；完整步骤与边界见README。'
    md = ['# 浏览器本地中文知识库 · 当前 v2 一页技术说明', '', conditions, '']
    for heading, body in sections:
        md += [f'**{heading}：** {body}', '']
    md += ['| ' + ' | '.join(rows[0]) + ' |', '| ' + ' | '.join(['---'] * len(rows[0])) + ' |']
    md += ['| ' + ' | '.join(row) + ' |' for row in rows[1:]]
    md += ['', '**冷加载/首次预热（ms）：** ' + cold + '。', '', '**优化：** ' + optimization, '', '**边界：** ' + limits, '', '**复现：** ' + reproduce, '', links, '']
    (ROOT / 'docs/technical-note.md').write_text('\n'.join(md), encoding='utf-8')

    pdfmetrics.registerFont(TTFont('Song', args.font, subfontIndex=0))
    body = ParagraphStyle('body', fontName='Song', fontSize=8.7, leading=12, spaceAfter=4, wordWrap='CJK', textColor=HexColor('#223337'))
    small = ParagraphStyle('small', parent=body, fontSize=7.7, leading=10.7, textColor=HexColor('#4d6268'))
    title = ParagraphStyle('title', parent=body, fontSize=19, leading=25, spaceAfter=7)
    story = []

    def p(text, style=body):
        story.append(Paragraph(escape(text), style))

    p('OCEANBASE × STEPFUN / CURRENT QUALITY-V2', small)
    p('浏览器本地中文知识库', title)
    p(conditions, small)
    for heading, text in sections:
        p(heading + '：' + text)
    table = Table(rows, colWidths=[107, 65, 53, 53, 80, 75, 94])
    table.setStyle(TableStyle([('FONTNAME', (0, 0), (-1, -1), 'Song'), ('FONTSIZE', (0, 0), (-1, -1), 8),
                              ('BACKGROUND', (0, 0), (-1, 0), HexColor('#235e5e')), ('TEXTCOLOR', (0, 0), (-1, 0), white),
                              ('BACKGROUND', (0, 1), (-1, -1), HexColor('#eff5f3')), ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
                              ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4)]))
    story += [Spacer(1, 3), table, Spacer(1, 6)]
    p('冷加载/首次预热（ms）：' + cold + '。', small)
    p('优化：' + optimization)
    p('边界：' + limits, small)
    p('复现：' + reproduce, small)
    p(links, small)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(str(output), pagesize=A4, leftMargin=32, rightMargin=32, topMargin=26, bottomMargin=25,
                      title='StepFun 当前v2一页技术说明', author='StepFun project').build(story)
    print(output)


if __name__ == '__main__':
    main()
