import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { randomBytes, randomUUID, createHash } from 'node:crypto';
import { QUESTIONS, score, buildReversals, compareReversals, allChoices } from './core.mjs';
import { predictionRecords, tradeoffQuestion, tradeoffRecord, perspectiveQuestion, perspectiveRecord, extraComparisons } from './extras.mjs';
import { scenes, report, memoryService } from './services.mjs';

export const ROOT = path.dirname(fileURLToPath(import.meta.url));
export function readConfig(env = process.env) {
  return { mode: env.PROFILE_MODE || 'local', dataDir: env.PROFILE_DATA_DIR || path.join(ROOT, '.runtime', 'data'), deepseekURL: env.DEEPSEEK_API_URL || 'https://api.deepseek.com', deepseekKey: env.DEEPSEEK_API_KEY || '', deepseekModel: env.DEEPSEEK_MODEL || 'deepseek-flash', difyURL: env.DIFY_API_URL || '', difyKey: env.DIFY_API_KEY || '', powerURL: env.POWERCONTEXT_URL || '', powerToken: env.POWERCONTEXT_TOKEN || '' };
}
const fail = (message, status = 400) => Object.assign(Error(message), { status });
export function createApp(config) {
  if (!['local', 'deepseek', 'dify'].includes(config.mode)) throw Error('PROFILE_MODE 应为 local、deepseek 或 dify。');
  if (config.mode === 'deepseek' && !config.deepseekKey) throw Error('请在本机配置 DEEPSEEK_API_KEY。');
  if (config.mode === 'dify' && (!config.difyURL || !config.difyKey)) throw Error('请配置 DIFY_API_URL 和 DIFY_API_KEY。');
  const memory = memoryService(config), locks = new Map();
  const fileFor = sid => path.join(config.dataDir, sid + '.json');
  async function read(sid) {
    try { return JSON.parse(await fs.readFile(fileFor(sid), 'utf8')); }
    catch (e) { if (e.code === 'ENOENT') return { test: null, requests: [] }; throw fail('无法读取存档，请保留文件并检查。', 500); }
  }
  async function save(sid, record) {
    await fs.mkdir(config.dataDir, { recursive: true });
    const temp = fileFor(sid) + '.' + randomBytes(6).toString('hex') + '.tmp';
    await fs.writeFile(temp, JSON.stringify(record), { mode: 0o600 });
    await fs.rename(temp, fileFor(sid));
  }
  async function sync(sid, record) {
    const t = record.test;
    if (!memory || !t) return;
    try {
      if (!t.scopeId) { t.scopeId = await memory.scope(t.id); await save(sid, record); }
      const choices = allChoices(t);
      if (!Array.isArray(t.memoryRecords)) t.memoryRecords = [];
      while (t.synced < choices.length) {
        const written = await memory.write(t.scopeId, t.id, choices[t.synced]);
        t.memoryRecords.push(written);
        t.synced++; await save(sid, record);
      }
      t.memoryError = '';
    } catch { t.memoryError = '记忆同步尚未完成，选择已保存在本机。可以重试同步后再生成档案。'; }
    await save(sid, record);
  }
  function questionFor(t, index) {
    const base = QUESTIONS[index], saved = t.scenes?.find(item => item.questionId === base.id);
    return {
      id: base.id,
      kind: saved?.kind || base.kind,
      title: saved?.title || base.title,
      scene: saved?.scene || base.scene,
      options: Array.isArray(saved?.options) && saved.options.length === 4 ? saved.options.map(({ id, text }) => ({ id, text })) : base.options.map(({ id, text }) => ({ id, text })),
    };
  }
  function view(record) {
    const t = record.test;
    return { service: { mode: config.mode, memory: memory ? 'powercontext' : 'local' }, test: t ? {
      id: t.id, revision: t.revision, phase: t.phase, answered: t.answers.length, total: QUESTIONS.length,
      sceneSource: t.sceneSource, notice: t.notice, memoryError: t.memoryError, pendingMemory: memory ? allChoices(t).length - t.synced : 0,
      version: t.version || 1, reversalAnswered: t.reversalAnswers?.length || 0, reversalTotal: t.version >= 2 ? 2 : 0,
      predictions: t.predictions || [], tradeoffAnswered: t.tradeoffAnswers?.length || 0, perspectiveAnswered: t.perspectiveAnswers?.length || 0,
      extraAnswers: [...(t.predictions || []), ...(t.tradeoffAnswers || []), ...(t.perspectiveAnswers || [])].map(({questionId,choice}) => ({questionId,choice})),
      reversalAnswers: (t.reversalAnswers || []).map(({ questionId, choice, scene, originalChoice }) => ({ questionId, choice, scene, originalChoice })),
      answers: t.answers.map(({ questionId, choice, scene }) => ({ questionId, choice, scene })),
      question: t.phase === 'answering' ? questionFor(t, t.answers.length) : t.phase === 'reversing' ? (() => { const r = buildReversals(t.answers, t.scenes)[t.reversalAnswers.length]; return { ...r, options: r.options.map(({ id, text }) => ({ id, text })) }; })() : t.phase === 'tradeoff' ? tradeoffQuestion(t) : t.phase === 'perspective' ? perspectiveQuestion(t) : null,
      report: t.report || null,
    } : null };
  }
  async function body(req) {
    let raw = '';
    for await (const chunk of req) { raw += chunk; if (Buffer.byteLength(raw) > 12000) throw fail('提交内容过长。', 413); }
    try { return JSON.parse(raw); } catch { throw fail('提交格式不正确。'); }
  }
  function json(res, status, data) {
    res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' });
    res.end(JSON.stringify(data));
  }
  const server = http.createServer(async (req, res) => {
    try {
      const route = new URL(req.url, 'http://localhost').pathname;
      if (route.startsWith('/api/')) {
        const existing = /(?:^|;\s*)manual_session=([a-f0-9]{64})(?:;|$)/.exec(req.headers.cookie || '')?.[1];
        const sid = existing || randomBytes(32).toString('hex');
        if (!existing) res.setHeader('Set-Cookie', `manual_session=${sid}; HttpOnly; SameSite=Strict; Path=/; Max-Age=2592000`);
        if (req.method === 'GET' && route === '/api/state') return json(res, 200, view(await read(sid)));
        if (req.method !== 'POST') throw fail('接口不支持此操作。', 405);
        if (req.headers.origin && req.headers.origin !== 'http://' + req.headers.host) throw fail('请求来源不匹配。', 403);
        if (req.headers['sec-fetch-site'] === 'cross-site') throw fail('请求来源不匹配。', 403);
        if (!String(req.headers['content-type'] || '').startsWith('application/json')) throw fail('请使用 JSON 提交。', 415);
        if (!['/api/start', '/api/predict', '/api/answer', '/api/reversal', '/api/tradeoff', '/api/perspective', '/api/report', '/api/sync'].includes(route)) throw fail('接口不存在。', 404);
        const input = await body(req);
        if (typeof input.requestId !== 'string' || input.requestId.length < 8 || input.requestId.length > 100) throw fail('缺少有效的请求标识。');
        const prior = locks.get(sid) || Promise.resolve();
        const pending = prior.catch(() => {}).then(async () => {
          const record = await read(sid);
          const hash = createHash('sha256').update(JSON.stringify({ route, input })).digest('hex');
          const replay = record.requests.find(r => r.id === input.requestId);
          if (replay) { if (replay.hash !== hash) throw fail('请求标识已被其他内容使用。', 409); return view(record); }
          const t = record.test;
          if (route !== '/api/start' && (!t || input.revision !== t.revision)) throw fail('进度已变化，请刷新后继续。', 409);
          if (route === '/api/start') {
            if (t) {
              const archive = path.join(config.dataDir, 'archive'); await fs.mkdir(archive, { recursive: true });
              await fs.writeFile(path.join(archive, sid + '-' + t.id + '.json'), JSON.stringify(record), { mode: 0o600 });
            }
            const id = randomUUID(), prepared = await scenes(config, id);
            record.test = { id, version: 4, copyVersion: 3, revision: 0, phase: 'predicting', predictions: [], answers: [], reversalAnswers: [], tradeoffAnswers: [], perspectiveAnswers: [], scenes: prepared.scenes, sceneSource: prepared.source, notice: prepared.notice, synced: 0, memoryRecords: [], memoryError: '', scopeId: null, report: null };
          } else if (route === '/api/predict') {
            if (t.phase !== 'predicting') throw fail('自我预判已经记录，不能在看过题目后修改。', 409);
            try { t.predictions = predictionRecords(input.predictions); } catch (e) { throw fail(e.message); }
            t.phase = 'answering'; t.revision++;
          } else if (route === '/api/answer') {
            if (t.phase !== 'answering') throw fail('本次选择已完成。', 409);
            const q = questionFor(t, t.answers.length), option = q.options.find(o => o.id === input.optionId);
            if (input.questionId !== q.id || !option) throw fail('请选择当前题目的一个选项。');
            t.answers.push({ questionId: q.id, optionId: option.id, choice: option.text, scene: q.scene });
            t.revision++; if (t.answers.length === QUESTIONS.length) t.phase = t.version >= 2 ? 'reversing' : 'ready';
          } else if (route === '/api/reversal') {
            if (t.phase !== 'reversing') throw fail('当前没有待回答的情境反转。', 409);
            const r = buildReversals(t.answers, t.scenes)[t.reversalAnswers.length], option = r.options.find(o => o.id === input.optionId);
            if (input.questionId !== r.id || !option) throw fail('请选择当前反转题的一个选项。');
            t.reversalAnswers.push({ questionId: r.id, optionId: option.id, choice: option.text, scene: r.scene, condition: r.condition, sourceQuestionId: r.sourceQuestionId, originalChoice: r.originalChoice });
            t.revision++; if (t.reversalAnswers.length === 2) t.phase = t.version >= 3 ? 'tradeoff' : 'ready';
          } else if (route === '/api/tradeoff') {
            if (t.phase !== 'tradeoff') throw fail('当前没有待完成的取舍。', 409);
            let record; try { record = tradeoffRecord(t, input); } catch (e) { throw fail(e.message); }
            t.tradeoffAnswers.push(record); t.revision++; if (t.tradeoffAnswers.length === 2) t.phase = 'perspective';
          } else if (route === '/api/perspective') {
            if (t.phase !== 'perspective') throw fail('当前没有待完成的换位选择。', 409);
            let record; try { record = perspectiveRecord(t, input); } catch (e) { throw fail(e.message); }
            t.perspectiveAnswers.push(record); t.revision++; if (t.perspectiveAnswers.length === 2) t.phase = 'ready';
          } else if (route === '/api/report') {
            if (t.phase !== 'ready') throw fail('请先完成六项选择，已生成的档案无需重复生成。', 409);
            if (memory) { await sync(sid, record); if (t.memoryError) throw fail(t.memoryError, 503); }
            let recalled = '';
            if (memory) {
              try { recalled = await memory.recall(t.scopeId, allChoices(t)); }
              catch (e) { throw fail(e.message, 503); }
            }
            const computed = score(t.answers);
            if (t.version >= 2) computed.reversals = compareReversals(t.answers, t.reversalAnswers, t.scenes);
            if (t.version >= 3) computed.extras = extraComparisons(t);
            let narrative;
            try { narrative = await report(config, computed, recalled, t.id); }
            catch { throw fail('档案生成失败，选择已保留。请检查模型或 Dify 配置后重试。', 502); }
            t.report = { id: t.id, createdAt: new Date().toISOString(), ...computed, narrative, source: config.mode, memorySource: memory ? 'powercontext' : 'local', recalledVerified: !!memory, ...(memory ? { memoryEvidence: { bytes: Buffer.byteLength(recalled), sha256: createHash('sha256').update(recalled).digest('hex') } } : {}) };
            t.phase = 'complete'; t.revision++;
          }
          record.requests.push({ id: input.requestId, hash }); record.requests = record.requests.slice(-32);
          await save(sid, record);
          if (['/api/predict','/api/answer','/api/reversal','/api/tradeoff','/api/perspective','/api/sync'].includes(route)) await sync(sid, record);
          return view(record);
        });
        locks.set(sid, pending);
        try { json(res, 200, await pending); } finally { if (locks.get(sid) === pending) locks.delete(sid); }
        return;
      }
      const staticFiles = { '/': ['index.html', 'text/html'], '/app.js': ['app.js', 'text/javascript'], '/style.css': ['style.css', 'text/css'], '/favicon.svg': ['favicon.svg', 'image/svg+xml'] };
      const entry = staticFiles[route];
      if (req.method !== 'GET' || !entry) throw fail('页面不存在。', 404);
      const content = await fs.readFile(path.join(ROOT, 'public', entry[0]));
      res.writeHead(200, { 'Content-Type': entry[1] + '; charset=utf-8', 'Cache-Control': 'no-cache', 'X-Content-Type-Options': 'nosniff', 'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none'" });
      res.end(content);
    } catch (e) { json(res, e.status || 500, { error: e.status ? e.message : '服务暂时无法完成操作。存档已保留，请稍后重试。' }); }
  });
  return server;
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const config = readConfig();
  const host = process.env.PROFILE_HOST || '127.0.0.1', port = Number(process.env.PROFILE_PORT || 8790);
  createApp(config).listen(port, host, () => console.log(`个人使用说明书：http://${host}:${port}/ · ${config.mode}`));
}
