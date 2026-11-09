import {fork} from 'node:child_process';
let child,seq=0;const pending=new Map();
function start() {
  if(child)return;
  child=fork(new URL('./db-worker.mjs',import.meta.url),[],{execPath:process.env.SEEKDB_NODE || process.execPath,stdio:['ignore','ignore','pipe','ipc'],windowsHide:true});
  child.stderr.on('data',d=>process.stderr.write(d));
  child.on('message',m=>{const p=pending.get(m.id);if(p){clearTimeout(p.timer);pending.delete(m.id);m.error?p.reject(Error(m.error)):p.resolve(m.result);}});
  child.on('exit',()=>{child=null;for(const p of pending.values()){clearTimeout(p.timer);p.reject(Error('seekdb 进程退出，请查看本机数据库配置'));}pending.clear();});
}
export function call(type,...args) {
  start();return new Promise((resolve,reject)=>{
    const id=++seq,timer=setTimeout(()=>{child?.kill();},Number(process.env.SEEKDB_TIMEOUT_MS || 60000));
    pending.set(id,{resolve,reject,timer}); child.send({id,type,args});
  });
}
export function close(){child?.kill();}
