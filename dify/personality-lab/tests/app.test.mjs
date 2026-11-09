import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { QUESTIONS, QUESTION_BLUEPRINTS, score, localReport, validateScenes, validateQuestionSet, validateReport, buildReversals, compareReversals } from '../core.mjs';
import { predictionRecords, tradeoffQuestion, tradeoffRecord, perspectiveQuestion, perspectiveRecord, extraComparisons } from '../extras.mjs';
import { createApp } from '../server.mjs';

const generatedStories = [
  '周日下午，你在社区书屋看到一张体验桌，上面摆着几种可以随手尝试的小工具。没有规定顺序，你会怎么开始？',
  '你准备为窗台设计一组小摆件，材料都已备好，旁边也有人愿意参与。成品没有统一标准，你会怎么推进？',
  '你来到一座第一次参观的植物园，几个展区都开放，半天内不要求全部看完。你会怎么安排这次闲逛？',
  '家里有一套没组装过的小型拼插材料，说明和零件都齐全，做坏了也能重新拼。你会怎么开始？',
  '社区要设计一块新的留言角，你可以自己拿主意，也可以邀请其他人一起讨论，几种方案都能实施。你会怎么决定？',
  '你第一次参加一个自由参观日，入口处提供了多种路线提示，基本需要已经准备好。你会怎样安排先后顺序？',
];
const generatedOptionText = {
  pace: ['先看看材料和示例，暂时不动手。', '先了解基本做法，再试一个小步骤。', '先搭出一个简单版本，边做边调整。', '直接开始尝试，遇到问题再处理。'],
  company: ['先按自己的想法独立完成。', '先自己做，需要时再问别人。', '找一个人商量分工，一起完成。', '请大家一起讨论，再共同完成。'],
  route: ['先排好完整顺序，再照着进行。', '先定一个主要目标，其他部分灵活调整。', '准备两个备选，到现场再选。', '不提前安排，按当时看到的情况行动。'],
};
function generatedQuestionSet() {
  return { scenes: QUESTION_BLUEPRINTS.map((blueprint, index) => ({
    questionId: blueprint.questionId,
    title: `本次新故事${index + 1}`,
    scene: generatedStories[index],
    options: blueprint.options.map((anchor, optionIndex) => ({ id: anchor.id, anchorId: anchor.anchorId, text: generatedOptionText[blueprint.axis][optionIndex] })),
    ...(blueprint.reversalRule ? { reversal: {
      condition: blueprint.axis === 'company' ? '另一位参与者愿意帮忙，但希望先说清各自决定的部分。' : '原先想走的顺序临时不能继续，不过还有几个同样可行的选择。',
      options: [
        { id: 'A', anchorId: 'reversal-stay', text: '仍按原来的方向处理。' },
        { id: 'B', anchorId: 'reversal-switch', text: '改用与刚才相反的做法。' },
        { id: 'C', anchorId: 'reversal-boundary', text: '只先确定一部分，其他部分保留调整。' },
      ],
    } } : {}),
  })) };
}

const listen = async s => { await new Promise(r => s.listen(0, '127.0.0.1', r)); return 'http://127.0.0.1:' + s.address().port; };
const close = async s => { s.closeAllConnections(); await new Promise(r => s.close(r)); };
async function fixture(extra = {}) {
  const dataDir = await fs.mkdtemp(path.join(os.tmpdir(), 'personal-manual-test-'));
  const config = { mode: 'local', dataDir, ...extra }, server = createApp(config), url = await listen(server);
  let cookie = '';
  async function call(route, body, headers = {}) {
    const response = await fetch(url + '/api/' + route, { method: body ? 'POST' : 'GET', headers: { ...(cookie ? { Cookie: cookie } : {}), ...(body ? { 'Content-Type': 'application/json' } : {}), ...headers }, ...(body ? { body: JSON.stringify(body) } : {}) });
    cookie = response.headers.get('set-cookie')?.split(';')[0] || cookie;
    return { status: response.status, data: await response.json() };
  }
  const post = (route, body = {}) => call(route, { requestId: crypto.randomUUID(), ...body });
  return { server, config, url, call, post, cookie: () => cookie, cleanup: async () => { if (server.listening) await close(server); await fs.rm(dataDir, { recursive: true, force: true }); } };
}
const predicted = { pace:'left', company:'middle', route:'right' };
async function begin(f) {
  const created = (await f.post('start')).data.test;
  assert.equal(created.phase, 'predicting');
  const result = await f.post('predict', { revision: created.revision, predictions: predicted });
  assert.equal(result.status, 200); return result.data.test;
}
async function finishExtras(f, current) {
  for (const input of [{ questionId:'T1', optionIds:['A','C'] }, { questionId:'T2', optionId:'C' }]) {
    const reply = await f.post('tradeoff', { revision: current.revision, ...input }); assert.equal(reply.status, 200); current = reply.data.test;
  }
  for (const input of [{ questionId:'S1', optionId:'A' }, { questionId:'S2', optionId:'C' }]) {
    const reply = await f.post('perspective', { revision: current.revision, ...input }); assert.equal(reply.status, 200); current = reply.data.test;
  }
  return current;
}
async function finish(f) {
  let current = await begin(f);
  for (const q of QUESTIONS) {
    const reply = await f.post('answer', { revision: current.revision, questionId: q.id, optionId: 'C' });
    assert.equal(reply.status, 200); current = reply.data.test;
  }
  assert.equal(current.phase, 'reversing');
  for (let i = 0; i < 2; i++) {
    const reply = await f.post('reversal', { revision: current.revision, questionId: current.question.id, optionId: i ? 'C' : 'B' });
    assert.equal(reply.status, 200); current = reply.data.test;
  }
  assert.equal(current.phase, 'tradeoff'); current = await finishExtras(f, current);
  assert.equal(current.phase, 'ready'); return current;
}
test('all 4096 answer paths keep deterministic scores and reference original option text', () => {
  for (let n = 0; n < 4096; n++) {
    const answers = QUESTIONS.map((q, i) => ({ questionId: q.id, optionId: q.options[(n >> (i * 2)) & 3].id, value: 99999 }));
    const result = score(answers);
    assert.ok(result.axes.every(a => a.raw >= -4 && a.raw <= 4 && a.position >= 0 && a.position <= 100));
    assert.equal(result.evidence.length, 6);
    assert.deepEqual(result, score(answers));
    assert.deepEqual(validateReport(localReport(result), result), localReport(result));
  }
  assert.throws(() => score([]));
});
test('model cannot add questions, omit IDs, fabricate evidence IDs or change scoring fields', () => {
  const scenes = { scenes: QUESTIONS.map(q => ({ questionId: q.id, scene: q.scene, options: ['tampered'] })) };
  const valid = validateScenes(scenes); assert.equal(valid.length, 6); assert.equal(valid[0].options, undefined);
  assert.throws(() => validateScenes({ scenes: scenes.scenes.slice(1) }));
  assert.throws(() => validateScenes({ scenes: scenes.scenes.map(() => scenes.scenes[0]) }));
  assert.throws(() => validateScenes({ scenes: scenes.scenes.map((s, i) => i ? s : { ...s, scene: s.scene + '手机快没电了。' }) }));
  const computed = score(QUESTIONS.map(q => ({ questionId: q.id, optionId: 'A' })));
  const narrative = { ...localReport(computed), axes: [{ raw: 999 }], title: 'fake' };
  assert.equal(validateReport(narrative, computed).axes, undefined);
  narrative.evidence[0].questionId = 'Q404'; assert.throws(() => validateReport(narrative, computed));
});
test('AI can create fresh stories and matching option copy without changing server-owned anchors or scores', () => {
  const payload = generatedQuestionSet(), valid = validateQuestionSet(payload);
  assert.equal(valid.length, 6); assert.equal(valid[0].title, '本次新故事1'); assert.equal(valid[0].options[2].text, generatedOptionText.pace[2]);
  assert.equal(valid[1].reversal.options.length, 3);
  const answers = valid.map((question, index) => ({ questionId: question.questionId, optionId: index % 2 ? 'D' : 'A', choice: question.options[index % 2 ? 3 : 0].text, scene: question.scene }));
  const result = score(answers); assert.deepEqual(result.axes.map(axis => axis.raw), [0, 0, 0]);
  const badAnchor = structuredClone(payload); badAnchor.scenes[0].options[0].anchorId = 'pace-start-now';
  assert.throws(() => validateQuestionSet(badAnchor));
  const repeated = structuredClone(payload); repeated.scenes[1].scene = repeated.scenes[0].scene;
  assert.throws(() => validateQuestionSet(repeated));
});
test('session, ordered selection, duplicate requests, stale updates, forged scores and restart recovery', async () => {
  const f = await fixture(); let restarted;
  try {
    assert.equal((await f.call('state')).data.test, null);
    let state = await begin(f);
    assert.equal(state.question.options[0].value, undefined);
    const input = { requestId: crypto.randomUUID(), revision: 1, questionId: 'Q1', optionId: 'D', value: -999 };
    const [a, b] = await Promise.all([f.call('answer', input), f.call('answer', input)]);
    assert.equal(a.status, 200); assert.equal(b.status, 200);
    state = (await f.call('state')).data.test; assert.equal(state.answered, 1);
    assert.equal((await f.call('answer', { ...input, optionId: 'A' })).status, 409);
    assert.equal((await f.post('answer', { revision: 0, questionId: 'Q2', optionId: 'A' })).status, 409);
    assert.equal((await f.post('answer', { revision: 2, questionId: 'Q3', optionId: 'A' })).status, 400);
    assert.equal((await f.post('report', { revision: 1 })).status, 409);
    assert.equal((await fetch(f.url + '/api/state').then(r => r.json())).test, null);
    assert.equal((await f.post('start', {})).status, 200);
    assert.equal((await f.call('start', { requestId: crypto.randomUUID() }, { Origin: 'https://other.example' })).status, 403);
    const current = await finish(f);
    const report = await f.post('report', { revision: current.revision });
    assert.equal(report.status, 200); assert.equal(report.data.test.phase, 'complete');
    assert.equal(report.data.test.report.source, 'local'); assert.equal(report.data.test.report.axes[0].raw, 2);
    await close(f.server); restarted = createApp(f.config); const url = await listen(restarted);
    const restored = await fetch(url + '/api/state', { headers: { Cookie: f.cookie() } }).then(r => r.json());
    assert.deepEqual(restored.test.report, report.data.test.report);
    assert.equal((await fetch(url + '/.env')).status, 404);
    const html = await fetch(url).then(r => r.text()); assert.ok(html.includes('个人使用说明书'));
  } finally { if (restarted) await close(restarted); await f.cleanup(); }
});

async function mockServices() {
  const scopes = new Map(), observed = []; let tamper = false, failWrite = false, invalidReport = false, partialRecall = false;
  const server = http.createServer(async (req, res) => {
    let raw = ''; for await (const c of req) raw += c; const body = JSON.parse(raw || '{}');
    observed.push({ route: req.url, body, authorized: !!req.headers.authorization });
    let value;
    if (req.url === '/v1/scopes') { const id = body.idempotency_key; if (!scopes.has(id)) scopes.set(id, new Map()); value = { scope_id: id }; }
    else if (req.url === '/v1/sources/content') {
      if (failWrite) { res.writeHead(503); res.end('{}'); return; }
      scopes.get(body.scope_id).set(body.source_id, body.content); value = { status: 'accepted', source: { name: 'content', source_id: body.source_id }, position: scopes.get(body.scope_id).size };
    } else if (req.url === '/v1/memory/remember') value = { changed: true, records: [{ artifact: { family: 'atomic-memory', artifact_id: 'art-' + observed.length, revision: 1 } }] };
    else if (req.url === '/v1/context/prepare') {
      const contents = [...scopes.get(body.scope_id).values()];
      const exactMarker = /\[[A-Z][A-Z0-9]*:[^\]]+\]/.exec(body.query)?.[0];
      value = { status: 'ready', content: tamper === 'omit-reversal' ? contents.filter(s => !s.includes('[R')).join('\n') : tamper ? 'wrong memory' : partialRecall ? (exactMarker ? contents.filter(s => s.includes(exactMarker)).join('\n') : contents.filter((_, index) => index % 2).join('\n')) : contents.join('\n') };
    }
    else if (req.url === '/v1/workflows/run') {
      const payload = JSON.parse(body.inputs.payload);
      const result = body.inputs.task === 'scenes' ? generatedQuestionSet() : invalidReport ? { summary: 'bad' } : localReport(payload.computed);
      value = { data: { status: 'succeeded', outputs: { result: JSON.stringify(result) } } };
    } else { res.writeHead(404); res.end('{}'); return; }
    res.writeHead(200, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(value));
  });
  const url = await listen(server);
  return { server, url, observed, tamper: v => { tamper = v; }, failWrite: v => { failWrite = v; }, invalidReport: v => { invalidReport = v; }, partialRecall: v => { partialRecall = v; } };
}
test('Dify and PowerContext execute full HTTP flow; recall feeds report, failure blocks fabrication and scopes stay separate', async () => {
  const mock = await mockServices();
  const config = { mode: 'dify', difyURL: mock.url + '/v1', difyKey: 'test-dify-key', powerURL: mock.url, powerToken: 'test-memory-token' };
  const f = await fixture(config), other = await fixture(config);
  try {
    let state = await finish(f); assert.equal(state.sceneSource, 'dify'); assert.equal(state.pendingMemory, 0);
    mock.tamper(true);
    let result = await f.post('report', { revision: state.revision }); assert.equal(result.status, 503);
    assert.equal((await f.call('state')).data.test.phase, 'ready');
    mock.tamper('omit-reversal');
    assert.equal((await f.post('report', { revision: state.revision })).status, 503);
    mock.tamper(false); mock.invalidReport(true);
    assert.equal((await f.post('report', { revision: state.revision })).status, 502);
    mock.invalidReport(false);
    result = await f.post('report', { revision: state.revision }); assert.equal(result.status, 200);
    assert.equal(result.data.test.report.recalledVerified, true); assert.equal(result.data.test.report.source, 'dify');
    const requests = mock.observed.filter(x => x.route === '/v1/workflows/run' && x.body.inputs.task === 'report');
    const payload = JSON.parse(requests.at(-1).body.inputs.payload); assert.ok(payload.recalled.includes('[Q1:C]')); assert.ok(payload.recalled.includes('[R1:B]')); assert.ok(payload.recalled.includes('[R2:C]')); assert.equal(payload.computed.reversals.length, 2); assert.ok(payload.recalled.includes('[T1:AC]')); assert.ok(payload.recalled.includes('[S2:C]')); assert.ok(payload.computed.extras); assert.ok(payload.recalled.includes(generatedOptionText.pace[2]));
    assert.ok(mock.observed.every(x => x.authorized));
    await finish(other); assert.equal(mock.observed.filter(x => x.route === '/v1/scopes').length, 2);
    assert.equal(mock.observed.filter(x => x.route === '/v1/sources/content').length, 30);
    assert.ok(!JSON.stringify(result.data).includes('test-dify-key')); assert.ok(!JSON.stringify(result.data).includes('test-memory-token'));
  } finally { await f.cleanup(); await other.cleanup(); await close(mock.server); }
});
test('memory write failure preserves answer; explicit sync recovers without answering twice', async () => {
  const mock = await mockServices(), f = await fixture({ powerURL: mock.url, powerToken: 'test-memory-token' });
  try {
    await begin(f); mock.failWrite(true);
    let state = (await f.post('answer', { revision: 1, questionId: 'Q1', optionId: 'A' })).data.test;
    assert.equal(state.answered, 1); assert.equal(state.pendingMemory, 1); assert.ok(state.memoryError);
    mock.failWrite(false);
    state = (await f.post('sync', { revision: state.revision })).data.test;
    assert.equal(state.answered, 1); assert.equal(state.pendingMemory, 0); assert.equal(state.memoryError, '');
  } finally { await f.cleanup(); await close(mock.server); }
});

test('partial PowerContext preparation is supplemented per missing record and stores real record IDs', async () => {
  const mock = await mockServices(), f = await fixture({ mode: 'dify', difyURL: mock.url + '/v1', difyKey: 'test-dify-key', powerURL: mock.url, powerToken: 'test-memory-token' });
  try {
    const ready = await finish(f); mock.partialRecall(true);
    const result = await f.post('report', { revision: ready.revision });
    assert.equal(result.status, 200); assert.equal(result.data.test.report.recalledVerified, true); assert.ok(result.data.test.report.memoryEvidence.bytes > 0); assert.equal(result.data.test.report.memoryEvidence.sha256.length, 64);
    const prepares = mock.observed.filter(entry => entry.route === '/v1/context/prepare');
    assert.ok(prepares.length > 1); assert.ok(prepares.some(entry => entry.body.query.includes('[P1:')));
    const sid = f.cookie().split('=')[1], saved = JSON.parse(await fs.readFile(path.join(f.config.dataDir, sid + '.json'), 'utf8'));
    assert.equal(saved.test.memoryRecords.length, 15);
    assert.ok(saved.test.memoryRecords.every(record => record.sourceId && record.artifacts[0]?.artifact_id));
  } finally { await f.cleanup(); await close(mock.server); }
});
test('AI scene failure is labeled fallback; report failure stays retryable and never claims local output as AI', async () => {
  const f = await fixture({ mode: 'deepseek', deepseekURL: 'http://127.0.0.1:1', deepseekKey: 'test-key', deepseekModel: 'test-model' });
  try {
    const ready = await finish(f); assert.equal(ready.sceneSource, 'fixed-fallback'); assert.ok(ready.notice);
    assert.equal((await f.post('report', { revision: ready.revision })).status, 502);
    const saved = (await f.call('state')).data.test; assert.equal(saved.phase, 'ready'); assert.equal(saved.report, null);
  } finally { await f.cleanup(); }
});


test('every initial path selects real source evidence; all 36864 reversal paths preserve scores and generate two comparisons', () => {
  for (let n = 0; n < 4096; n++) {
    const answers = QUESTIONS.map((q, i) => ({ questionId: q.id, optionId: q.options[(n >> (i * 2)) & 3].id }));
    const base = score(answers), plan = buildReversals(answers);
    assert.equal(new Set(plan.map(p => p.sourceQuestionId)).size, 2);
    for (const r of plan) {
      assert.equal(r.originalChoice, base.evidence.find(e => e.questionId === r.sourceQuestionId).choice);
      assert.equal(r.options.length, 3); assert.ok(r.options.every(o => o.value === undefined));
    }
    for (let k = 0; k < 9; k++) {
      const records = plan.map((r, i) => ({ questionId: r.id, optionId: ['A','B','C'][i ? Math.floor(k / 3) : k % 3], value: 999 }));
      const reversals = compareReversals(answers, records);
      const computed = { ...base, reversals };
      const narrative = localReport(computed);
      assert.equal(validateReport(narrative, computed).reversals.length, 2);
      assert.equal(reversals.length, 2);
    }
    assert.deepEqual(score(answers), base);
  }
});

test('reversal cannot be skipped, reordered, overwritten or used to alter earlier scores; reload restores mid-reversal', async () => {
  const f = await fixture(); let restarted;
  try {
    let current = await begin(f);
    assert.equal((await f.post('reversal', { revision: 0, questionId: 'R1', optionId: 'A' })).status, 409);
    for (const q of QUESTIONS) current = (await f.post('answer', { revision: current.revision, questionId: q.id, optionId: 'D' })).data.test;
    assert.equal(current.phase, 'reversing'); assert.equal(current.question.originalChoice, QUESTIONS[1].options[3].text);
    assert.equal((await f.post('report', { revision: current.revision })).status, 409);
    assert.equal((await f.post('reversal', { revision: current.revision, questionId: 'R2', optionId: 'A' })).status, 400);
    const input = { requestId: crypto.randomUUID(), revision: current.revision, questionId: 'R1', optionId: 'B', originalChoice: 'forged', score: 999 };
    const replies = await Promise.all([f.call('reversal', input), f.call('reversal', input)]);
    assert.ok(replies.every(r => r.status === 200));
    current = (await f.call('state')).data.test; assert.equal(current.reversalAnswered, 1); assert.equal(current.question.id, 'R2');
    await close(f.server); restarted = createApp(f.config); const url = await listen(restarted);
    const restored = (await fetch(url + '/api/state', { headers: { Cookie: f.cookie() } }).then(r => r.json())).test;
    assert.equal(restored.question.id, 'R2'); assert.equal(restored.reversalAnswered, 1);
    async function post(route, body) { return fetch(url + '/api/' + route, { method: 'POST', headers: { Cookie: f.cookie(), 'Content-Type': 'application/json' }, body: JSON.stringify({ requestId: crypto.randomUUID(), ...body }) }).then(async r => ({ status: r.status, data: await r.json() })); }
    assert.equal((await post('report', { revision: current.revision })).status, 409);
    current = (await post('reversal', { revision: current.revision, questionId: 'R2', optionId: 'C' })).data.test;
    current = await finishExtras({post}, current);
    const result = await post('report', { revision: current.revision }); assert.equal(result.status, 200);
    const report = result.data.test.report;
    assert.ok(report.axes.every(a => a.raw === 4)); assert.equal(report.reversals[0].responseType, '这次换了做法');
    assert.equal(report.reversals[0].originalChoice, QUESTIONS[1].options[3].text);
    assert.equal(report.reversals[1].responseType, '先约定一部分'); assert.equal(report.narrative.reversals.length, 2);
  } finally { if (restarted) await close(restarted); await f.cleanup(); }
});

test('version-one saved tests remain readable and completable without silently resetting progress', async () => {
  const f = await fixture();
  try {
    await f.call('state'); const sid = f.cookie().split('=')[1];
    const answers = QUESTIONS.map(q => ({ questionId: q.id, optionId: 'A', choice: q.options[0].text, scene: q.scene }));
    const record = { requests: [], test: { id: crypto.randomUUID(), phase: 'ready', revision: 6, answers, scenes: QUESTIONS.map(q => ({ questionId:q.id, scene:q.scene })), synced: 0, scopeId: null, memoryError: '', sceneSource:'fixed', notice:'' } };
    await fs.writeFile(path.join(f.config.dataDir, sid + '.json'), JSON.stringify(record));
    const existing = (await f.call('state')).data.test; assert.equal(existing.version, 1); assert.equal(existing.phase, 'ready');
    const result = await f.post('report', { revision: 6 }); assert.equal(result.status, 200); assert.equal(result.data.test.report.reversals, undefined);
    const fresh = (await f.post('start')).data.test; assert.equal(fresh.version, 4); assert.equal(fresh.answered, 0);
  } finally { await f.cleanup(); }
});


test('valid extra model entries are bounded for display; every returned evidence ID is validated before trimming', () => {
  const computed = score(QUESTIONS.map(q => ({ questionId: q.id, optionId: 'A' })));
  const narrative = localReport(computed);
  narrative.manual.push('补充一条有效的相处建议。');
  narrative.evidence = computed.evidence.map(e => ({ questionId: e.questionId, comment: '这条解释引用了实际选择。' }));
  const normalized = validateReport(narrative, computed); assert.equal(normalized.manual.length, 3); assert.equal(normalized.evidence.length, 3);
  narrative.evidence[5].questionId = 'Q404'; assert.throws(() => validateReport(narrative, computed));
  const answers = QUESTIONS.map(q => ({ questionId: q.id, optionId: 'A' }));
  const reversals = compareReversals(answers, buildReversals(answers).map(r => ({ questionId:r.id, optionId:'B' })));
  const withReversals = { ...computed, reversals }; const report = localReport(withReversals);
  report.reversals[1].reversalId = 'R404'; assert.throws(() => validateReport(report, withReversals));
});


test('prediction choices are complete, validated and compared to initial scores without changing them', () => {
  assert.throws(()=>predictionRecords({pace:'left'})); assert.throws(()=>predictionRecords({...predicted,route:'invalid'}));
  const answers=QUESTIONS.map(q=>({questionId:q.id,optionId:'D'}));
  const records=predictionRecords(predicted); assert.equal(records.length,3); assert.equal(records[0].questionId,'P1');
  for (const pair of [['A','B'],['A','C'],['A','D'],['B','C'],['B','D'],['C','D']]) {
    for(const keep of pair) for(const self of ['A','B','C','D']) for(const other of ['A','B','C','D']) {
      const t={answers,predictions:records,tradeoffAnswers:[],perspectiveAnswers:[]};
      t.tradeoffAnswers.push(tradeoffRecord(t,{questionId:'T1',optionIds:[...pair].reverse()}));
      assert.deepEqual(t.tradeoffAnswers[0].optionIds,pair);
      assert.deepEqual(tradeoffQuestion(t).options.map(o=>o.id),pair);
      t.tradeoffAnswers.push(tradeoffRecord(t,{questionId:'T2',optionId:keep}));
      t.perspectiveAnswers.push(perspectiveRecord(t,{questionId:'S1',optionId:self}));
      const before=perspectiveQuestion(t); assert.ok(before.companion); assert.equal(before.originalChoice,t.perspectiveAnswers[0].choice);
      t.perspectiveAnswers.push(perspectiveRecord(t,{questionId:'S2',optionId:other}));
      const extras=extraComparisons(t); const computed={...score(answers),extras};
      assert.equal(extras.prediction[0].relation,'和猜的不一样'); assert.equal(extras.prediction[2].relation,'和猜的一样');
      assert.equal(validateReport(localReport(computed),computed).extras.tradeoff.includes(extras.tradeoff.retained),true);
      assert.ok(computed.axes.every(a=>a.raw===4));
    }
  }
});

test('extras enforce two distinct selections, subset retention, self-before-other, and server-owned originals', async () => {
  const f=await fixture(); let restarted;
  try {
    let current=(await f.post('start')).data.test;
    assert.equal((await f.post('answer',{revision:0,questionId:'Q1',optionId:'A'})).status,409);
    assert.equal((await f.post('predict',{revision:0,predictions:{pace:'left'}})).status,400);
    const input={requestId:crypto.randomUUID(),revision:0,predictions:predicted};
    assert.ok((await Promise.all([f.call('predict',input),f.call('predict',input)])).every(r=>r.status===200));
    current=(await f.call('state')).data.test; assert.equal(current.predictions.length,3);
    assert.equal((await f.post('predict',{revision:current.revision,predictions:predicted})).status,409);
    for(const q of QUESTIONS) current=(await f.post('answer',{revision:current.revision,questionId:q.id,optionId:'A'})).data.test;
    for(const id of ['R1','R2']) current=(await f.post('reversal',{revision:current.revision,questionId:id,optionId:'A'})).data.test;
    assert.equal((await f.post('report',{revision:current.revision})).status,409);
    for(const ids of [['A'],['A','A'],['A','B','C'],['A','X']]) assert.equal((await f.post('tradeoff',{revision:current.revision,questionId:'T1',optionIds:ids})).status,400);
    current=(await f.post('tradeoff',{revision:current.revision,questionId:'T1',optionIds:['D','B']})).data.test;
    assert.equal(current.question.id,'T2'); assert.equal(current.question.options.length,2);
    assert.equal((await f.post('tradeoff',{revision:current.revision,questionId:'T2',optionId:'A'})).status,400);
    await close(f.server); restarted=createApp(f.config); const url=await listen(restarted);
    async function post(route,body){return fetch(url+'/api/'+route,{method:'POST',headers:{Cookie:f.cookie(),'Content-Type':'application/json'},body:JSON.stringify({requestId:crypto.randomUUID(),...body})}).then(async r=>({status:r.status,data:await r.json()}));}
    current=(await fetch(url+'/api/state',{headers:{Cookie:f.cookie()}}).then(r=>r.json())).test;
    assert.equal(current.question.id,'T2'); assert.deepEqual(current.question.options.map(o=>o.id),['B','D']);
    current=(await post('tradeoff',{revision:current.revision,questionId:'T2',optionId:'D'})).data.test;
    assert.equal((await post('perspective',{revision:current.revision,questionId:'S2',optionId:'B'})).status,400);
    current=(await post('perspective',{revision:current.revision,questionId:'S1',optionId:'A'})).data.test;
    assert.ok(current.question.originalChoice.includes('自己'));
    const last={requestId:crypto.randomUUID(),revision:current.revision,questionId:'S2',optionId:'D'};
    // A retry uses the same request ID and may not append a second choice.
    const submit=()=>fetch(url+'/api/perspective',{method:'POST',headers:{Cookie:f.cookie(),'Content-Type':'application/json'},body:JSON.stringify(last)}).then(r=>r.json());
    await Promise.all([submit(),submit()]);
    current=(await fetch(url+'/api/state',{headers:{Cookie:f.cookie()}}).then(r=>r.json())).test;
    assert.equal(current.perspectiveAnswered,2); assert.equal(current.phase,'ready');
    const result=await post('report',{revision:current.revision}); assert.equal(result.status,200);
    assert.equal(result.data.test.report.extras.tradeoff.retained,'有安静的休息点');
    assert.equal(result.data.test.report.extras.perspective.relation,'选法不一样');
    assert.ok(result.data.test.report.axes.every(a=>a.raw===-4));
  } finally {if(restarted) await close(restarted);await f.cleanup();}
});


test('scene guard distinguishes explicit absence of pressure from added pressure', () => {
  const base=QUESTIONS.map(q=>({questionId:q.id,scene:q.scene}));
  assert.equal(validateScenes({scenes:base.map((s,i)=>i?s:{...s,scene:s.scene+'没有人催促你。'})}).length,6);
  assert.throws(()=>validateScenes({scenes:base.map((s,i)=>i?s:{...s,scene:s.scene+'有人催促你。'})}));
});


test('version-two saves finish reversal and report without being forced through new extras', async () => {
  const f=await fixture();
  try {
    await f.call('state');const sid=f.cookie().split('=')[1];
    const answers=QUESTIONS.map(q=>({questionId:q.id,optionId:'B',choice:q.options[1].text,scene:q.scene}));
    const record={requests:[],test:{id:crypto.randomUUID(),version:2,phase:'reversing',revision:6,answers,reversalAnswers:[],scenes:QUESTIONS.map(q=>({questionId:q.id,scene:q.scene})),synced:0,memoryError:'',sceneSource:'fixed',notice:''}};
    await fs.writeFile(path.join(f.config.dataDir,sid+'.json'),JSON.stringify(record));
    let current=(await f.call('state')).data.test;assert.equal(current.version,2);
    for(const id of ['R1','R2'])current=(await f.post('reversal',{revision:current.revision,questionId:id,optionId:'B'})).data.test;
    assert.equal(current.phase,'ready');
    const result=await f.post('report',{revision:current.revision});assert.equal(result.status,200);assert.equal(result.data.test.report.extras,undefined);assert.equal(result.data.test.report.reversals.length,2);
  } finally {await f.cleanup();}
});


test('copy updates preserve original answer, reversal, card and perspective wording from saved records', () => {
  const answers=QUESTIONS.map(q=>({questionId:q.id,optionId:'A',scene:q.scene,choice:q.options[0].text}));
  answers[1].choice='一本空白笔记本：独自把想法画出来。';
  assert.equal(score(answers).evidence[1].choice,answers[1].choice);
  const plan=buildReversals(answers);
  const oldReverse=plan.map(r=>({questionId:r.id,optionId:'B',scene:'过去的新条件。你现在会怎样选择？',choice:'过去记录的新选择。',originalChoice:r.originalChoice}));
  const compared=compareReversals(answers,oldReverse);assert.equal(compared[0].choice,'过去记录的新选择。');assert.equal(compared[0].condition,'过去的新条件。');
  const t={answers,predictions:predictionRecords(predicted),tradeoffAnswers:[{questionId:'T1',optionId:'AC',optionIds:['A','C'],scene:'旧题',choice:'提前知道全部路线 ＋ 随时改变目的地'}],perspectiveAnswers:[]};
  assert.deepEqual(tradeoffQuestion(t).options.map(o=>o.text),['提前知道全部路线','随时改变目的地']);
  t.tradeoffAnswers.push(tradeoffRecord(t,{questionId:'T2',optionId:'C'}));
  t.perspectiveAnswers=[{questionId:'S1',optionId:'A',scene:'旧海报场景',choice:'旧的自己选择'},{questionId:'S2',optionId:'B',scene:'旧海报场景\n旧的小周背景',choice:'旧的同伴选择'}];
  const old=extraComparisons(t);assert.equal(old.tradeoff.retained,'随时改变目的地');assert.equal(old.perspective.scene,'旧海报场景');assert.equal(old.perspective.companion,'旧的小周背景');
  const fresh={copyVersion:2,tradeoffAnswers:[]};
  fresh.tradeoffAnswers.push(tradeoffRecord(fresh,{questionId:'T1',optionIds:['A','C']}));
  assert.deepEqual(fresh.tradeoffAnswers[0].cards.map(c=>c.text),['有人帮你安排路线','可以临时换地方']);
});


test('tradeoff narration follows recorded full/half availability instead of model-invented later events', () => {
  const t={copyVersion:2,answers:QUESTIONS.map(q=>({questionId:q.id,optionId:'A'})),predictions:predictionRecords(predicted),tradeoffAnswers:[],perspectiveAnswers:[]};
  t.tradeoffAnswers.push(tradeoffRecord(t,{questionId:'T1',optionIds:['A','C']}));t.tradeoffAnswers.push(tradeoffRecord(t,{questionId:'T2',optionId:'C'}));
  t.perspectiveAnswers.push(perspectiveRecord(t,{questionId:'S1',optionId:'A'}));t.perspectiveAnswers.push(perspectiveRecord(t,{questionId:'S2',optionId:'B'}));
  const computed={...score(t.answers),extras:extraComparisons(t)};
  const model=localReport(computed);model.extras.tradeoff='用户后来完全放弃了另一项。';
  const actual=validateReport(model,computed).extras.tradeoff;
  assert.ok(actual.includes('仍在前半程提供'));assert.ok(actual.includes('有人帮你安排路线'));assert.ok(!actual.includes('完全放弃'));
});
