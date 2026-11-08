import {chromium} from 'playwright-core';import {mkdir,readFile,writeFile} from 'node:fs/promises';
import assert from 'node:assert/strict';import os from 'node:os';import {quality} from '../src/core.mjs';
const f=JSON.parse(await readFile('data/fixture.json')),manifest=JSON.parse(await readFile('model-manifest.json'));
const out=process.env.RESULT_DIR||'test-results/benchmark-'+new Date().toISOString().replace(/[:.]/g,'-');await mkdir(out,{recursive:true});
const report={at:new Date().toISOString(),device:{platform:os.platform(),cpu:os.cpus()[0].model,cores:os.cpus().length,totalMemory:os.totalmem(),freeMemoryAtStart:os.freemem()},
  conditions:{documents:f.documents.length,queries:f.queries.length,repeats:3,k:5,tokenLimit:256,wasmThreads:2,batchSize:4,modelInstances:'one at a time',database:'recorded from runtime /api/health',corpus:'data/fixture.json',qrels:'authored topical relevance; engineering regression only',model:manifest},runs:[]};
const configs=[{dtype:'fp32',backend:'auto',expect:'webgpu'},{dtype:'fp16',backend:'auto',expect:'webgpu'},{dtype:'fp32',backend:'auto',disableGpu:true,expect:'wasm'},{dtype:'q8',backend:'auto',disableGpu:true,expect:'wasm'}];
const executablePath=process.env.CHROME||'C:/Program Files/Google/Chrome/Application/chrome.exe';
for(const config of configs){
  console.log('Running',config);
  const browser=await chromium.launch({executablePath,headless:true,args:config.disableGpu?['--disable-gpu','--disable-webgpu']:[]});
  const context=await browser.newContext(),page=await context.newPage();
  const run={config,browser:await browser.version(),unexpectedRequests:[],pageErrors:[],queryRuns:[],imports:[]};report.runs.push(run);
  page.on('pageerror',e=>run.pageErrors.push(e.message));
  page.on('request',r=>{if(!r.url().startsWith('http://127.0.0.1:4317')&&!r.url().startsWith('blob:'))run.unexpectedRequests.push(r.url());});
  try {
    await page.goto('http://127.0.0.1:4317');await page.waitForFunction(()=>window.stepfunTest);
    run.health=await page.evaluate(()=>window.stepfunTest.api('/health'));if(process.env.EXPECT_DB_MODE)assert.equal(run.health.mode,process.env.EXPECT_DB_MODE);report.health??=run.health;report.conditions.database={mode:run.health.mode,version:run.health.version};
    run.coldLoad=await page.evaluate(c=>window.stepfunTest.loadModel(c.dtype,c.backend),config);
    assert.equal(run.coldLoad.backend,config.expect);
    run.cachedReload=await page.evaluate(c=>window.stepfunTest.loadModel(c.dtype,c.backend),config);
    const k=await page.evaluate(name=>window.stepfunTest.createKb(name),'评测-'+config.dtype+'-'+config.expect+'-'+Date.now());run.kb=k;
    run.firstImport=await page.evaluate(d=>window.stepfunTest.importDocs(d,4),f.documents);
    for(let repeat=0;repeat<3;repeat++) {
      // Compare batching on the same already-populated collection. Alternate order to reduce order bias.
      if(config.dtype==='fp16') for(const batch of (repeat%2?[4,1]:[1,4])) run.imports.push({repeat,...await page.evaluate(({d,b})=>window.stepfunTest.importDocs(d,b),{d:f.documents,b:batch})});
      for(const q of f.queries){
        const result=await page.evaluate(q=>window.stepfunTest.query(q,5),q.text);
        run.queryRuns.push({repeat,queryId:q.id,...result,...quality(result.ids,q.relevance,5)});
      }
    }
    const median=xs=>{const a=xs.sort((a,b)=>a-b);return a.length%2?a[(a.length-1)/2]:(a[a.length/2-1]+a[a.length/2])/2;};
    const warm=run.queryRuns.slice(1);
    run.summary={recallAt5:run.queryRuns.reduce((s,x)=>s+x.recall,0)/run.queryRuns.length,ndcgAt5:run.queryRuns.reduce((s,x)=>s+x.ndcg,0)/run.queryRuns.length,
      queryEmbeddingMedianMs:median(warm.map(x=>x.queryEmbeddingMs)),searchMedianMs:median(warm.map(x=>x.searchMs)),endToEndMedianMs:median(warm.map(x=>x.endToEndMs)),firstQuery:run.queryRuns[0],
      batchComparison:run.imports.length?[1,4].map(batch=>({batch,embeddingMedianMs:median(run.imports.filter(x=>x.batchSize===batch).map(x=>x.embeddingMs)),totalMedianMs:median(run.imports.filter(x=>x.batchSize===batch).map(x=>x.totalMs))})):[]};
    assert.deepEqual(run.unexpectedRequests,[]);assert.deepEqual(run.pageErrors,[]);run.ok=true;
    console.log('Complete',run.summary);
  }catch(e){run.error=e.stack;process.exitCode=1;console.error(e.message);}finally{await browser.close();await writeFile(`${out}/benchmark.json`,JSON.stringify(report,null,2));}
}
console.log('Raw results:',out+'/benchmark.json');
