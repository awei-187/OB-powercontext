import {fork} from 'node:child_process';
const child=fork(new URL('./check-db-child.mjs',import.meta.url),[],{stdio:['ignore','ignore','ignore','ipc'],windowsHide:true});
const timer=setTimeout(()=>{console.error('seekdb probe timed out');child.kill();process.exitCode=1;},60000);
child.on('message',m=>{clearTimeout(timer);child.kill();process.exitCode=m.exitCode;console.log('Evidence: test-results/db-probe.json');});
child.on('error',e=>{clearTimeout(timer);console.error(e.message);process.exitCode=1;});
