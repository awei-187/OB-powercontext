import { createRequire } from 'node:module';
import fs from 'node:fs/promises';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { createApp, ROOT } from '../server.mjs';
import assert from 'node:assert/strict';

// Reuse an installed browser and playwright-core. No browser download is required.
const require = createRequire(import.meta.url);
let chromium;
try { ({ chromium } = require('playwright-core')); }
catch { ({ chromium } = require(path.resolve(ROOT, '..', 'node_modules', 'playwright-core'))); }
const executablePath = process.env.CHROME || ['C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', '/usr/bin/chromium'].find(existsSync);
if (!executablePath) throw Error('请设置 CHROME 为已安装浏览器的路径。');
const output = path.join(ROOT, '.runtime', 'browser'); await fs.mkdir(output, { recursive: true });
const server = createApp({ mode: 'local', dataDir: path.join(output, 'data') });
await new Promise(r => server.listen(0, '127.0.0.1', r));
const url = 'http://127.0.0.1:' + server.address().port;
const browser = await chromium.launch({ executablePath, headless: true });
const errors = [], outside = [], checks = [];
async function predictions(page) {
  await page.getByRole('heading',{name:'你觉得自己通常会怎么选？'}).waitFor();
  assert.equal(await page.getByRole('button',{name:/选好了，开始答题/}).isDisabled(),true);
  for(const [axis,value] of [['pace','left'],['company','middle'],['route','right']]) await page.locator(`[data-predict-axis="${axis}"][data-predict-value="${value}"]`).click();
  await page.screenshot({path:path.join(output,page.viewportSize().width<700?'14-prediction-mobile.png':'09-prediction.png'),fullPage:true});
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.getByRole('button',{name:/选好了，开始答题/}).click();
}
async function extras(page,mobile=false) {
  await page.getByRole('heading',{name:'如果不能全部拥有'}).waitFor();
  assert.equal(await page.getByRole('button',{name:/就选这两项/}).isDisabled(),true);
  await page.locator('[data-option="A"]').click();await page.locator('[data-option="C"]').click();
  await page.locator('[data-option="B"]').click();assert.equal(await page.locator('.option.selected').count(),2);
  await page.locator('[data-option="A"]').click(); await page.locator('[data-option="A"]').click();
  await page.screenshot({path:path.join(output,mobile?'12-tradeoff-mobile.png':'10-tradeoff.png'),fullPage:true}); assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.getByRole('button',{name:/就选这两项/}).click();
  await page.getByRole('heading',{name:'再做一次取舍'}).waitFor();await page.reload();
  await page.getByRole('heading',{name:'再做一次取舍'}).waitFor();assert.equal(await page.locator('.option').count(),2);
  assert.equal(await page.locator('[data-option="B"]').count(),0);
  await page.locator('[data-option="C"]').click();await page.getByRole('button',{name:/这项全程保留/}).click();
  await page.getByRole('heading',{name:'先替自己选一次'}).waitFor();await page.locator('[data-option="A"]').click();
  await page.getByRole('button',{name:/再替小周选一次/}).click();
  await page.getByRole('heading',{name:'同一件事，给他一点建议'}).waitFor();
  assert.ok((await page.locator('.old-choice').innerText()).includes('先自己做完'));
  await page.screenshot({path:path.join(output,mobile?'13-perspective-mobile.png':'11-perspective.png'),fullPage:true}); assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.locator('[data-option="D"]').click();await page.getByRole('button',{name:/选好了，看结果/}).click();
}
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true, reducedMotion: 'reduce' });
  const page = await context.newPage();
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('request', r => { if (!r.url().startsWith(url) && !r.url().startsWith('blob:') && !r.url().startsWith('data:')) outside.push(r.url()); });
  await page.goto(url); await page.getByRole('button', { name: /开始测试/ }).waitFor();
  await page.screenshot({ path: path.join(output, '01-welcome.png'), fullPage: true });
  await page.getByRole('button', { name: /开始测试/ }).click();
  await predictions(page);
  for (let i = 0; i < 6; i++) {
    await page.locator('.question-meta').getByText(`第 ${i + 1} / 6 题`, { exact: false }).waitFor();
    assert.equal(await page.locator('.option').count(), 4);
    assert.equal(await page.getByRole('button', { name: /下一题|选好了|再换个条件试试/ }).isDisabled(), true);
    await page.locator(`[data-option="${i % 2 === 0 ? 'C' : 'A'}"]`).click();
    if (i === 0) await page.screenshot({ path: path.join(output, '02-question.png'), fullPage: true });
    await page.getByRole('button', { name: /下一题|选好了|再换个条件试试/ }).click();
    if (i === 1) { await page.locator('.question-meta').getByText('第 3 / 6', { exact: false }).waitFor(); await page.reload(); }
  }
  for (let i = 0; i < 2; i++) {
    await page.locator('.question-meta').getByText(`换个条件 ${i + 1} / 2`, { exact: false }).waitFor();
    assert.equal(await page.locator('.option').count(), 3);
    const current = (await page.evaluate(() => fetch('/api/state').then(r => r.json()))).test;
    assert.ok((await page.locator('.old-choice').innerText()).includes(current.question.originalChoice));
    await page.locator('.old-choice summary').click(); assert.ok((await page.locator('.old-choice').innerText()).includes(current.question.originalScene));
    if (i === 0) await page.screenshot({ path: path.join(output, '06-reversal-desktop.png'), fullPage: true });
    await page.locator(`[data-option="${i ? 'C' : 'B'}"]`).click();
    await page.getByRole('button', { name: /下一题|继续/ }).click();
    if (i === 0) { await page.locator('.question-meta').getByText('换个条件 2 / 2').waitFor(); await page.reload(); }
  }
  await extras(page);
  await page.getByRole('button', { name: /查看我的说明书/ }).waitFor();
  assert.equal(await page.locator('.answer-row').count(), 15);
  await page.getByRole('button', { name: /查看我的说明书/ }).click();
  await page.locator('.dossier h1').waitFor();
  assert.equal(await page.locator('.evidence-card').count(), 3);
  assert.equal(await page.locator('.axis-marker').count(), 3);
  assert.equal(await page.locator('.reversal-review .comparison').count(), 2);
  assert.equal(await page.locator('.extra-review').count(), 3);
  assert.equal(await page.locator('.prediction-result').count(), 3);
  await page.locator('.reversal-review').screenshot({ path: path.join(output, '08-report-comparison.png') });
  await page.screenshot({ path: path.join(output, '03-report.png'), fullPage: true });
  await page.reload(); await page.locator('.dossier h1').waitFor();
  checks.push('six initial choices, two source-linked reversals, refresh resume mid-reversal, complete report with two reversal comparisons, three extra sections and three evidence citations');
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: /保存长卡片/ }).click();
  const download = await downloadPromise; await download.saveAs(path.join(output, 'exported-card.svg'));
  const svg = await fs.readFile(path.join(output, 'exported-card.svg'), 'utf8'); assert.ok(svg.includes('<svg')); assert.ok(svg.includes('个人使用说明书')); assert.ok(!svg.includes('<script')); assert.ok(svg.includes('什么条件下，你会改变主意')); assert.ok(svg.includes('新条件：')); assert.ok(svg.includes('你猜的，和这次选的')); assert.ok(svg.includes('建议小周：'));
  const jsonPromise = page.waitForEvent('download'); await page.getByRole('button', { name: '导出记录', exact: true }).click();
  await (await jsonPromise).saveAs(path.join(output, 'exported-report.json'));
  const exported = JSON.parse(await fs.readFile(path.join(output, 'exported-report.json'), 'utf8')); assert.equal(exported.evidence.length, 6); assert.equal(exported.source, 'local'); assert.equal(exported.reversals.length, 2); assert.equal(exported.reversals[0].responseType, '这次换了做法'); assert.equal(exported.extras.tradeoff.retained,'可以临时换地方'); assert.ok(exported.narrative.extras);
  checks.push('prediction selection, exactly-two tradeoff with subset retention, self/other decisions, refresh mid-tradeoff, SVG and JSON exports');
  await page.getByRole('button', { name: /再测一次/ }).click(); await page.getByRole('button', { name: '保留这份' }).click(); assert.equal(await page.locator('.dossier').count(), 1);
  await page.getByRole('button', { name: /再测一次/ }).click(); await page.getByRole('button', { name: /重新开始/ }).click(); await page.setViewportSize({width:390,height:844}); await predictions(page); await page.locator('.question-meta').getByText('第 1 / 6', { exact: false }).waitFor();
  checks.push('restart confirmation retains or archives the prior session and starts a new test');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: path.join(output, '04-mobile-question.png'), fullPage: true });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  for (let i = 0; i < 6; i++) {
    await page.locator('.question-meta').getByText(`第 ${i + 1} / 6`, { exact: false }).waitFor();
    await page.locator('[data-option="D"]').click(); await page.getByRole('button', { name: /下一题|选好了|再换个条件试试/ }).click();
  }
  for (let i = 0; i < 2; i++) {
    await page.locator('.question-meta').getByText(`换个条件 ${i + 1} / 2`).waitFor();
    if (i === 0) await page.screenshot({ path: path.join(output, '07-reversal-mobile.png'), fullPage: true });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await page.locator(`[data-option="${i ? 'B' : 'A'}"]`).click();
    await page.getByRole('button', { name: /下一题|继续/ }).click();
  }
  await extras(page,true);
  await page.getByRole('button', { name: /查看我的说明书/ }).click(); await page.locator('.dossier h1').waitFor();
  await page.screenshot({ path: path.join(output, '05-mobile-report.png'), fullPage: true });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.setViewportSize({ width: 320, height: 740 }); assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  checks.push('390px question, reversal and report, 320px report have no horizontal overflow');
  assert.deepEqual(errors, []); assert.deepEqual(outside, []);
  const result = { passed: true, browser: browser.version(), checkedAt: new Date().toISOString(), checks, errors, outside };
  await fs.writeFile(path.join(output, 'results.json'), JSON.stringify(result, null, 2)); console.log(JSON.stringify(result));
  await context.close();
} finally { await browser.close(); server.closeAllConnections(); await new Promise(r => server.close(r)); }
