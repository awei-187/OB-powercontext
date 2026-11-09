const w=new Worker('/assets/embed-worker.js',{type:'module'});let id=0;const pending=new Map();
w.onmessage=({data})=>{if(data.event)return;const p=pending.get(data.id);if(p){pending.delete(data.id);data.error?p.reject(Error(data.error)):p.resolve(data.result);}};
w.onerror=e=>{for(const p of pending.values())p.reject(Error(e.message));pending.clear();};
window.rpc=(type,payload)=>new Promise((resolve,reject)=>{pending.set(++id,{resolve,reject});w.postMessage({id,type,payload});});
