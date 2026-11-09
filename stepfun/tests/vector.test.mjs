import {test} from 'node:test';import assert from 'node:assert/strict';
import {vector,profile,validateProfile} from '../server/db.mjs';
test('reject malformed client embeddings at the database boundary',()=>{
  const v=Array(512).fill(0);v[0]=1;assert.equal(vector(v),v);
  assert.throws(()=>vector(v.slice(1)));assert.throws(()=>vector(Array(512).fill(0)));
  const bad=[...v];bad[10]=Infinity;assert.throws(()=>vector(bad));
});
test('require the exact model space while accepting reordered JSON keys',()=>{
  const p=profile('fp16');assert.doesNotThrow(()=>validateProfile(Object.fromEntries(Object.entries(p).reverse()),'fp16'));
  assert.throws(()=>validateProfile(p,'fp32'));assert.throws(()=>validateProfile({...p,revision:'other'},'fp16'));
});
