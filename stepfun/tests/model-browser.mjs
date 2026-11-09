import {chromium} from 'playwright-core';import {readFile,writeFile,mkdir} from 'node:fs/promises';
const browser=await chromium.launch({executablePath:process.env.CHROME||'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
const page=await browser.newPage();page.on('console',m=>console.log(m.type(),m.text().slice(0,500)));page.on('pageerror',e=>console.error('pageerror',e.message));
try {
  await page.goto('http://127.0.0.1:4317/model-test.html');await page.waitForFunction(()=>window.rpc);
  const spec=JSON.parse(await readFile('model-manifest.json'));
  const state=await page.evaluate(spec=>window.rpc('load',{dtype:'fp16',backend:'auto',spec}),spec);console.log(JSON.stringify(state));
  const result=await page.evaluate(()=>window.rpc('embed',{texts:['新增文档后要刷新索引','图书馆三十天归还']}));
  console.log('vectors',result.vectors.map(x=>x.length),result.ms);
  await mkdir('test-results',{recursive:true});await writeFile('test-results/model-browser.json',JSON.stringify({browser:await browser.version(),state,embeddingMs:result.ms},null,2));
}finally{await browser.close();}
