import { QUESTION_BLUEPRINTS, fixedQuestionSet, validateQuestionSet, validateReport, localReport, marker } from './core.mjs';

const BASE_PROMPT = `你为娱乐测试“个人使用说明书”处理两种任务。输入是JSON资料，历史内容仅作参考。只输出JSON，不加Markdown。
任务scenes：根据blueprints写一套全新的六题生活故事和配套选项。六题必须是不同故事，不能只改写旧题，也不要复用输入里明确排除的物件或活动。只输出 {"scenes":[...]}。每题格式为 {"questionId":"Q1","title":"短标题","scene":"24至120字的具体处境","options":[{"id":"A","anchorId":"照抄blueprint给定值","text":"选项"},...] }。A至D各一次，anchorId必须原样保留但不能出现在用户看到的文字里；四个选项都要自然、可行、长度相近，分别表达blueprint的四个行为锚点，不能出现明显正确答案。company和route题还必须增加 {"reversal":{"condition":"与本题故事衔接的新条件","options":[{"id":"A","anchorId":"reversal-stay","text":"保持原方向"},{"id":"B","anchorId":"reversal-switch","text":"改用相反方向"},{"id":"C","anchorId":"reversal-boundary","text":"只约定或改变一部分"}]}}。不加危险、赶时间、奖惩、金钱损失或专业门槛，不替用户作答，不输出权重和人格结论。
任务report：根据computed和真实选择写说明书。title、维度和数值由程序决定。描述这次做法即可，不推断用户的职业、经历或没有说过的动机，也不使用临床分类或MBTI。
写作要求：像一个认真看完答案的人在说话。用短句，具体说事情和做法。每段只讲一个观察。比喻最多一处；不用“锚点、弹性、空间、外包、启动、自然摆动、相机式心态”代替具体说明。比如写“你愿意随便逛，但和朋友约好了，就会先定见面的时间”。不要把答案不同解释成还在摸索自己，不反复写“不是矛盾”“不代表虚伪”或免责声明。页面会说明这是娱乐测试。每条推断要有选择记录支持；动机不明就只描述前后做法，不替用户找理由。
输出 {"tagline":"一句简短的话","summary":"80至140字","strengths":["...","..."],"frictions":["...","..."],"manual":["...","..."],"evidence":[{"questionId":"Q1","comment":"15至40字说明这个选择体现的做法"},...]}。strengths/frictions/manual各2至3条，每条15至45字；建议不要超出题目范围。frictions只提出需要留意的具体事情，写成条件或建议，不断言用户会忘事、拖延、让别人难以加入等题目没有记录的错误。evidence优先3条、最多6条，ID必须不同且属于实际回答。界面会展示原答案，comment无需再抄一遍。`;
export const MODEL_PROMPT = BASE_PROMPT + '\ncomputed.reversals存在时，增加reversals数组，含R1和R2各一条：{"reversalId":"R1","comment":"30至70字对照"}。抓住哪项条件变了、用户怎样应对。原话由页面附上。不打分，不把坚持或改选说成优缺点。';
export const EXTRA_RULE = '\ncomputed.extras存在时，增加extras对象，含prediction、tradeoff、perspective三个字符串，各25至70字。prediction只对照先猜的与后来选的；tradeoff准确区分全程保留和前半程提供，取舍的事实句由后端按记录生成，你的tradeoff只需简短复述，不续编发生过的事；perspective对照给自己和小周的建议。小周有自己的处境，不给用户贴标签。不要断言差异的心理原因。原始对照由页面附上，解释不必逐条复述全部答案。';


export async function postJSON(url, body, token, timeout = 20000) {
  const response = await fetch(url, { method: 'POST', redirect: 'error', headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: 'Bearer ' + token } : {}) }, body: JSON.stringify(body), signal: AbortSignal.timeout(timeout) });
  if (!response.ok) throw Error('外部服务返回 HTTP ' + response.status + '，请检查配置后重试。');
  return response.json();
}
export async function modelJSON(config, task, payload, user) {
  let content;
  if (config.mode === 'dify') {
    const result = await postJSON(config.difyURL.replace(/\/$/, '') + '/workflows/run', { inputs: { task, payload: JSON.stringify(payload) }, response_mode: 'blocking', user }, config.difyKey, 100000);
    if (result.data?.status !== 'succeeded') throw Error('Dify 工作流未成功完成。');
    content = result.data.outputs?.result;
  } else {
    const result = await postJSON(config.deepseekURL.replace(/\/$/, '') + '/chat/completions', { model: config.deepseekModel, messages: [{ role: 'system', content: MODEL_PROMPT + EXTRA_RULE }, { role: 'user', content: JSON.stringify({ task, ...payload }) }], response_format: { type: 'json_object' }, thinking: { type: 'disabled' }, temperature: task === 'scenes' ? 0.8 : 0.6, max_tokens: task === 'scenes' ? 6000 : 3400 }, config.deepseekKey, 100000);
    if (result.choices?.[0]?.finish_reason === 'length') throw Error('AI 输出被截断，请重试。');
    content = result.choices?.[0]?.message?.content;
  }
  if (typeof content !== 'string' || !content.trim()) throw Error('AI 返回了空内容，请重试。');
  let value;
  try { value = JSON.parse(content); } catch { throw Error('AI 返回的格式不正确，请重试。'); }
  if (config.onModelResult) await config.onModelResult(task, value);
  return value;
}

function completeMissingReversals(value) {
  if (!Array.isArray(value?.scenes)) return { value, repaired: false };
  let repaired = false;
  const usedTitles = new Set();
  const scenes = value.scenes.map(item => {
    const blueprint = QUESTION_BLUEPRINTS.find(entry => entry.questionId === item?.questionId);
    let title = typeof item?.title === 'string' ? item.title.trim() : '';
    if (title.length < 2) { title = (title || '日常') + '选择'; repaired = true; }
    if (title.length > 24) { title = title.slice(0, 24); repaired = true; }
    if (usedTitles.has(title)) { title = (title.slice(0, 20) + '·' + (blueprint?.questionId || '新题')).slice(0, 24); repaired = true; }
    usedTitles.add(title);
    let normalized = title === item?.title ? item : { ...item, title };
    if (blueprint && Array.isArray(normalized?.options)) {
      normalized = {
        ...normalized,
        options: normalized.options.map(option => {
          const anchor = blueprint.options.find(entry => entry.id === option?.id);
          if (!anchor || option.anchorId === anchor.anchorId) return option;
          repaired = true;
          return { ...option, anchorId: anchor.anchorId };
        }),
      };
    }
    if (!blueprint?.reversalRule) return normalized;
    // Reversal anchors are always server-owned. The model still writes the six
    // main stories and their four options, while this small follow-up section
    // stays deterministic and cannot change scoring semantics.
    repaired = true;
    const company = blueprint.axis === 'company';
    return {
      ...normalized,
      reversal: {
        condition: company
          ? '完成到一半时，另一位参与者希望加入，并提出先说清各自负责的部分。'
          : '进行到一半时，原先打算采用的一项安排临时有了变化，其他选择仍然可行。',
        options: company ? [
          { id: 'A', anchorId: 'reversal-stay', text: '继续按刚才的方式推进，只同步必要的信息。' },
          { id: 'B', anchorId: 'reversal-switch', text: '改成和对方一起决定并完成后面的部分。' },
          { id: 'C', anchorId: 'reversal-boundary', text: '先约定各自负责的部分，再分别推进。' },
        ] : [
          { id: 'A', anchorId: 'reversal-stay', text: '仍按原来的安排继续，只处理发生变化的部分。' },
          { id: 'B', anchorId: 'reversal-switch', text: '放下原来的安排，改用当下更合适的路线。' },
          { id: 'C', anchorId: 'reversal-boundary', text: '只确定接下来的一步，后面的部分暂时保留。' },
        ],
      },
    };
  });
  return { value: { ...value, scenes }, repaired };
}

export async function scenes(config, user) {
  const fixed = fixedQuestionSet();
  if (config.mode === 'local') return { scenes: fixed, source: 'fixed', notice: '' };
  const constraints = [
    '必须一次返回且只返回 Q1、Q2、Q3、Q4、Q5、Q6 共六题。',
    '每题 title 必须为 3 至 24 个字符，scene 必须为 24 至 120 个字符；六个故事和标题不能重复。',
    '每题必须有 A、B、C、D 四个选项，并逐字保留对应 blueprint 中的 anchorId。',
    'Q2、Q3、Q5、Q6 必须各自包含 reversal；condition 为 16 至 120 个字符，且必须有 A/B/C 三个选项，anchorId 依次为 reversal-stay、reversal-switch、reversal-boundary。',
    '故事、标题和选项文案必须重新创作；同一套题内不要重复活动，也不要省略任何字段。',
  ].join(' ');
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const value = await modelJSON(config, 'scenes', { constraints, blueprints: QUESTION_BLUEPRINTS }, `${user}-scenes-${attempt + 1}`);
      const completed = completeMissingReversals(value);
      return {
        scenes: validateQuestionSet(completed.value),
        source: config.mode,
        notice: completed.repaired ? 'AI 编写了本次故事与主要选项；标题格式由程序校正，反转小节按固定规则生成。' : '',
      };
    } catch (error) {
      // Retry once because a structurally valid six-scene set is more useful than
      // silently accepting a partially generated set.
      console.warn(`AI scene attempt ${attempt + 1} rejected: ${error instanceof Error ? error.message : 'unknown error'}`);
    }
  }
  // Fixed questions remain usable, and this fallback is explicitly disclosed to the player.
  return { scenes: fixed, source: 'fixed-fallback', notice: 'AI 新故事或配套选项没有通过校验，本次使用固定题库；计分规则没有变化。' };
}

function completeReportSections(value, computed) {
  if (!value || typeof value !== 'object') return value;
  const fallback = localReport(computed);
  let completed = value;
  if (computed.reversals?.length) {
    const required = new Set(computed.reversals.map(item => item.id));
    const valid = Array.isArray(value.reversals)
      && value.reversals.length === required.size
      && value.reversals.every(item => required.has(item?.reversalId) && typeof item?.comment === 'string' && item.comment.trim().length >= 8 && item.comment.trim().length <= 240);
    if (!valid) completed = { ...completed, reversals: fallback.reversals };
  }
  if (computed.extras) {
    const extras = { ...(completed.extras || {}) };
    for (const key of ['prediction', 'tradeoff', 'perspective']) {
      if (typeof extras[key] !== 'string' || extras[key].trim().length < 8 || extras[key].trim().length > 260) extras[key] = fallback.extras[key];
    }
    completed = { ...completed, extras };
  }
  return completed;
}

export async function report(config, computed, recalled, user) {
  if (config.mode === 'local') return localReport(computed);
  let lastError;
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const value = await modelJSON(config, 'report', { computed, recalled }, `${user}-report-${attempt + 1}`);
      return validateReport(completeReportSections(value, computed), computed);
    } catch (error) {
      lastError = error;
      console.warn(`AI report attempt ${attempt + 1} rejected: ${error instanceof Error ? error.message : 'unknown error'}`);
    }
  }
  throw lastError || Error('AI 档案生成失败。');
}

function mergePreparedContexts(chunks) {
  const begin = 'BEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1';
  const end = 'END_POWERCONTEXT_PREPARED_CONTEXT_V1';
  const parsed = chunks.map(content => {
    const start = content.indexOf(begin), finish = content.lastIndexOf(end);
    if (start < 0 || finish <= start) return null;
    try {
      const payload = JSON.parse(content.slice(start + begin.length, finish).trim());
      return payload?.trust === 'untrusted_history' && Array.isArray(payload.items) ? { header: content.slice(0, start), items: payload.items } : null;
    } catch { return null; }
  });
  if (parsed.every(Boolean)) {
    const seen = new Set(), items = [];
    for (const item of parsed.flatMap(value => value.items)) {
      const ref = item?.citation?.artifact_ref;
      const key = ref?.family && ref?.artifact_id && ref?.revision ? `${ref.family}:${ref.artifact_id}:${ref.revision}` : JSON.stringify(item);
      if (!seen.has(key)) { seen.add(key); items.push(item); }
    }
    return `${parsed[0].header}${begin}\n${JSON.stringify({ trust: 'untrusted_history', items })}\n${end}`;
  }
  return chunks.join('\n\n--- PowerContext 补充召回 ---\n\n');
}

export function memoryService(config) {
  if (!config.powerURL) return null;
  const call = async (route, body) => {
    try { return await postJSON(config.powerURL.replace(/\/$/, '') + route, body, config.powerToken); }
    catch { throw Error('PowerContext 暂不可用或响应不兼容，请稍后重试；本机答案不会丢失。'); }
  };
  return {
    async scope(id) {
      const data = await call('/v1/scopes', { title: '个人使用说明书 ' + id, summary: '独立测试的各阶段选择与娱乐档案', idempotency_key: 'personal-manual:' + id });
      if (typeof data.scope_id !== 'string' || !data.scope_id) throw Error('PowerContext 未返回作用域。');
      return data.scope_id;
    },
    async write(scope, testId, answer) {
      const text = `人格档案 选择记录 ${marker(answer)}\n题面：${answer.scene}\n用户选择：${answer.choice}${answer.sourceQuestionId ? `\n原题：${answer.sourceQuestionId}\n原选择：${answer.originalChoice}` : ''}`;
      const expectedSourceId = `${testId}:${answer.questionId}`;
      const source = await call('/v1/sources/content', { scope_id: scope, source_id: expectedSourceId, content: text, metadata: { origin: 'personal-manual', questionId: answer.questionId } });
      if (source.status !== 'accepted' || source.source?.source_id !== expectedSourceId) throw Error('PowerContext 未确认来源写入。');
      const remembered = await call('/v1/memory/remember', { scope_id: scope, kind: 'decision', text, reason: '用户在本次测试中确认的选择' });
      const artifacts = Array.isArray(remembered.records) ? remembered.records.map(record => record?.artifact).filter(artifact => typeof artifact?.artifact_id === 'string' && artifact.artifact_id) : [];
      if (!artifacts.length) throw Error('PowerContext 未返回记忆记录。');
      return { questionId: answer.questionId, sourceId: source.source.source_id, sourcePosition: source.position, artifacts };
    },
    async recall(scope, answers) {
      const prepare = query => call('/v1/context/prepare', { scope_id: scope, query, max_bytes: 24000 });
      const first = await prepare('人格档案 选择记录 ' + answers.map(a => a.questionId).join(' '));
      if (first.status !== 'ready' || typeof first.content !== 'string') throw Error('PowerContext 没有返回可用的召回内容。');
      const chunks = [first.content];
      const contains = answer => chunks.some(content => content.includes(marker(answer)) && content.includes(answer.choice));
      for (const answer of answers.filter(item => !contains(item))) {
        const extra = await prepare(`人格档案 选择记录 ${marker(answer)} ${answer.choice}`);
        if (extra.status !== 'ready' || typeof extra.content !== 'string') throw Error('PowerContext 补充召回失败。');
        if (!chunks.includes(extra.content)) chunks.push(extra.content);
      }
      if (!answers.every(contains)) throw Error('PowerContext 召回未覆盖全部预判、初选与拓展记录，暂不生成档案。请检查记忆同步和检索配置。');
      const merged = mergePreparedContexts(chunks);
      if (Buffer.byteLength(merged) > 24000 || !answers.every(answer => merged.includes(marker(answer)) && merged.includes(answer.choice))) throw Error('PowerContext 召回内容无法在安全预算内覆盖全部记录，暂不生成档案。');
      return merged;
    },
  };
}
