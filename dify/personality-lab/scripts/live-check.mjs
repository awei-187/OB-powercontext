import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import { createApp, readConfig, ROOT } from '../server.mjs';
if (process.env.ALLOW_LIVE_MODEL !== '1') throw Error('真实模型检查需要 ALLOW_LIVE_MODEL=1，会调用付费API。');
const output = path.join(ROOT, '.runtime', 'live'); await fs.mkdir(output, { recursive: true });
const config = { ...readConfig(), mode: 'deepseek', powerURL: '', dataDir: path.join(output, 'data'), onModelResult: async (task, value) => fs.writeFile(path.join(output, 'model-' + task + '.json'), JSON.stringify(value, null, 2)) };
const server = createApp(config); await new Promise(r => server.listen(0, '127.0.0.1', r));
const url = 'http://127.0.0.1:' + server.address().port; let cookie = '';
async function post(route, body = {}) {
  const response = await fetch(url + '/api/' + route, { method: 'POST', headers: { 'Content-Type': 'application/json', ...(cookie ? { Cookie: cookie } : {}) }, body: JSON.stringify({ requestId: crypto.randomUUID(), ...body }) });
  cookie = response.headers.get('set-cookie')?.split(';')[0] || cookie;
  const result = await response.json(); assert.equal(response.status, 200, result.error); return result.test;
}
try {
  const started = Date.now(); let t, generated = [];
  if (process.env.LIVE_RESUME === '1') {
    const files = await fs.readdir(config.dataDir);
    const records = await Promise.all(files.filter(f => /^[a-f0-9]{64}\.json$/.test(f)).map(async file => ({ file, modified: (await fs.stat(path.join(config.dataDir, file))).mtimeMs, record: JSON.parse(await fs.readFile(path.join(config.dataDir, file), 'utf8')) })));
    const latest = records.filter(x => x.record.test?.phase === 'ready').sort((a, b) => b.modified - a.modified)[0];
    if (!latest) throw Error('没有可重试的完整测试。');
    cookie = 'manual_session=' + latest.file.slice(0, -5);
    t = (await fetch(url + '/api/state', { headers: { Cookie: cookie } }).then(r => r.json())).test;
    generated = latest.record.test.scenes;
  } else t = await post('start');
  if(t.phase==='predicting') t=await post('predict',{revision:t.revision,predictions:{pace:'left',company:'middle',route:'right'}});
  assert.equal(t.sceneSource, 'deepseek', 'This check requires actual model scenes, not fallback.');
  for (const id of t.phase === 'ready' ? [] : ['C', 'A', 'D', 'B', 'B', 'D']) {
    generated.push(t.question);
    t = await post('answer', { revision: t.revision, questionId: t.question.id, optionId: id });
  }
  const reversals = [];
  while (t.phase === 'reversing') {
    reversals.push(t.question);
    t = await post('reversal', { revision: t.revision, questionId: t.question.id, optionId: t.reversalAnswered ? 'C' : 'B' });
  }
  if(t.phase==='tradeoff') {
    for(const input of [{questionId:'T1',optionIds:['A','C']},{questionId:'T2',optionId:'C'}]) t=await post('tradeoff',{revision:t.revision,...input});
  }
  if(t.phase==='perspective') {
    for(const input of [{questionId:'S1',optionId:'A'},{questionId:'S2',optionId:'C'}]) t=await post('perspective',{revision:t.revision,...input});
  }
  t = await post('report', { revision: t.revision });
  assert.equal(t.phase, 'complete'); assert.equal(t.report.source, 'deepseek'); assert.equal(t.report.narrative.evidence.length, 3);
  if (t.version >= 2) { assert.equal(t.report.reversals.length, 2); assert.equal(t.report.narrative.reversals.length, 2); }
  if(t.version>=3){assert.ok(t.report.extras);assert.ok(t.report.narrative.extras);}
  const result = { passed: true, checkedAt: new Date().toISOString(), model: config.deepseekModel, durationMs: Date.now() - started, questions: generated, reversalQuestions: reversals, report: t.report, note: 'Real DeepSeek; local session history. Does not verify real Dify or PowerContext.' };
  await fs.writeFile(path.join(output, 'results.json'), JSON.stringify(result, null, 2));
  console.log(JSON.stringify({ passed: true, model: config.deepseekModel, durationMs: result.durationMs, evidenceCount: t.report.narrative.evidence.length, reversalCount: t.report.reversals?.length || 0 }));
} finally { server.closeAllConnections(); await new Promise(r => server.close(r)); }
