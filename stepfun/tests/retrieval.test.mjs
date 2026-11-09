import {test} from 'node:test';import assert from 'node:assert/strict';
import {defaultStrategy,scoreFusionSql,variants} from '../server/retrieval.mjs';
test('old indexes retain baseline behavior; max_word indexes opt into the new scorer',()=>{
  assert.equal(defaultStrategy({schema:{fulltextIndex:{analyzer:'ik'}}}),'baseline-v1');
  assert.equal(defaultStrategy({schema:{fulltextIndex:{analyzer:'ik',properties:{ik_mode:'max_word'}}}}),'quality-v2');
});
test('new hybrid SQL keeps vector, fulltext and fusion inside the database',()=>{
  const sql=scoreFusionSql('`test_table`',variants['quality-v2']);
  assert.match(sql,/cosine_distance/);assert.match(sql,/MATCH\(document\) AGAINST/);assert.match(sql,/FULL JOIN/);assert.match(sql,/OVER\(\)/);
  assert.equal((sql.match(/\?/g)||[]).length,4);
});
