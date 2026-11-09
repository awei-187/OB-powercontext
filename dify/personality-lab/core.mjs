export const AXES = [
  { id: 'pace', name: '做事节奏', left: '先观察', right: '先行动' },
  { id: 'company', name: '协作方式', left: '自己掌握', right: '一起完成' },
  { id: 'route', name: '面对未知', left: '先有安排', right: '边走边看' },
];

// Scores and option meanings are authored here, never supplied by the model/browser.
export const QUESTIONS = [
  { id: 'Q1', axis: 'pace', kind: '场景', title: '先迈出哪一步', scene: '你比约定提前一小时到了一个陌生街区。朋友暂时联系不上，附近有一家咖啡馆、一处公告栏和几条小路。你会先做什么？', options: [
    { id: 'A', text: '找个地方坐下，先看看周围的情况。', value: -2 },
    { id: 'B', text: '看一眼地图，选好方向再动身。', value: -1 },
    { id: 'C', text: '先沿着最近的小路走一小段。', value: 1 },
    { id: 'D', text: '直接挑一家顺眼的店进去。', value: 2 },
  ] },
  { id: 'Q2', axis: 'company', kind: '场景', title: '一起做张贺卡', scene: '周末，你去活动室做一张手工贺卡，旁边也有人在做。你想怎么开始？', options: [
    { id: 'A', text: '先在本子上画草图，自己做。', value: -2 },
    { id: 'B', text: '先自己试，遇到不会的再问旁边的人。', value: -1 },
    { id: 'C', text: '找个人搭把手，一起把贺卡做出来。', value: 1 },
    { id: 'D', text: '问问大家的想法，凑在一起做一张。', value: 2 },
  ] },
  { id: 'Q3', axis: 'route', kind: '场景', title: '空出来的半天', scene: '原本约好的周末活动取消了，你想趁多出的半天出去逛逛。附近有几个想去的地方，都不急着去。你会怎么安排？', options: [
    { id: 'A', text: '列好时间表，把这半天安排清楚。', value: -2 },
    { id: 'B', text: '选一个主要目标，其他时间自由处理。', value: -1 },
    { id: 'C', text: '留两个备选，到时候再决定。', value: 1 },
    { id: 'D', text: '先不做安排，跟着当时的兴致走。', value: 2 },
  ] },
  { id: 'Q4', axis: 'pace', kind: '场景', title: '想到就试试？', scene: '你想用家里的纸盒做个桌面收纳盒，材料也都在手边。不急着用，做坏了也没关系。你会怎么开始？', options: [
    { id: 'A', text: '先弄清楚需要什么，暂时不急着动手。', value: -2 },
    { id: 'B', text: '看看类似做法，再试一个小步骤。', value: -1 },
    { id: 'C', text: '先做一个粗糙版本，边做边想。', value: 1 },
    { id: 'D', text: '马上开始，碰到问题时再解决。', value: 2 },
  ] },
  { id: 'Q5', axis: 'company', kind: '场景', title: '桌椅怎么摆', scene: '活动室想重新摆一下桌椅，几种摆法各有好处。你不急着决定，也可以和其他人讨论。你会怎么拿主意？', options: [
    { id: 'A', text: '先独立想透，再决定要不要分享。', value: -2 },
    { id: 'B', text: '先想一个办法，再问问别人怎么看。', value: -1 },
    { id: 'C', text: '找个人交换想法，一起修正答案。', value: 1 },
    { id: 'D', text: '叫上几个人聊聊，边聊边想办法。', value: 2 },
  ] },
  { id: 'Q6', axis: 'route', kind: '物品', title: '出发前的最后一样', scene: '你准备去附近一个不熟悉的地方待半天。必要用品已经齐了，包里还可以放一件东西。哪一样更符合你的习惯？', options: [
    { id: 'A', text: '写好的行程单：按顺序走，心里有底。', value: -2 },
    { id: 'B', text: '标出重点的地图：有方向，也能绕路。', value: -1 },
    { id: 'C', text: '一张空白卡片：到了再记下想去的地方。', value: 1 },
    { id: 'D', text: '一台小相机：遇到什么，就留下什么。', value: 2 },
  ] },
];

const AXIS_ANCHORS = Object.freeze({
  pace: [
    { id: 'A', anchorId: 'pace-observe', meaning: '先观察、理解或准备，暂时不开始实际操作' },
    { id: 'B', anchorId: 'pace-small-step', meaning: '先做少量准备，再试一个可收回的小步骤' },
    { id: 'C', anchorId: 'pace-prototype', meaning: '先做一个粗略版本，在行动中继续思考' },
    { id: 'D', anchorId: 'pace-start-now', meaning: '马上开始，遇到问题再现场处理' },
  ],
  company: [
    { id: 'A', anchorId: 'company-solo', meaning: '自己决定并独立完成' },
    { id: 'B', anchorId: 'company-consult', meaning: '先按自己的想法做，需要时再征求意见' },
    { id: 'C', anchorId: 'company-pair', meaning: '找一个人分工或共同修正' },
    { id: 'D', anchorId: 'company-group', meaning: '让多人一起讨论并共同完成' },
  ],
  route: [
    { id: 'A', anchorId: 'route-plan', meaning: '事先排好明确顺序或路线' },
    { id: 'B', anchorId: 'route-main-goal', meaning: '只定主要目标，其余保留调整空间' },
    { id: 'C', anchorId: 'route-options', meaning: '准备少量备选，到现场再决定' },
    { id: 'D', anchorId: 'route-improvise', meaning: '不预先安排，按当时情况行动' },
  ],
});

const STORY_RULES = [
  '写一个没有时间压力的日常空档：用户来到一个不熟悉但安全的地方，可以先观察也可以立刻开始探索。不要沿用陌生街区、咖啡馆或等朋友。',
  '写一个个人完全能独立完成、也可以与旁人合作的小型创作或整理任务。旁人是否参与没有奖惩。不要沿用贺卡或摆桌椅。',
  '写一个半天内的轻松外出或休闲安排，有多个同样可行的去处，没有必须完成的目标。不要沿用活动取消或空出来的半天。',
  '写一个材料齐全、失败成本很低的小制作或小尝试，既可以先研究也可以马上动手。不要沿用纸盒收纳盒。',
  '写一个可以自己决定、也可以和他人商量的日常方案任务，各种合作方式都可行。不要沿用活动室、桌椅或海报。',
  '写一个面对陌生体验时如何安排顺序的日常情境，必要条件已经满足，各种计划程度都可行。不要沿用旅行行李、行程单、地图或相机。',
];

// The model may write fresh stories and option copy, but these hidden anchors
// and their score order remain server-owned.
export const QUESTION_BLUEPRINTS = QUESTIONS.map((q, index) => ({
  questionId: q.id,
  axis: q.axis,
  axisName: AXES.find(axis => axis.id === q.axis).name,
  storyRule: STORY_RULES[index],
  options: AXIS_ANCHORS[q.axis],
  ...(q.axis === 'company' || q.axis === 'route' ? {
    reversalRule: q.axis === 'company'
      ? '给原任务增加一个关于合作边界的新条件；A保持原方向，B改用相反方向，C只协商或限定一部分。'
      : '给原任务增加一个关于计划变化的新条件；A保持原方向，B改用相反方向，C只确定一部分。',
  } : {}),
}));

export function fixedQuestionSet() {
  return QUESTIONS.map(q => ({
    questionId: q.id,
    kind: q.kind,
    title: q.title,
    scene: q.scene,
    options: q.options.map(({ id, text }) => ({ id, text })),
  }));
}

const TITLES = ['先想清楚再出发的人', '喜欢独自探索的人', '愿意一起做计划的人', '喜欢结伴发现新事的人', '习惯自己动手的人', '喜欢边做边试的人', '愿意带头开工的人', '喜欢和大家一起尝试的人'];
export function buildReversals(answers, sceneSet = []) {
  const { evidence } = score(answers);
  return ['company', 'route'].map((axis, index) => {
    // Choose the clearest earlier preference; break ties by original question order.
    const original = evidence.filter(e => e.axis === axis).sort((a, b) => Math.abs(b.value) - Math.abs(a.value))[0];
    const independent = original.value < 0;
    let condition, stay, change, middle;
    if (axis === 'company') {
      condition = independent ? '旁边的人说，可以按你的想法来，他帮忙做些重复的活。你愿意的话也可以继续自己做。' : '对方愿意一起做，但希望主要照他的想法来。你也可以自己做，不会耽误这件事。';
      stay = independent ? '还是自己做，想法和细节都自己定。' : '还是一起做，这部分先照他的想法试试。';
      change = independent ? '那就一起做，我出主意，他来帮忙。' : '那我还是自己做，试试自己的想法。';
      middle = '先商量一下，哪些照他的想法，哪些照我的。';
    } else {
      condition = independent ? '出门后，你发现原本想去的地方今天不开放。旁边还有几条没逛过的小街，时间也还早。' : '朋友说晚点想和你碰面，问你能不能先约好几点、在哪儿见。其他时间你可以自己逛。';
      stay = independent ? '重新查好去处和路线，再出发。' : '先随便逛，快结束时再联系他。';
      change = independent ? '不查了，先去旁边的小街逛逛。' : '先把见面的时间地点定好，再安排其他事。';
      middle = independent ? '只定一个想去的地方，路上再看。' : '只约好几点、在哪儿见，其他时候随便逛。';
    }
    const generated = sceneSet.find(item => item.questionId === original.questionId)?.reversal;
    if (generated) {
      condition = generated.condition;
      stay = generated.options.find(option => option.id === 'A').text;
      change = generated.options.find(option => option.id === 'B').text;
      middle = generated.options.find(option => option.id === 'C').text;
    }
    return { id: 'R' + (index + 1), kind: '情境反转', axis, title: axis === 'company' ? '如果对方这样说' : '这时，情况变了', sourceQuestionId: original.questionId, originalScene: original.scene, originalChoice: original.choice, condition, scene: condition + '你现在会怎样选择？', options: [
      { id: 'A', text: stay, responseType: '还是原来的做法', observation: '虽然条件变了，你这次还是选了原来的做法。' },
      { id: 'B', text: change, responseType: '这次换了做法', observation: '知道这件事后，你换了一个做法。把前后的条件放在一起看，才能理解这次选择。' },
      { id: 'C', text: middle, responseType: '先约定一部分', observation: '你先把需要商量的部分定下来，剩下的仍按自己的习惯来。' },
    ] };
  });
}
export function compareReversals(answers, reversalAnswers, sceneSet = []) {
  const plan = buildReversals(answers, sceneSet);
  if (!Array.isArray(reversalAnswers) || reversalAnswers.length !== plan.length) throw Error('请先完成两项情境反转。');
  return plan.map((r, i) => {
    const a = reversalAnswers[i], option = r.options.find(o => o.id === a?.optionId);
    if (a?.questionId !== r.id || !option) throw Error('反转记录不完整或顺序不正确。');
    return { id: r.id, axis: r.axis, sourceQuestionId: r.sourceQuestionId, originalScene: r.originalScene, originalChoice: a.originalChoice || r.originalChoice, condition: a.condition || a.scene?.replace(/你现在会怎样选择？$/, '') || r.condition, choice: a.choice || option.text, responseType: option.responseType, observation: option.observation };
  });
}
export function allChoices(t) { return [...(t.predictions || []), ...t.answers, ...(t.reversalAnswers || []), ...(t.tradeoffAnswers || []), ...(t.perspectiveAnswers || [])]; }
export function score(answers) {
  if (!Array.isArray(answers) || answers.length !== QUESTIONS.length) throw Error('请先完成全部六项选择。');
  const evidence = QUESTIONS.map((q, i) => {
    const a = answers[i];
    const option = q.options.find(o => o.id === a?.optionId);
    if (a?.questionId !== q.id || !option) throw Error('选择记录不完整或顺序不正确。');
    return { questionId: q.id, title: q.title, scene: a.scene || q.scene, optionId: option.id, choice: typeof a.choice === 'string' ? a.choice : option.text, axis: q.axis, value: option.value };
  });
  const axes = AXES.map(axis => {
    const raw = evidence.filter(e => e.axis === axis.id).reduce((n, e) => n + e.value, 0);
    return { ...axis, raw, position: 50 + raw * 12.5, tendency: raw === 0 ? '看情况，两种都会' : raw < 0 ? axis.left : axis.right };
  });
  const index = (axes[0].raw > 0 ? 4 : 0) + (axes[1].raw > 0 ? 2 : 0) + (axes[2].raw > 0 ? 1 : 0);
  return { title: axes.every(a => a.raw === 0) ? '灵活的平衡观察员' : TITLES[index], axes, evidence };
}

export function localReport(computed) {
  const [p, c, r] = computed.axes;
  const mid = a => a.raw === 0;
  return {
    tagline: '从你选过的答案，说说这次的做法。',
    summary: `这次你做事${mid(p) ? '有时先看看，有时直接试' : p.raw < 0 ? '更愿意先弄清情况，再动手' : '更愿意先试试，遇到问题再想办法'}。和别人一起做事时，你${mid(c) ? '有时想自己来，有时愿意一起做' : c.raw < 0 ? '倾向先拿出自己的想法' : '愿意边讨论边找办法'}。安排时间和路线时，你${mid(r) ? '既会做些准备，也给临时变化留了余地' : r.raw < 0 ? '喜欢先有个安排' : '更愿意到了再看'}。`,
    strengths: [mid(p) ? '有时先看看，有时直接试，做法会随事情变化。' : p.raw < 0 ? '愿意给理解情况留出时间。' : '有了想法就愿意先试一下。', mid(c) ? '既能自己处理，也愿意借助交流。' : c.raw < 0 ? '愿意先自己想一想，再听别人的意见。' : '遇到事情，愿意和别人一起想办法。'],
    frictions: [mid(r) ? '几个去处都想选时，可以先定一个最想去的。' : r.raw < 0 ? '临时改安排时，你可能想先理清楚再继续。' : '随意逛的时候，可以先把见面的时间定下来。', '和别人一起做事时，不妨先说说自己想怎么做。'],
    manual: ['先说清要做什么，再商量怎么做。', c.raw < 0 ? '让我先自己想一会儿，再一起聊。' : '有想法就一起聊，也留点各自决定的余地。', r.raw < 0 ? '变化发生时，把新的安排说清楚。' : '保留一点自主选择路线的余地。'],
    evidence: computed.evidence.slice(0, 3).map(e => ({ questionId: e.questionId, comment: `${e.axis === 'pace' ? (e.value < 0 ? '这次你选择先了解情况，再动手。' : '这次你愿意先行动，走一步看一步。') : e.axis === 'company' ? (e.value < 0 ? '这次你想先有自己的想法。' : '这次你愿意和别人一起想办法。') : e.value < 0 ? '这次你更想提前做好安排。' : '这次你给临时改变主意留了余地。'}` })),
    ...(computed.reversals?.length ? { reversals: computed.reversals.map(r => ({ reversalId: r.id, comment: r.observation })) } : {}),
    ...(computed.extras ? { extras: { prediction: '上面列出了你开始前的猜测和后来实际选的答案，可以看看哪些和预想的一样。', tradeoff: `你先选了“${computed.extras.tradeoff.selected.join('”和“')}”。后来，你选了“${computed.extras.tradeoff.retained}”全程保留；“${computed.extras.tradeoff.limited}”仍在前半程提供。`, perspective: `你给自己和小周的建议${computed.extras.perspective.relation === '给出了相同方向的选择' || computed.extras.perspective.relation === '选法一样' ? '一样' : '不一样'}。他想练习独立决定，和你自己的情况并不完全相同。` } } : {}),
  };
}

function cleanText(value, min, max) { return typeof value === 'string' && value.trim().length >= min && value.trim().length <= max; }
const unsafeCondition = /没电|电量不足|迟到|催促|赶时间|急需|危险|受伤|奖金|惩罚|考核|淘汰|必须成功|唯一正确/;
export function validateScenes(value) {
  if (!Array.isArray(value?.scenes) || value.scenes.length !== QUESTIONS.length) throw Error('AI 题面格式不符合要求。');
  return QUESTIONS.map(q => {
    const entries = value.scenes.filter(s => s.questionId === q.id);
    if (entries.length !== 1 || !cleanText(entries[0].scene, 20, 220)) throw Error('AI 题面缺失或长度不合适。');
    const conditions = entries[0].scene.replace(/(?:没有|无需|不必|不用)(?:任何人|人|谁)?(?:在)?(?:催促|赶时间|考核|惩罚)/g, '');
    if (unsafeCondition.test(conditions)) throw Error('AI 题面加入了会改变选择条件的信息。');
    return { questionId: q.id, scene: entries[0].scene.trim() };
  });
}

export function validateQuestionSet(value) {
  if (!Array.isArray(value?.scenes) || value.scenes.length !== QUESTION_BLUEPRINTS.length) throw Error('AI 新题集格式不符合要求。');
  const titles = new Set();
  const scenes = QUESTION_BLUEPRINTS.map((blueprint, index) => {
    const matches = value.scenes.filter(item => item?.questionId === blueprint.questionId);
    if (matches.length !== 1) throw Error('AI 新题集缺少题目或题号重复。');
    const item = matches[0];
    if (!cleanText(item.title, 2, 24) || !cleanText(item.scene, 20, 220)) throw Error('AI 新题集标题或题面长度不合适。');
    const title = item.title.trim(), scene = item.scene.trim();
    if (titles.has(title) || scene === QUESTIONS[index].scene || unsafeCondition.test(scene)) throw Error('AI 新题集重复旧题或加入了不公平条件。');
    titles.add(title);
    if (!Array.isArray(item.options) || item.options.length !== 4) throw Error('AI 新题集必须为每题提供四个选项。');
    const optionTexts = new Set();
    const options = blueprint.options.map(anchor => {
      const matches = item.options.filter(option => option?.id === anchor.id);
      const option = matches[0];
      if (matches.length !== 1 || option.anchorId !== anchor.anchorId || !cleanText(option.text, 4, 72)) throw Error('AI 新题选项没有保持指定的行为锚点。');
      const text = option.text.trim();
      if (optionTexts.has(text) || unsafeCondition.test(text)) throw Error('AI 新题选项重复或包含不公平条件。');
      optionTexts.add(text);
      return { id: anchor.id, text };
    });
    let reversal;
    if (blueprint.reversalRule) {
      if (!item.reversal || !cleanText(item.reversal.condition, 16, 180) || unsafeCondition.test(item.reversal.condition)) throw Error('AI 新题缺少可用的情境反转。');
      const expected = [
        { id: 'A', anchorId: 'reversal-stay' },
        { id: 'B', anchorId: 'reversal-switch' },
        { id: 'C', anchorId: 'reversal-boundary' },
      ];
      const reversalTexts = new Set();
      reversal = {
        condition: item.reversal.condition.trim(),
        options: expected.map(anchor => {
          const matches = Array.isArray(item.reversal.options) ? item.reversal.options.filter(option => option?.id === anchor.id) : [];
          const option = matches[0];
          if (matches.length !== 1 || option.anchorId !== anchor.anchorId || !cleanText(option.text, 4, 72)) throw Error('AI 情境反转选项格式不正确。');
          const text = option.text.trim();
          if (reversalTexts.has(text) || unsafeCondition.test(text)) throw Error('AI 情境反转选项重复或包含不公平条件。');
          reversalTexts.add(text);
          return { id: anchor.id, text };
        }),
      };
    }
    return { questionId: blueprint.questionId, kind: '场景', title, scene, options, ...(reversal ? { reversal } : {}) };
  });
  if (new Set(scenes.map(item => item.scene)).size !== scenes.length) throw Error('AI 新题集包含重复故事。');
  return scenes;
}
export function validateReport(value, computed) {
  if (!value || !cleanText(value.tagline, 4, 80) || !cleanText(value.summary, 20, 500)) throw Error('AI 档案缺少有效的描述。');
  for (const key of ['strengths', 'frictions', 'manual']) {
    if (!Array.isArray(value[key]) || value[key].length < 2 || value[key].length > 6 || !value[key].every(x => cleanText(x, 4, 140))) throw Error('AI 档案条目格式不正确。');
  }
  if (!Array.isArray(value.evidence) || value.evidence.length < 3 || value.evidence.length > 6 || new Set(value.evidence.map(e => e.questionId)).size !== value.evidence.length || !value.evidence.every(e => computed.evidence.some(a => a.questionId === e.questionId) && cleanText(e.comment, 4, 160))) throw Error('AI 档案必须引用至少三条不同的真实选择。');
  if (computed.reversals?.length && (!Array.isArray(value.reversals) || value.reversals.length !== 2 || new Set(value.reversals.map(r => r.reversalId)).size !== 2 || !value.reversals.every(r => computed.reversals.some(s => s.id === r.reversalId) && cleanText(r.comment, 8, 240)))) throw Error('AI 档案必须对照两项真实的情境反转。');
  if (computed.extras && (!value.extras || !['prediction', 'tradeoff', 'perspective'].every(key => cleanText(value.extras[key], 8, 260)))) throw Error('AI 档案缺少预判、取舍或换位的对照。');
  return { tagline: value.tagline, summary: value.summary, strengths: value.strengths.slice(0, 3), frictions: value.frictions.slice(0, 3), manual: value.manual.slice(0, 3), evidence: value.evidence.slice(0, 3).map(e => ({ questionId: e.questionId, comment: e.comment })), ...(computed.reversals?.length ? { reversals: value.reversals.map(r => ({ reversalId: r.reversalId, comment: r.comment })) } : {}), ...(computed.extras ? { extras: Object.fromEntries(['prediction','tradeoff','perspective'].map(key => [key,key === 'tradeoff' ? localReport(computed).extras.tradeoff : value.extras[key]])) } : {}) };
}
export function marker(a) { return `[${a.questionId}:${a.optionId}]`; }
