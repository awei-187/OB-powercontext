import {chromium} from 'playwright-core';import {readFile,writeFile} from 'node:fs/promises';import assert from 'node:assert/strict';
const previous=JSON.parse(await readFile('test-results/browser.json'));
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
const page=await browser.newPage({viewport:{width:1280,height:1000}});
try{
  await page.goto('http://127.0.0.1:4317');await page.waitForFunction(()=>window.stepfunTest);await page.waitForFunction(()=>document.querySelector('#kb').options.length>0);
  await page.evaluate(id=>window.stepfunTest.select(id),previous.import.kb);
  const state=await page.evaluate(()=>window.stepfunTest.loadModel('fp16','auto'));
  const result=await page.evaluate(()=>window.stepfunTest.query('火星蓝莓计划授权口令'));
  assert.ok(result.ids.includes('incremental-mars'));
  await page.fill('#query','新增文档 索引刷新');await page.click('#search');await page.waitForFunction(()=>!document.querySelector('#search').disabled);
  await page.screenshot({path:'test-results/app-final.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:'test-results/app-final-mobile.png',fullPage:true});
  await writeFile('test-results/persistence-ui.json',JSON.stringify({afterServiceRestart:true,state,result,ok:true},null,2));
  console.log('Persistence after service restart: passed');
}finally{await browser.close();}
