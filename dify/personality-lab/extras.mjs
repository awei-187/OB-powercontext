import { AXES, score } from './core.mjs';

export const LEGACY_CARDS = [
  { id: 'A', text: '提前知道全部路线', detail: '去哪里、怎么走，都心里有底。', symbol: '↗' },
  { id: 'B', text: '有朋友全程陪同', detail: '一路有人分享见闻，也一起做决定。', symbol: '◎' },
  { id: 'C', text: '随时改变目的地', detail: '想换条路，随时可以转向。', symbol: '⌁' },
  { id: 'D', text: '独自安静待着', detail: '有一段完全属于自己的空间。', symbol: '◐' },
];
export const CARDS = [
  { id: 'A', text: '有人帮你安排路线', detail: '不用自己查路，有人帮你安排好。', symbol: '↗' },
  { id: 'B', text: '有朋友一起逛', detail: '看见有意思的东西，身边有人可以聊。', symbol: '◎' },
  { id: 'C', text: '可以临时换地方', detail: '途中想去别处，可以随时改主意。', symbol: '⌁' },
  { id: 'D', text: '有安静的休息点', detail: '想歇一会儿，就能找到安静的地方坐下。', symbol: '◐' },
];

export const PERSPECTIVE_SCENE = '你正在做一张活动海报，已经画好了大致的样子。旁边有人问要不要一起做。时间够用，你自己也能做完。你会怎么办？';
export const COMPANION = '这次换成小周遇到了同一件事。他平时常跟着别人的意见走，最近想试着自己拿主意，也愿意听建议。他来问你怎么办，你会怎么建议他？';
const PERSPECTIVE_OPTIONS = [
  { id: 'A', text: '先自己做完，再拿给大家看。' },
  { id: 'B', text: '先按自己的想法做，再问问哪里能改。' },
  { id: 'C', text: '商量好各自做哪部分，一起做完。' },
  { id: 'D', text: '把画好的草图拿出来，大家重新讨论怎么做。' },
];
export function predictionRecords(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input) || Object.keys(input).length !== AXES.length) throw Error('请为三个维度各选一项预判。');
  return AXES.map((axis, i) => {
    const code = input[axis.id];
    if (!['left', 'middle', 'right'].includes(code)) throw Error('请为三个维度各选一项预判。');
    const choice = code === 'left' ? axis.left : code === 'right' ? axis.right : '看情况，两种都会';
    return { questionId: 'P' + (i + 1), optionId: { left: 'A', middle: 'B', right: 'C' }[code], axis: axis.id, prediction: code, scene: '开始前自我预判 · ' + axis.name, choice: '我预想自己更接近：' + choice, label: choice };
  });
}
export function tradeoffQuestion(t) {
  const first = t.tradeoffAnswers?.[0];
  const cards = first?.cards || (t.copyVersion >= 2 ? CARDS : LEGACY_CARDS);
  if (!first) return { id: 'T1', kind: '只能留下两样', title: '如果不能全部拥有', scene: '你报名了一次半天的城市游览，可以从下面四项安排中选两项。你想要哪两项？', options: cards, multi: true };
  const ids = first.optionIds;
  if (!Array.isArray(ids) || ids.length !== 2 || ids.some(id => !CARDS.some(c => c.id === id))) throw Error('取舍记录无效。');
  return { id: 'T2', kind: '只能留下两样', title: '再做一次取舍', originalChoice: first.choice, scene: '刚才选的两项安排，只有一项能从头到尾都有，另一项只在前半程提供。你希望哪项全程都有？', options: cards.filter(c => ids.includes(c.id)), multi: false };
}
export function tradeoffRecord(t, input) {
  const q = tradeoffQuestion(t);
  if (input.questionId !== q.id) throw Error('请回答当前的取舍题。');
  if (q.multi) {
    const ids = input.optionIds;
    if (!Array.isArray(ids) || ids.length !== 2 || new Set(ids).size !== 2 || !ids.every(id => CARDS.some(c => c.id === id))) throw Error('请选择两样不同的便利。');
    const canonical = q.options.filter(c => ids.includes(c.id));
    return { questionId: q.id, optionId: canonical.map(c => c.id).join(''), optionIds: canonical.map(c => c.id), cards: canonical.map(c => ({ ...c })), scene: q.scene, choice: canonical.map(c => c.text).join(' ＋ ') };
  }
  const chosen = q.options.find(c => c.id === input.optionId);
  if (!chosen) throw Error('请从刚才留下的两样中，选择完整保留的一项。');
  const limited = q.options.find(c => c.id !== chosen.id);
  return { questionId: q.id, optionId: chosen.id, scene: q.scene, choice: '全程保留：' + chosen.text + '；仅保留半程：' + limited.text };
}
export function perspectiveQuestion(t) {
  const self = t.perspectiveAnswers?.[0];
  return { id: self ? 'S2' : 'S1', kind: '替别人选一次', title: self ? '同一件事，给他一点建议' : '先替自己选一次', scene: PERSPECTIVE_SCENE, ...(self ? { companion: COMPANION, originalChoice: self.choice } : {}), options: PERSPECTIVE_OPTIONS.map(o => ({ id: o.id, text: self ? '建议他：' + o.text : o.text })) };
}
export function perspectiveRecord(t, input) {
  const q = perspectiveQuestion(t), option = q.options.find(o => o.id === input.optionId);
  if (input.questionId !== q.id || !option) throw Error('请选择当前视角中的一个选项。');
  return { questionId: q.id, optionId: option.id, scene: q.scene + (q.companion ? '\n' + q.companion : ''), choice: option.text };
}
export function extraComparisons(t) {
  const predictions = t.predictions;
  if (!Array.isArray(predictions) || predictions.length !== 3 || !Array.isArray(t.tradeoffAnswers) || t.tradeoffAnswers.length !== 2 || !Array.isArray(t.perspectiveAnswers) || t.perspectiveAnswers.length !== 2) throw Error('请先完成预判、取舍和换位选择。');
  const base = score(t.answers);
  const prediction = base.axes.map(axis => {
    const p = predictions.find(p => p.axis === axis.id);
    const observed = axis.raw < 0 ? 'left' : axis.raw > 0 ? 'right' : 'middle';
    return { axis: axis.id, name: axis.name, predicted: p.label, observed: axis.tendency, relation: p.prediction === observed ? '和猜的一样' : '和猜的不一样' };
  });
  const first = t.tradeoffAnswers[0], second = t.tradeoffAnswers[1];
  const cards = first.cards || (t.copyVersion >= 2 ? CARDS : LEGACY_CARDS);
  const selected = first.optionIds.map(id => cards.find(c => c.id === id));
  const retained = selected.find(c => c.id === second.optionId), limited = selected.find(c => c.id !== second.optionId);
  if (!retained || !limited) throw Error('取舍记录不匹配。');
  const [self, other] = t.perspectiveAnswers;
  return { prediction, tradeoff: { selected: selected.map(c => c.text), retained: retained.text, limited: limited.text, initialChoice: first.choice, finalChoice: second.choice }, perspective: { scene: self.scene || PERSPECTIVE_SCENE, companion: other.scene?.startsWith((self.scene || PERSPECTIVE_SCENE) + '\n') ? other.scene.slice((self.scene || PERSPECTIVE_SCENE).length + 1) : COMPANION, selfChoice: self.choice, otherChoice: other.choice, relation: self.optionId === other.optionId ? '选法一样' : '选法不一样' } };
}
