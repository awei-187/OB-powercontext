import { mkdir, readFile, writeFile, rename } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import path from 'node:path';
export const revision = '469a55dc84ea7a9e077161a8b454871a9adaff35';
export const baseUrl = `https://oceanbase-seekdb-builds.s3.ap-southeast-1.amazonaws.com/js-bindings/all_commits/${revision}`;
const platform = `${process.platform}-${process.arch}`;
const dir = path.resolve('.cache/bindings', revision, platform);
await mkdir(dir, { recursive: true });
const file = `seekdb-js-bindings-${platform}.zip`;
if(platform!=='win32-x64') throw Error('This verified bootstrap is for Windows x64. Use a local seekdb server on other platforms.');
const expected='40641c08ab488aff9ca278de814d6558169194cc75d61d51b102317732e0b796';
const dest=path.join(dir,file);
const hash=b=>createHash('sha256').update(b).digest('hex');
let verified=false;try {verified=hash(await readFile(dest))===expected;} catch {}
const args = ['-fL', '--retry', '2', '--continue-at', '-', '--speed-time', '30', '--speed-limit', '1024', '--connect-timeout', '30', '--max-time', '900'];
if (process.env.DOWNLOAD_PROXY) args.push('--proxy', process.env.DOWNLOAD_PROXY);
if(!verified) {
  execFileSync('curl.exe', [...args, `${baseUrl}/${file}`, '-o', dest+'.part'], { stdio: 'inherit' });
  if(hash(await readFile(dest+'.part'))!==expected) throw Error('Native artifact checksum mismatch');
  await rename(dest+'.part',dest);
}
const buf = await readFile(dest);
const evidence = { url: `${baseUrl}/${file}`, bytes: buf.length, sha256: createHash('sha256').update(buf).digest('hex') };
await writeFile('.cache/bindings/download.json', JSON.stringify(evidence, null, 2));
console.log(evidence);
