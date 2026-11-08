import {test} from 'node:test';
import assert from 'node:assert/strict';
import {splitText,quality} from '../src/core.mjs';
import {readFile} from 'node:fs/promises';
test('overlapping chunks reconstruct the original without losing the tail',()=>{
  const text='甲'.repeat(221)+'终'; const parts=splitText(text,'s');
  assert.equal(parts.length,2);assert.equal(parts[0].text.length,220);assert.ok(parts[1].text.endsWith('终'));
  assert.equal(splitText('   ','s').length,0);
});
test('ranking metric penalizes missing and incorrectly ordered relevant documents',()=>{
  assert.deepEqual(quality(['a','b'],{a:2,b:1},2),{recall:1,ndcg:1});
  assert.ok(quality(['b','x'],{a:2,b:1},2).ndcg<0.5);
});
test('fixed fixture has unique IDs and valid judgments',async()=>{
  const f=JSON.parse(await readFile('data/fixture.json'));const ids=new Set(f.documents.map(d=>d.id));assert.equal(ids.size,100);
  for(const q of f.queries)for(const id of Object.keys(q.relevance))assert.ok(ids.has(id));
});
