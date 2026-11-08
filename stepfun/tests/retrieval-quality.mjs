import {chromium} from 'playwright-core';import {readFile,writeFile,mkdir} from 'node:fs/promises';import {createHash} from 'node:crypto';import os from 'node:os';import assert from 'node:assert/strict';
import {quality} from '../src/core.mjs';
import {variants} from '../server/retrieval.mjs';
const out=process.env.RESULT_DIR||'test-results/retrieval-quality/run-'+new Date().toISOString().replace(/[:.]/g,'-');await mkdir(out,{recursive:true});
const bytes=await readFile('data/fixture.json'),fixtureHash=createHash('sha256').update(bytes).digest('hex'),f=JSON.parse(bytes);
assert.equal(fixtureHash,'1aac6c5e31da316c51404128aa730c9f10aaf08c473a705e7d8e786e0134e21b');
let original;
try{original=JSON.parse(await readFile('test-results/retrieval-quality/baseline-v1/test-results/benchmark.json')).runs.find(r=>r.config.dtype==='fp16');}catch{}
const report={at:new Date().toISOString(),fixtureSha256:fixtureHash,conditions:{cpu:os.cpus()[0].model,totalMemory:os.totalmem(),freeMemoryAtStart:os.freemem(),queries:12,documents:100,repeats:3,k:5,
  note:'Paired alternating order, one FP16 WebGPU model; same persisted document vectors; each measured query recomputes its embedding in the browser; warmup per case excluded'},strategies:variants,cases:[],warmups:[]};
const browser=await chromium.launch({executablePath:process.env.CHROME||'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
const page=await browser.newPage({viewport:{width:1280,height:1000}}),unexpected=[],errors=[];
page.on('request',r=>{if(!r.url().startsWith('http://127.0.0.1:4317')&&!r.url().startsWith('blob:'))unexpected.push(r.url());});page.on('pageerror',e=>errors.push(e.message));
try {
  await page.goto('http://127.0.0.1:4317');await page.waitForFunction(()=>window.stepfunTest);await page.waitForFunction(()=>document.querySelector('#dbStatus').textContent.includes('已连接'));
  report.browser=await browser.version();report.model=await page.evaluate(()=>window.stepfunTest.loadModel('fp16','auto'));assert.equal(report.model.backend,'webgpu');assert.equal(report.model.dtype,'fp16');
  report.health=await page.evaluate(()=>window.stepfunTest.api('/health'));if(process.env.EXPECT_DB_MODE)assert.equal(report.health.mode,process.env.EXPECT_DB_MODE);
  let baselineId=original?.kb.id;
  const existing=await page.evaluate(()=>window.stepfunTest.api('/kbs'));
  if(process.env.QUALITY_FRESH==='1' || !existing.some(k=>k.id===baselineId)){
    const k=await page.evaluate(()=>window.stepfunTest.api('/kbs',{name:'复现原版-'+Date.now(),dtype:'fp16',retrieval:'baseline-v1'}));
    baselineId=k.id;await page.evaluate(id=>window.stepfunTest.reloadKbs(id),baselineId);
    report.freshBaselineImport=await page.evaluate(d=>window.stepfunTest.importDocs(d,4),f.documents);
  }
  report.baselineKb=baselineId;
  // Exercise the visible upgrade button. The old baseline collection is preserved.
  await page.evaluate(id=>window.stepfunTest.select(id),baselineId);await page.click('#optimize');await page.waitForFunction(()=>!document.querySelector('#optimize').disabled,undefined,{timeout:60000});
  const upgraded=await page.locator('#kb').inputValue();assert.notEqual(upgraded,baselineId);report.upgradedKb=upgraded;
  report.cases=[
    {name:'baseline',kb:baselineId,expected:'baseline-v1'},
    {name:'index-only',kb:upgraded,strategy:'baseline-v1',expected:'baseline-v1'},
    {name:'fusion-only',kb:baselineId,strategy:'score-75',expected:'score-75'},
    {name:'quality-v2',kb:upgraded,expected:'quality-v2'},
    {name:'recall-priority',kb:upgraded,strategy:'score-50',expected:'score-50'},
  ].map(c=>({...c,rows:[]}));
  for(const c of report.cases){await page.evaluate(id=>window.stepfunTest.select(id),c.kb);const r=await page.evaluate(c=>window.stepfunTest.query('数据库 索引刷新',5,c.strategy),c);assert.equal(r.strategy,c.expected);report.warmups.push({case:c.name,...r});}
  for(let repeat=0;repeat<3;repeat++)for(let qi=0;qi<f.queries.length;qi++){
    const q=f.queries[qi],offset=(repeat+qi)%report.cases.length;
    for(let i=0;i<report.cases.length;i++){
      const c=report.cases[(i+offset)%report.cases.length];await page.evaluate(id=>window.stepfunTest.select(id),c.kb);
      const r=await page.evaluate(({q,strategy})=>window.stepfunTest.query(q,5,strategy),{q:q.text,strategy:c.strategy});
      assert.equal(r.strategy,c.expected);
      c.rows.push({repeat,queryId:q.id,...r,...quality(r.ids,q.relevance),precisionAt1:Number((q.relevance[r.ids[0]]||0)>0)});
    }
  }
  const median=xs=>{const a=[...xs].sort((a,b)=>a-b),n=a.length;return n%2?a[(n-1)/2]:(a[n/2-1]+a[n/2])/2;};
  for(const c of report.cases){
    c.summary={recallAt5:c.rows.reduce((s,r)=>s+r.recall,0)/36,ndcgAt5:c.rows.reduce((s,r)=>s+r.ndcg,0)/36,precisionAt1:c.rows.reduce((s,r)=>s+r.precisionAt1,0)/36,
      queryEmbeddingMedianMs:median(c.rows.map(r=>r.queryEmbeddingMs)),searchMedianMs:median(c.rows.map(r=>r.searchMs)),endToEndMedianMs:median(c.rows.map(r=>r.endToEndMs))};
    c.perQuery=f.queries.map(q=>{const r=c.rows.filter(r=>r.queryId===q.id);return {id:q.id,text:q.text,recall:r.reduce((s,x)=>s+x.recall,0)/3,ndcg:r.reduce((s,x)=>s+x.ndcg,0)/3,precisionAt1:r.reduce((s,x)=>s+x.precisionAt1,0)/3,ids:r[0].ids,stableAcrossRepeats:r.every(x=>JSON.stringify(x.ids)===JSON.stringify(r[0].ids))};});
    console.log(c.name,c.summary);
  }
  if(original){
    report.historicalBaselineRecall=original.summary.recallAt5;
    report.baselineRecallDrift=report.cases[0].summary.recallAt5-original.summary.recallAt5;
    // Fresh collections may have different internal row IDs for exactly tied SDK RRF scores.
    // Preserve/report that variation rather than changing judgments or forcing the historical score.
    if(!report.freshBaselineImport)assert.ok(Math.abs(report.baselineRecallDrift)<1e-12);
  }
  assert.deepEqual(unexpected,[]);assert.deepEqual(errors,[]);
  await page.evaluate(id=>window.stepfunTest.select(id),upgraded);await page.fill('#query',f.queries[0].text);await page.click('#search');await page.waitForFunction(()=>!document.querySelector('#search').disabled);
  await page.screenshot({path:out+'/app-optimized.png',fullPage:true});
  report.unexpectedRequests=unexpected;report.pageErrors=errors;report.ok=true;
}catch(e){report.error=e.stack;process.exitCode=1;console.error(e.message);}finally{await writeFile(out+'/comparison.json',JSON.stringify(report,null,2));await browser.close();}
