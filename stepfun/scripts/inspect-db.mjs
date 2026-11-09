import {fork} from 'node:child_process';import {readFile,writeFile} from 'node:fs/promises';
import assert from 'node:assert/strict';
const out=process.env.RESULT_DIR||'test-results';const id=process.argv[2] || JSON.parse(await readFile(out+'/browser.json')).import.kb;
const child=fork(new URL('../server/db-worker.mjs',import.meta.url),[],{stdio:['ignore','ignore','ignore','ipc'],windowsHide:true});
const timer=setTimeout(()=>{child.kill();process.exitCode=1;},60000);
child.on('message',async m=>{
  try {
    if(m.error)throw Error(m.error);
    assert.equal(m.result.count,101);
    assert.equal(m.result.stored.embeddings.length,2);
    for(const v of m.result.stored.embeddings){assert.equal(v.length,512);assert.ok(Math.abs(Math.sqrt(v.reduce((s,x)=>s+x*x,0))-1)<.02);}
    assert.ok(m.result.stored.documents.some(t=>t.includes('火星蓝莓')));
    m.persistenceVerified=true;
  }catch(e){m.verificationError=e.message;process.exitCode=1;}
  await writeFile(out+'/storage-inspection.json',JSON.stringify(m,null,2));clearTimeout(timer);child.kill();
});
child.send({id:1,type:'inspect',args:[id]});
