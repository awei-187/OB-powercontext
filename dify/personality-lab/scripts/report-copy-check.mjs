// Reuse synthetic completed choices to inspect report wording with one model request.
import fs from 'node:fs/promises';
import path from 'node:path';
import { report } from '../services.mjs';
import { readConfig, ROOT } from '../server.mjs';
if (process.env.ALLOW_LIVE_MODEL !== '1') throw Error('需要显式设置ALLOW_LIVE_MODEL=1。');
const prior = JSON.parse(await fs.readFile(path.join(ROOT, '.runtime/live/results.json'), 'utf8'));
const { narrative, createdAt, source, memorySource, recalledVerified, ...computed } = prior.report;
const config = { ...readConfig(), mode: 'deepseek' };
const result = await report(config, computed, '', computed.id);
const output = path.join(ROOT, '.runtime/copy-review'); await fs.mkdir(output, { recursive: true });
await fs.writeFile(path.join(output, 'report.json'), JSON.stringify({ checkedAt: new Date().toISOString(), model: config.deepseekModel, computed, narrative: result }, null, 2));
console.log('报告结构与证据检查通过，生成内容已保存在独立检查目录。');
