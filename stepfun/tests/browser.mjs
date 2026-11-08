import {chromium} from 'playwright-core';import {mkdir,writeFile,readFile} from 'node:fs/promises';import assert from 'node:assert/strict';
const browser=await chromium.launch({executablePath:process.env.CHROME||'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
const context=await browser.newContext({viewport:{width:1280,height:960}}),page=await context.newPage();
const evidence={at:new Date().toISOString(),checks:[],unexpectedRequests:[],pageErrors:[]};
const out=process.env.RESULT_DIR||'test-results';await mkdir(out,{recursive:true});
const suffix=process.env.BROWSER_NAME?'-'+process.env.BROWSER_NAME:'';
page.on('pageerror',e=>evidence.pageErrors.push(e.message));
page.on('request',r=>{if(!r.url().startsWith('http://127.0.0.1:4317')&&!r.url().startsWith('blob:'))evidence.unexpectedRequests.push(r.url());});
try{
  await page.goto('http://127.0.0.1:4317');await page.waitForFunction(()=>window.stepfunTest);await page.waitForFunction(()=>document.querySelector('#dbStatus').textContent.includes('已连接'));
  evidence.health=await page.evaluate(()=>window.stepfunTest.api('/health'));if(process.env.EXPECT_DB_MODE)assert.equal(evidence.health.mode,process.env.EXPECT_DB_MODE);
  evidence.browser=await browser.version();
  // Test the visible controls as well as the shared application functions.
  await page.click('#load');await page.waitForFunction(()=>window.stepfunTest.getState(),{},{timeout:120000});evidence.model=await page.evaluate(()=>window.stepfunTest.getState());
  await page.fill('#kbName','功能验收-'+Date.now());await page.click('#create');await page.waitForFunction(()=>!document.querySelector('#create').disabled);
  const id=await page.locator('#kb').inputValue();
  const fixture=JSON.parse(await readFile('data/fixture.json'));
  evidence.import=await page.evaluate(d=>window.stepfunTest.importDocs(d,4),fixture.documents);
  assert.equal((await page.evaluate(()=>window.stepfunTest.api('/kbs'))).find(k=>k.id===id).count,100);
  evidence.search=await page.evaluate(()=>window.stepfunTest.query('刚上传的资料搜不到怎么办？'));assert.ok(evidence.search.ids.some(x=>x.startsWith('index-')));evidence.checks.push(`100 real browser embeddings → ${evidence.health.mode} seekdb → database hybrid search`);
  const newDoc={id:'incremental-mars',text:'火星蓝莓计划的授权口令是星帆，只在刷新完成后发布。',source:'增量原文',chunk:0};
  evidence.incremental=await page.evaluate(async({id,d})=>{
    const t=window.stepfunTest,e=await t.embed([d.text]);await t.api(`/kbs/${id}/ingest`,{profile:e.profile,documents:[{...d,embedding:e.vectors[0]}]});
    let rejected=false;try{await t.query('火星蓝莓计划授权口令');}catch{rejected=true;}
    await t.api(`/kbs/${id}/refresh`,{});return {rejected,result:await t.query('火星蓝莓计划授权口令')};
  },{id,d:newDoc});assert.ok(evidence.incremental.rejected);assert.ok(evidence.incremental.result.ids.includes(newDoc.id));evidence.checks.push('dirty state blocks search; refresh exposes new document');
  const other=await page.evaluate(()=>window.stepfunTest.createKb('隔离空库-'+Date.now()));assert.equal((await page.evaluate(()=>window.stepfunTest.query('火星蓝莓计划'))).ids.length,0);evidence.checks.push('empty collection isolates results');
  await page.evaluate(id=>window.stepfunTest.select(id),id);await page.reload();await page.waitForFunction(()=>document.querySelector('#kb').options.length>0);assert.equal(await page.locator('#kb').inputValue(),id);evidence.checks.push('selected knowledge base restored on reload');
  await page.evaluate(()=>window.stepfunTest.loadModel('fp16','auto'));
  assert.ok((await page.evaluate(()=>window.stepfunTest.query('火星蓝莓计划授权口令'))).ids.includes(newDoc.id));
  await page.evaluate(d=>window.stepfunTest.importDocs(d,4),fixture.documents);
  assert.equal((await page.evaluate(()=>window.stepfunTest.api('/kbs'))).find(k=>k.id===id).count,101);evidence.checks.push('repeated import upserts stable IDs');
  await page.fill('#query','新增文档 索引刷新');await page.click('#search');await page.waitForFunction(()=>!document.querySelector('#search').disabled);
  await page.screenshot({path:`${out}/app-desktop${suffix}.png`,fullPage:true});
  await page.setViewportSize({width:390,height:844});await page.screenshot({path:`${out}/app-mobile${suffix}.png`,fullPage:true});
  assert.deepEqual(evidence.unexpectedRequests,[]);assert.deepEqual(evidence.pageErrors,[]);
  evidence.ok=true;
}catch(e){evidence.error=e.stack;process.exitCode=1;}finally{
  await writeFile(`${out}/browser${suffix}.json`,JSON.stringify(evidence,null,2));await browser.close();console.log(JSON.stringify(evidence,null,2));
}
