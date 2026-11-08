import {chromium} from 'playwright-core';import {readFile,writeFile} from 'node:fs/promises';
const spec=JSON.parse(await readFile('model-manifest.json')),f=JSON.parse(await readFile('data/fixture.json'));
const useInstruction=process.env.QUERY_INSTRUCTION!=='none';
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
const page=await browser.newPage();
try {
  await page.goto('http://127.0.0.1:4317/model-test.html');await page.waitForFunction(()=>window.rpc);
  const state=await page.evaluate(spec=>window.rpc('load',{spec,dtype:'fp16',backend:'auto'}),spec),queries=[];
  for(const q of f.queries){const e=await page.evaluate(({text,useInstruction})=>window.rpc('embed',{texts:[text],query:useInstruction}),{text:q.text,useInstruction});queries.push({id:q.id,text:q.text,...e});}
  const file=useInstruction?'query-vectors.json':'query-vectors-no-instruction.json';
  await writeFile('test-results/retrieval-quality/'+file,JSON.stringify({browser:await browser.version(),useInstruction,state,queries},null,2));console.log(state.backend,state.adapter);
} finally {await browser.close();}
