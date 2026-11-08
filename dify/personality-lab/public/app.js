const app = document.querySelector('#app');
let state, selected = null, picks = [], predictions = {}, previousTest = '', busy = '', previousQuestion = '';
const predictionAxes = [{id:'pace',name:'做事节奏',left:'先观察',right:'先行动'},{id:'company',name:'协作方式',left:'自己掌握',right:'一起完成'},{id:'route',name:'面对未知',left:'先有安排',right:'边走边看'}];
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const button = (label, action, cls = 'primary', disabled = false) => `<button class="${cls}" data-action="${action}" ${disabled || busy ? 'disabled' : ''}>${label}</button>`;
let toastTimer;
function toast(message) { const el = document.querySelector('#toast'); el.textContent = message; el.classList.add('visible'); clearTimeout(toastTimer); toastTimer = setTimeout(() => el.classList.remove('visible'), 4500); }
function render() {
  if (!state) return;
  const t = state.test, mode = { local: '固定题库与模板报告', deepseek: 'DeepSeek 场景与档案', dify: 'Dify 工作流' }[state.service.mode];
  document.querySelector('#service-info').textContent = `${mode}。记忆来源：${state.service.memory === 'powercontext' ? 'PowerContext（生成报告前核对初选与反转）' : '本机独立会话记录'}。` + (t?.sceneSource === 'fixed-fallback' ? '本次 AI 题面失败，已明确使用固定题库。' : '') + ' 计分是本应用的游戏规则，不是心理测量概率。';
  if (!t) {
    app.innerHTML = `<section class="hero"><div><p class="eyebrow">A SMALL STUDY OF YOUR CHOICES</p><h1>给自己，写一份<br><span class="accent">使用说明书。</span></h1><p class="intro">先猜猜自己会怎么选，再回答几个生活小问题。<br>如果条件变了，或者换成别人，你还会这样选吗？<br>最后，拿到一份附上你选过的答案的个人说明书。</p>${button(busy || '开始测试 <span>↗</span>', 'start')}<p class="micro">约 4—6 分钟 · 猜自己、做选择、看结果 · 随时回来继续</p><div class="steps"><span><b>01</b>猜猜自己</span><span><b>02</b>选一选</span><span><b>03</b>看结果</span></div></div><div class="specimen" aria-label="档案样式预览"><div class="orbit"></div><div class="orbit small"></div><div class="sample-card"><span class="sticker">PERSONAL MANUAL / 样本</span><h2>每一种选择，<br>都有自己的理由。</h2><div class="rule"></div><div class="bars"><i></i><i></i><i></i></div><p class="micro">观察 · 协作 · 探索</p></div><span class="sample-note">你的档案 / 待开启</span></div></section>`;
    if (busy) app.insertAdjacentHTML('beforeend', '<p class="busy-note">正在准备题目，稍等一会儿。</p>');
    return;
  }
  if (t.id !== previousTest) { previousTest = t.id; predictions = {}; picks = []; selected = null; }
  if (t.question?.id !== previousQuestion) { previousQuestion = t.question?.id; selected = null; picks = []; }
  if (t.phase === 'predicting') {
    app.innerHTML = `<section class="question-layout"><p class="eyebrow">BEFORE WE BEGIN / 先猜猜自己</p><div class="question-top"><span class="question-number">?</span><div class="question-content"><h1>你觉得自己通常会怎么选？</h1><p class="scene">下面三组说法，选出平时更像你的。最后看看，你实际选的和猜的一不一样。</p></div></div><div class="prediction-form">${predictionAxes.map(axis => `<section class="prediction-row"><h2>${axis.name}</h2><div class="prediction-options">${[['left',axis.left],['middle','看情况，两种都会'],['right',axis.right]].map(([id,text]) => `<button class="option ${predictions[axis.id] === id ? 'selected' : ''}" data-predict-axis="${axis.id}" data-predict-value="${id}" aria-pressed="${predictions[axis.id] === id}" ${busy ? 'disabled' : ''}>${text}</button>`).join('')}</div></section>`).join('')}</div><div class="question-bottom"><span class="micro">凭第一感觉选就好。</span>${button(busy || '选好了，开始答题 <span>→</span>', 'predict', 'primary', Object.keys(predictions).length !== 3)}</div></section>`;
  } else if (t.phase === 'tradeoff' || t.phase === 'perspective') {
    const q = t.question, trading = t.phase === 'tradeoff';
    const count = trading ? t.tradeoffAnswered : t.perspectiveAnswered;
    app.innerHTML = `<section class="question-layout"><div class="question-meta"><span>${trading ? '只能选两项' : '替别人选一次'} ${count + 1} / 2</span><span>${q.multi ? `已选 ${picks.length} / 2` : '单项选择'}</span></div><div class="question-top"><span class="question-number">${esc(q.id)}</span><div class="question-content"><h1>${esc(q.title)}</h1><p class="scene">${esc(q.scene)}</p></div></div>${q.originalChoice ? `<div class="old-choice"><span class="eyebrow">${trading ? '你刚才留下的两样' : '你给自己的选择'}</span><p>“${esc(q.originalChoice)}”</p></div>` : ''}${q.companion ? `<div class="new-condition"><span class="condition-label">如果是小周来问你</span><p>${esc(q.companion)}</p></div>` : ''}<div class="options ${trading ? 'item-options' : ''}" role="group" aria-label="${q.multi ? '选择两项' : '选择一项'}">${q.options.map(o => `<button class="option ${q.multi ? (picks.includes(o.id) ? 'selected' : '') : selected === o.id ? 'selected' : ''}" data-option="${o.id}" aria-pressed="${q.multi ? picks.includes(o.id) : selected === o.id}" ${busy ? 'disabled' : ''}>${o.symbol ? `<span class="item-symbol">${esc(o.symbol)}</span>` : `<span class="option-letter">${o.id}</span>`}<span>${esc(o.text)}${o.detail ? `<small class="item-detail">${esc(o.detail)}</small>` : ''}</span></button>`).join('')}</div><div class="question-bottom"><span class="micro">${trading ? '选你更想要的两项。' : '这次，你会怎么建议小周？'}</span>${button(busy || (trading ? (q.multi ? '就选这两项 <span>→</span>' : '这项全程保留 <span>→</span>') : count ? '选好了，看结果 <span>→</span>' : '再替小周选一次 <span>→</span>'), trading ? 'tradeoff' : 'perspective', 'primary', q.multi ? picks.length !== 2 : !selected)}</div>${t.memoryError ? `<p class="notice">${esc(t.memoryError)}</p>` : ''}</section>`;
  } else if (t.phase === 'reversing') {
    const q = t.question;
    app.innerHTML = `<section class="question-layout"><div class="question-meta"><span>换个条件 ${t.reversalAnswered + 1} / ${t.reversalTotal}</span><div class="progress">${Array.from({ length: t.reversalTotal }, (_, i) => `<i class="${i < t.reversalAnswered ? 'done' : i === t.reversalAnswered ? 'current' : ''}"></i>`).join('')}</div></div><div class="question-top"><span class="question-number">${esc(q.id)}</span><div class="question-content"><h1>${esc(q.title)}</h1><p class="micro">回到 ${esc(q.sourceQuestionId)} · 如果多知道这件事呢？</p></div></div><div class="old-choice"><span class="eyebrow">你当时的选择</span><p>“${esc(q.originalChoice)}”</p><details><summary>查看当时的场景</summary><p>${esc(q.originalScene)}</p></details></div><div class="new-condition"><span class="condition-label">新增条件</span><p>${esc(q.scene)}</p></div><div class="options reversal-options" role="group" aria-label="在新条件下再次选择">${q.options.map(o => `<button class="option ${selected === o.id ? 'selected' : ''}" data-option="${o.id}" aria-pressed="${selected === o.id}" ${busy ? 'disabled' : ''}><span class="option-letter">${o.id}</span><span>${esc(o.text)}</span></button>`).join('')}</div><div class="question-bottom"><span class="micro">现在，你会选哪项？</span>${button(busy || (t.reversalAnswered === 1 ? '继续 <span>→</span>' : '下一题 <span>→</span>'), 'reversal', 'primary', !selected)}</div>${t.memoryError ? `<p class="notice">${esc(t.memoryError)}</p>` : ''}<button class="quiet" data-action="restart" ${busy ? 'disabled' : ''}>从头再来</button></section>`;
  } else if (t.phase === 'answering') {
    const q = t.question;
    app.innerHTML = `<section class="question-layout"><div class="question-meta"><span>第 ${t.answered + 1} / ${t.total} 题 · ${esc(q.kind)}</span><div class="progress" aria-label="已完成 ${t.answered} 项">${Array.from({ length: t.total }, (_, i) => `<i class="${i < t.answered ? 'done' : i === t.answered ? 'current' : ''}"></i>`).join('')}</div></div><div class="question-top"><span class="question-number">0${t.answered + 1}</span><div class="question-content"><h1>${esc(q.title)}</h1><p class="scene">${esc(q.scene)}</p></div></div><div class="options" role="group" aria-label="选择最接近你的一项">${q.options.map(o => `<button class="option ${selected === o.id ? 'selected' : ''}" data-option="${o.id}" aria-pressed="${selected === o.id}" ${busy ? 'disabled' : ''}><span class="option-letter">${o.id}</span><span>${esc(o.text)}</span></button>`).join('')}</div><div class="question-bottom"><span class="micro">选最接近你想法的一项。</span>${button(busy || (t.answered === t.total - 1 ? (t.reversalTotal ? '再换个条件试试 <span>→</span>' : '选好了 <span>→</span>') : '下一题 <span>→</span>'), 'answer', 'primary', !selected)}</div>${t.notice ? `<p class="notice">${esc(t.notice)}</p>` : ''}${t.memoryError ? `<p class="notice">${esc(t.memoryError)}</p>` : ''}<button class="quiet" data-action="restart" ${busy ? 'disabled' : ''}>从头再来</button></section>`;
  } else if (t.phase === 'ready') {
    app.innerHTML = `<section class="ready"><p class="eyebrow">OBSERVATION COMPLETE</p><div class="seal">✓</div><h1>${t.version >= 3 ? '都选好了。' : t.reversalTotal ? '都选好了。' : '六题答完了。'}</h1><p>看看这些选择放在一起，会写成怎样一份说明书。<br>结果里会附上你选过的答案。</p>${button(busy || '查看我的说明书 <span>↗</span>', 'report')}<p class="micro">${state.service.mode === 'local' ? '当前是固定题库和模板结果。' : 'AI 正在整理你的选择，通常需要几十秒。生成失败也可以重试，答案不会丢。'}</p>${t.memoryError ? `<p class="notice">${esc(t.memoryError)}</p>${button('重试记忆同步', 'sync', 'secondary')}` : ''}<div class="answer-list">${[...t.answers, ...(t.reversalAnswers || []), ...(t.extraAnswers || [])].map(a => `<div class="answer-row"><span>${esc(a.questionId)}</span><div>${esc(a.choice)}</div></div>`).join('')}</div><button class="quiet" data-action="restart" ${busy ? 'disabled' : ''}>重新做一份</button></section>`;
  } else {
    const r = t.report, n = r.narrative;
    const list = a => `<ul>${a.map(s => `<li>${esc(s)}</li>`).join('')}</ul>`;
    app.innerHTML = `<section><div class="report-toolbar"><p class="eyebrow">YOUR PERSONAL MANUAL</p><div class="actions">${button('保存长卡片 ↓', 'save', 'secondary')}${button('打印 / PDF', 'print', 'secondary')}</div></div><article class="dossier"><div class="dossier-top"><span>档案 ${esc(r.id.slice(0, 8).toUpperCase())} / VOL. 01</span><span class="badge">${r.extras ? '你的选择记录' : r.reversals?.length ? '六项初选 · 两次反转' : '六项选择 · 一份快照'}</span></div><h1>${esc(r.title)}</h1><p class="tagline">${esc(n.tagline)}</p><p class="summary">${esc(n.summary)}</p><div class="axis-grid">${r.axes.map(a => `<div><div class="axis-name">${esc(a.name)}</div><div class="axis-track"><i class="axis-marker pos-${a.position * 2}"></i></div><div class="axis-labels"><span>${esc(a.left)}</span><span>${esc(a.right)}</span></div><div class="axis-value">本次倾向：${esc(a.tendency)}</div></div>`).join('')}</div><div class="report-grid"><section class="report-section"><h2>你比较顺手的做法</h2>${list(n.strengths)}</section><section class="report-section"><h2>有时会遇到的小麻烦</h2>${list(n.frictions)}</section></div><section class="report-section manual"><h2>建议这样与我相处</h2><ol>${n.manual.map(s => `<li>${esc(s)}</li>`).join('')}</ol></section>${extraReview(r, n)}${reversalReview(r, n)}<section class="report-section evidence"><h2>从这几道题说起</h2>${n.evidence.map(e => { const source = r.evidence.find(a => a.questionId === e.questionId); return `<div class="evidence-card"><span class="evidence-id">${esc(e.questionId)}</span><div><p class="quote">“${esc(source.choice)}”</p><p class="comment">${esc(e.comment)}</p></div></div>`; }).join('')}</section><div class="dossier-footer">${r.source === 'local' ? '固定模板档案' : r.source === 'dify' ? 'Dify 生成档案' : 'DeepSeek 生成档案'} · ${r.memorySource === 'powercontext' ? '已核对 PowerContext 初选与反转记录' : '依据本机保存的选择记录'}<br>这是一次娱乐测试，结果只根据这次的选择生成。上面的倾向条来自前六题，其他选择单独对照。</div></article><div class="report-bottom"><span class="micro">下次想试试别的选法，也可以再来。</span><div class="actions">${button('导出记录', 'json', 'secondary')}${button('再测一次 →', 'restart', 'primary')}</div></div></section>`;
  }
}
function extraReview(r, n) {
  if (!r.extras) return '';
  const e = r.extras;
  return `<section class="report-section extra-review"><h2>你猜的，和这次选的</h2><div class="prediction-table">${e.prediction.map(p => `<div class="prediction-result"><strong>${esc(p.name)}</strong><p>预想：${esc(p.predicted)}</p><p>这次：${esc(p.observed)}</p><span class="badge">${esc(p.relation)}</span></div>`).join('')}</div><p class="comment">${esc(n.extras.prediction)}</p></section><section class="report-section extra-review"><h2>你最后留下了什么</h2><div class="comparison"><div class="comparison-row"><span>先留下</span><p>${esc(e.tradeoff.initialChoice)}</p></div><div class="comparison-row"><span>全程</span><p>${esc(e.tradeoff.retained)}</p></div><div class="comparison-row"><span>半程</span><p>${esc(e.tradeoff.limited)}</p></div><p class="comparison-comment">${esc(n.extras.tradeoff)}</p></div></section><section class="report-section extra-review"><h2>同一件事，换一个人</h2><p class="comment">${esc(e.perspective.scene)}</p><div class="comparison"><p class="micro">${esc(e.perspective.companion)}</p><div class="comparison-row"><span>给自己</span><p>${esc(e.perspective.selfChoice)}</p></div><div class="comparison-row"><span>给同伴</span><p>${esc(e.perspective.otherChoice)}</p></div><span class="badge">${esc(e.perspective.relation)}</span><p class="comparison-comment">${esc(n.extras.perspective)}</p></div></section>`;
}

function reversalReview(r, n) {
  if (!r.reversals?.length) return '';
  return `<section class="report-section reversal-review"><h2>什么条件下，你会改变主意</h2><p class="micro"></p>${r.reversals.map(item => `<div class="comparison" data-source="${esc(item.sourceQuestionId)}"><div class="comparison-head"><span>${esc(item.sourceQuestionId)} → ${esc(item.id)}</span><span class="badge">${esc(item.responseType)}</span></div><div class="comparison-row"><span>原选择</span><p>${esc(item.originalChoice)}</p></div><div class="comparison-row"><span>新条件</span><p>${esc(item.condition)}</p></div><div class="comparison-row"><span>新选择</span><p>${esc(item.choice)}</p></div><p class="comparison-comment">${esc(n.reversals?.find(v => v.reversalId === item.id)?.comment || item.observation)}</p></div>`).join('')}</section>`;
}

async function request(action) {
  if (busy) return;
  const payload = { requestId: crypto.randomUUID() };
  if (state.test) payload.revision = state.test.revision;
  if (action === 'predict') payload.predictions = predictions;
  if (action === 'tradeoff') { payload.questionId = state.test.question.id; if (state.test.question.multi) payload.optionIds = picks; else payload.optionId = selected; }
  if (action === 'answer' || action === 'reversal' || action === 'perspective') { payload.questionId = state.test.question.id; payload.optionId = selected; }
  busy = action === 'start' ? '正在准备场景…' : action === 'report' ? '正在生成说明书…' : '正在保存…';
  document.querySelector('#toast').classList.remove('visible'); render();
  try {
    const response = await fetch('/api/' + action, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    const result = await response.json();
    if (!response.ok) throw Error(result.error || '暂时无法完成操作。');
    state = result;
    if (action !== 'sync') window.scrollTo({ top: 0, behavior: 'instant' });
  } catch (e) { toast(e.message || '连接中断，请刷新恢复进度。'); }
  finally { busy = ''; render(); }
}
function download(blob, filename) {
  const url = URL.createObjectURL(blob), a = document.createElement('a'); a.href = url; a.download = filename; a.click(); setTimeout(() => URL.revokeObjectURL(url), 2000);
}
function saveCard() {
  const r = state.test.report, n = r.narrative;
  const lines = [];
  const add = (text, size = 21, color = '#526357', gap = 33) => {
    const chunks = String(text).match(new RegExp('.{1,' + (size > 30 ? 19 : 32) + '}', 'gu')) || [''];
    for (const t of chunks) lines.push({ text: t, size, color, gap });
  };
  add('THE PERSONAL MANUAL / 个人使用说明书', 14, '#68776d', 45);
  add('档案 ' + r.id.slice(0, 8).toUpperCase(), 15, '#68776d', 42);
  add(r.title, 38, '#243b34', 55); add(n.tagline, 20, '#c06e48', 40); add(n.summary);
  add('你的选择倾向', 24, '#243b34', 44);
  r.axes.forEach(a => add(a.name + '：' + a.tendency));
  for (const [title, content] of [['你比较顺手的做法', n.strengths], ['有时会遇到的小麻烦', n.frictions], ['建议这样与我相处', n.manual]]) {
    add(title, 24, '#243b34', 44); content.forEach(s => add('· ' + s));
  }
  if (r.extras) {
    add('你猜的，和这次选的', 24, '#243b34', 44);
    r.extras.prediction.forEach(p => add(p.name + ' / 预想：' + p.predicted + ' / 这次：' + p.observed, 19));
    add(n.extras.prediction, 18);
    add('你最后留下了什么', 24, '#243b34', 44);
    add('先留下：' + r.extras.tradeoff.initialChoice, 19); add('全程保留：' + r.extras.tradeoff.retained, 19); add('半程保留：' + r.extras.tradeoff.limited, 19); add(n.extras.tradeoff, 18);
    add('同一件事，换一个人', 24, '#243b34', 44);
    add(r.extras.perspective.scene, 18); add(r.extras.perspective.companion, 18);
    add('我会：' + r.extras.perspective.selfChoice, 19); add('建议小周：' + r.extras.perspective.otherChoice, 19); add(n.extras.perspective, 18);
  }
  if (r.reversals?.length) {
    add('什么条件下，你会改变主意', 24, '#243b34', 44);
    r.reversals.forEach(item => { add(item.sourceQuestionId + ' → ' + item.id + ' / ' + item.responseType, 20, '#c06e48', 40); add('原选择：' + item.originalChoice, 19); add('新条件：' + item.condition, 19); add('新选择：' + item.choice, 19); add(n.reversals?.find(v => v.reversalId === item.id)?.comment || item.observation, 18, '#68776d', 30); });
  }
  add('从这几道题说起', 24, '#243b34', 44);
  n.evidence.forEach(e => { add(e.questionId + '  ' + r.evidence.find(a => a.questionId === e.questionId).choice, 19); add(e.comment, 18, '#68776d', 30); });
  add('情境偏好 · 娱乐体验 / 依据本次选择与情境条件', 14, '#68776d', 40);
  add(r.source === 'local' ? '固定模板档案' : 'AI 生成档案', 14, '#68776d', 28);
  let y = 65;
  const texts = lines.map(l => { y += l.gap; return `<text x="60" y="${y}" font-size="${l.size}" fill="${l.color}">${esc(l.text)}</text>`; }).join('');
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="800" height="${y + 65}" viewBox="0 0 800 ${y + 65}"><rect width="800" height="100%" fill="#f5f3eb"/><rect x="24" y="24" width="752" height="${y + 17}" fill="#fffefa" stroke="#c3cebe"/><g font-family="Microsoft YaHei, PingFang SC, sans-serif">${texts}</g></svg>`;
  download(new Blob([svg], { type: 'image/svg+xml;charset=utf-8' }), '个人使用说明书-' + r.id.slice(0, 8) + '.svg');
}
app.addEventListener('click', event => {
  const prediction = event.target.closest('[data-predict-axis]');
  if (prediction && !busy) { predictions[prediction.dataset.predictAxis] = prediction.dataset.predictValue; render(); return; }
  const option = event.target.closest('[data-option]');
  if (option && !busy) {
    if (state.test.phase === 'tradeoff' && state.test.question.multi) {
      const id = option.dataset.option; if (picks.includes(id)) picks = picks.filter(v => v !== id); else if (picks.length < 2) picks.push(id); else { toast('只能选两项，先取消一项再换。'); return; }
    } else selected = option.dataset.option;
    document.querySelector('#toast').classList.remove('visible'); render(); return;
  }
  const action = event.target.closest('[data-action]')?.dataset.action;
  if (!action || busy) return;
  if (action === 'restart') document.querySelector('#restart-dialog').showModal();
  else if (action === 'save') saveCard();
  else if (action === 'print') window.print();
  else if (action === 'json') download(new Blob([JSON.stringify(state.test.report, null, 2)], { type: 'application/json' }), '个人使用说明书.json');
  else request(action);
});
document.querySelector('#cancel-restart').addEventListener('click', () => document.querySelector('#restart-dialog').close());
document.querySelector('#confirm-restart').addEventListener('click', () => { document.querySelector('#restart-dialog').close(); request('start'); });
try { const response = await fetch('/api/state'); state = await response.json(); if (!response.ok) throw Error(state.error); render(); }
catch { app.innerHTML = '<section class="ready"><h1>暂时没能取出档案。</h1><p>请检查本机服务是否启动，然后刷新页面。已有进度会保留。</p></section>'; }
