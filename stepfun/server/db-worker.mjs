import * as store from './db.mjs';
process.on('message',m=>{
  store.serial(async()=>{
    try {
      await store.ensureServerConnection();
      await store.init();
      let result;
      if(m.type==='health') result={ok:true,mode:store.mode,version:await store.db.execute('SELECT VERSION() AS version')};
      else result=await store[m.type](...m.args);
      process.send?.({id:m.id,result});
    } catch(e) {process.send?.({id:m.id,error:e.message});}
  });
});
