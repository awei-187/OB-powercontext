import { readFile, mkdir, rename, stat } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
const spec = JSON.parse(await readFile('model-manifest.json'));
const root = path.resolve('public/models', spec.repo);
const proxy = process.env.DOWNLOAD_PROXY;
for (const f of spec.files) {
  const dest = path.join(root, f.path);
  await mkdir(path.dirname(dest), { recursive: true });
  async function valid() {
    try {
      if ((await stat(dest)).size !== f.bytes) return false;
      const buf = await readFile(dest);
      return f.sha256 ? createHash('sha256').update(buf).digest('hex') === f.sha256
        : createHash('sha1').update(`blob ${buf.length}\0`).update(buf).digest('hex') === f.gitBlob;
    } catch { return false; }
  }
  if (await valid()) { console.log('verified', f.path); continue; }
  const args = ['-fL', '--retry', '2', '--connect-timeout', '30', '--max-time', '900'];
  if (proxy) args.push('--proxy', proxy);
  execFileSync('curl.exe', [...args, `https://huggingface.co/${spec.repo}/resolve/${spec.revision}/${f.path}`, '-o', dest + '.part'], { stdio: 'inherit' });
  await rename(dest + '.part', dest);
  if (!await valid()) throw Error(`Checksum mismatch: ${f.path}`);
  console.log('verified', f.path, f.bytes);
}
