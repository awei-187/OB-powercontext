"""Build the one-page AMD + seekdb Server technical note from archived evidence."""
from pathlib import Path
import argparse
import json
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'docs/evidence/2026-11-08-amd-server'


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

    benchmark = load('benchmark.json')
    quality = load('quality.json')
    browser = load('browser.json')
    manifest = json.loads((ROOT / 'model-manifest.json').read_text(encoding='utf-8'))
    weights = {x['path'].split('/')[-1]: x['bytes'] for x in manifest['files'] if x['path'].endswith('.onnx')}
    shared = sum(x['bytes'] for x in manifest['files'] if x['path'] in ['config.json', 'tokenizer.json', 'tokenizer_config.json'])
    sizes = {key: weights[name] + shared for key, name in [
        ('fp32', 'model.onnx'), ('fp16', 'model_fp16.onnx'), ('q8', 'model_quantized.onnx')
    ]}

    rows = [['配置', '部署 MB', 'R@5', 'nDCG@5', '查询向量 ms', 'seekdb ms', '端到端 ms']]
    for run in benchmark['runs']:
        summary = run['summary']
        rows.append([
            f"{run['config']['dtype'].upper()}/{run['coldLoad']['backend'].upper()}",
            f"{sizes[run['config']['dtype']] / 1e6:.3f}",
            f"{summary['recallAt5']:.3f}", f"{summary['ndcgAt5']:.3f}",
            f"{summary['queryEmbeddingMedianMs']:.2f}", f"{summary['searchMedianMs']:.2f}",
            f"{summary['endToEndMedianMs']:.2f}",
        ])

    fp16 = next(x for x in benchmark['runs'] if x['config']['dtype'] == 'fp16')
    batches = {x['batch']: x for x in fp16['summary']['batchComparison']}
    cases = {x['name']: x['summary'] for x in quality['cases']}
    cold = '；'.join(
        f"{x['config']['dtype'].upper()}/{x['coldLoad']['backend'].upper()} "
        f"{x['coldLoad']['sessionLoadMs']:.0f}/{x['coldLoad']['warmupMs']:.0f}"
        for x in benchmark['runs']
    )
    server_version = benchmark['conditions']['database']['version'][0]['version']
    conditions = (
        '2026-11-08 AMD实验室实测；Windows 11 / Ryzen 7 7700X / 32 GiB / AMD RDNA-2；'
        'Chrome 156.0.8078.80、Edge 157.0.4341.42。下表为Chrome、100段/12查询/每查询3次、'
        'batch=4、WASM 2线程、单模型串行；延迟为预热后中位数。'
    )
    sections = [
        ('模型与量化',
         f"Xenova/bge-small-zh-v1.5，修订 {manifest['revision']}；Transformers.js 3.8.1 / ORT Web "
         '1.22.0-dev.20250409-89f8206ba4；CLS、L2、512维、256 tokens。发布者FP16及Q8 '
         '(per-channel、reduce-range、QInt8) ONNX均按清单验哈希，不训练、不调用云端推理。'),
        ('体积与质量',
         f"统一口径为权重+配置/分词器 {shared:,} bytes；FP32/FP16/Q8为 "
         f"{sizes['fp32']:,}/{sizes['fp16']:,}/{sizes['q8']:,} bytes，压缩比 "
         f"{sizes['fp32']/sizes['fp16']:.3f}x/{sizes['fp32']/sizes['q8']:.3f}x。"
         '本次小型回归集中FP16与FP32指标相同，Q8的R@5相同、nDCG高0.012；不外推为普遍提升。'),
        ('端侧运行',
         '文档和查询embedding均在浏览器Worker生成，embeddingFunction=null；模型及ORT资源同源。显式优先WebGPU，'
         '无适配器或FP16初始化失败自动降级WASM/FP32并在界面显示。Chrome、Edge和两条降级路径均完成真实数据库检索，外部推理请求为0。'),
        ('seekdb Server',
         f"seekdb-js 1.4.0连接 {server_version}；官方Docker镜像固定 "
         'oceanbase/seekdb:1.4.0-100000172026082615，仅127.0.0.1:12881，named volume挂载/var/lib/seekdb。'
         '每库独立表保存ID、原文、VECTOR(512)、JSON元数据，含IK max_word全文和cosine/HNSW向量索引。'),
        ('混合检索与状态',
         'quality-v2由一条参数化CTE SQL在seekdb内完成向量/全文候选、归一化、0.75/0.25加权、FULL JOIN与排序；'
         '客户端不拼合。稳定ID upsert；写入前持久化dirty，CALL dbms_index_manager.refresh()成功后才开放查询。'
         '100段、增量、重复upsert、空库隔离、页面恢复及容器/应用重启后持久化均通过。'),
    ]
    optimization = (
        f"FP16 batch 1->4：100段向量化中位数 {batches[1]['embeddingMedianMs']:.0f}->"
        f"{batches[4]['embeddingMedianMs']:.0f} ms，导入 {batches[1]['totalMedianMs']:.0f}->"
        f"{batches[4]['totalMedianMs']:.0f} ms。完整UI流程导入：向量 {browser['import']['embeddingMs']:.0f}、"
        f"写入 {browser['import']['writeMs']:.0f}、刷新 {browser['import']['refreshMs']:.0f}、"
        f"总计 {browser['import']['totalMs']:.0f} ms。baseline->quality-v2：R@5 "
        f"{cases['baseline']['recallAt5']:.3f}->{cases['quality-v2']['recallAt5']:.3f}，nDCG "
        f"{cases['baseline']['ndcgAt5']:.3f}->{cases['quality-v2']['ndcgAt5']:.3f}。"
    )
    limits = (
        '12查询为自编工程回归集，不是通用中文基准；冷加载为本机HTTP，不含互联网下载。未做大规模、多用户或断电事务测试。'
        'Windows原生addon受Code Integrity拒绝，本轮不绕过策略，改用获准Docker Linux Server；旧Intel结果只作历史记录。'
    )
    reproduce = (
        'deploy/seekdb/configure.ps1 -> start.ps1 -> npm ci -> npm run models:download -> npm run build -> npm start。'
        'npm run db:check:server、test:browser、fallback、benchmark、benchmark:quality；停止用deploy/seekdb/stop.ps1，保留named volume。'
    )

    md = ['# 浏览器本地中文知识库 - AMD + seekdb Server 一页技术说明', '', conditions, '']
    for heading, body in sections:
        md += [f'**{heading}：** {body}', '']
    md += ['| ' + ' | '.join(rows[0]) + ' |', '| ' + ' | '.join(['---'] * len(rows[0])) + ' |']
    md += ['| ' + ' | '.join(row) + ' |' for row in rows[1:]]
    md += ['', '**冷加载/首次预热（ms）：** ' + cold + '。', '', '**优化与完整流程：** ' + optimization,
           '', '**边界：** ' + limits, '', '**复现：** ' + reproduce, '',
           '原始证据：docs/evidence/2026-11-08-amd-server/；模型清单：model-manifest.json；完整命令与安全审计见README。', '']
    (ROOT / 'docs/technical-note.md').write_text('\n'.join(md), encoding='utf-8')

    pdfmetrics.registerFont(TTFont('Song', args.font, subfontIndex=0))
    body = ParagraphStyle('body', fontName='Song', fontSize=8.3, leading=11.2, spaceAfter=3.3,
                          wordWrap='CJK', textColor=HexColor('#223337'))
    small = ParagraphStyle('small', parent=body, fontSize=7.3, leading=9.7, textColor=HexColor('#4d6268'))
    title = ParagraphStyle('title', parent=body, fontSize=18, leading=23, spaceAfter=6)
    story = []

    def para(text, style=body):
        story.append(Paragraph(escape(text), style))

    para('OCEANBASE x STEPFUN / AMD SERVER VALIDATION', small)
    para('浏览器本地中文知识库', title)
    para(conditions, small)
    for heading, body_text in sections:
        para(heading + '：' + body_text)
    table = Table(rows, colWidths=[105, 64, 49, 54, 81, 69, 91])
    table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Song'), ('FONTSIZE', (0, 0), (-1, -1), 7.8),
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#235e5e')), ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('BACKGROUND', (0, 1), (-1, -1), HexColor('#eff5f3')), ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('TOPPADDING', (0, 0), (-1, -1), 3.5), ('BOTTOMPADDING', (0, 0), (-1, -1), 3.5),
    ]))
    story += [Spacer(1, 2), table, Spacer(1, 4)]
    para('冷加载/首次预热（ms）：' + cold + '。', small)
    para('优化与完整流程：' + optimization)
    para('边界：' + limits, small)
    para('复现：' + reproduce, small)
    para('原始证据：docs/evidence/2026-11-08-amd-server/；完整步骤、SQL与安全审计见README。', small)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(str(output), pagesize=A4, leftMargin=30, rightMargin=30, topMargin=23, bottomMargin=22,
                      title='StepFun AMD seekdb Server 一页技术说明', author='StepFun project').build(story)
    print(output)


if __name__ == '__main__':
    main()
