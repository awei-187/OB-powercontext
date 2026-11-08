import {chromium} from 'playwright-core';import {writeFile,readFile,mkdir} from 'node:fs/promises';import assert from 'node:assert/strict';
const fixture=JSON.parse(await readFile('data/fixture.json')),records=[];
const out=process.env.RESULT_DIR||'test-results';await mkdir(out,{recursive:true});
for(const kind of ['no-adapter-fp16','model-file-failure']) {
  const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:kind==='no-adapter-fp16'?['--disable-gpu','--disable-webgpu']:[]});
  const context=await browser.newContext(),page=await context.newPage();
  // Controlled initialization fault: abort only FP16 model fetch; the FP32 WASM model runs normally.
  if(kind==='model-file-failure')await context.route('**/onnx/model_fp16.onnx',r=>r.abort('failed'));
  try{
    await page.goto('http://127.0.0.1:4317');await page.waitForFunction(()=>window.stepfunTest);
    const health=await page.evaluate(()=>window.stepfunTest.api('/health'));if(process.env.EXPECT_DB_MODE)assert.equal(health.mode,process.env.EXPECT_DB_MODE);
    const state=await page.evaluate(()=>window.stepfunTest.loadModel('fp16','auto'));
    assert.equal(state.backend,'wasm');assert.equal(state.dtype,'fp32');assert.ok(state.fallbackReason);
    await page.evaluate(name=>window.stepfunTest.createKb(name),'降级验证-'+kind+'-'+Date.now());
    const imported=await page.evaluate(d=>window.stepfunTest.importDocs(d,4),fixture.documents.slice(0,5));
    const result=await page.evaluate(()=>window.stepfunTest.query('索引刷新'));
    assert.ok(result.ids.length);records.push({kind,health,state,imported,result,ok:true});
  }catch(e){records.push({kind,error:e.stack});process.exitCode=1;}finally{await browser.close();}
}
await writeFile(out+'/'+(process.env.FALLBACK_RESULT||'fallback.json'),JSON.stringify(records,null,2));console.log(records.map(x=>({kind:x.kind,ok:x.ok,error:x.error,backend:x.state?.backend,reason:x.state?.fallbackReason})));
