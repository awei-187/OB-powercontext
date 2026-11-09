import {fork} from 'node:child_process';import {readFile,writeFile} from 'node:fs/promises';import {createHash} from 'node:crypto';import assert from 'node:assert/strict';
const report=JSON.parse(await readFile('test-results/retrieval-quality/final/comparison.json')),snapshot=JSON.parse(await readFile('test-results/retrieval-quality/baseline-v1/snapshot.json'));
assert.equal(createHash('sha256').update(await readFile('data/fixture.json')).digest('hex'),snapshot.hashes['data/fixture.json']);
assert.equal(createHash('sha256').update(await readFile('test-results/benchmark.json')).digest('hex'),snapshot.hashes['test-results/benchmark.json']);
const child=fork(new URL('../server/db-worker.mjs',import.meta.url),[],{stdio:['ignore','ignore','ignore','ipc'],windowsHide:true});
let seq=0;const pending=new Map();child.on('message',m=>{const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(Error(m.error)):p.resolve(m.result);});
const call=(type,...args)=>new Promise((resolve,reject)=>{pending.set(++seq,{resolve,reject});child.send({id:seq,type,args});});
const timer=setTimeout(()=>{child.kill();process.exitCode=1;},60000);
try{
  const before=report.cases[0].kb,after=report.upgradedKb;
  const identical=await call('verifyEquivalent',before,after);assert.equal(identical.count,100);
  const baseline=await call('inspect',before),optimized=await call('inspect',after);
  assert.match(JSON.stringify(baseline.schema),/smart/);assert.match(JSON.stringify(optimized.schema),/max_word/);
  await writeFile('test-results/retrieval-quality/final/data-integrity.json',JSON.stringify({fixtureUnchanged:true,originalBenchmarkUnchanged:true,identical,baselineSchema:baseline.schema,optimizedSchema:optimized.schema,ok:true},null,2));
  console.log('Original corpus, labels, baseline results, and both collections\' stored text/metadata/vectors: unchanged');
}finally{clearTimeout(timer);child.kill();}
