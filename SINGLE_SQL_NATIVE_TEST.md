# Challenge 11: native seekdb test candidate

This branch is a candidate for independent AMD/Linux validation, not a validated
competition deliverable. Do not interpret publication as native acceptance or a
score claim.

The parent is the scored integration commit
`764028023ef6e1713b93f2370c6c8d04d739ef0e`. It retains the official competition
ancestor `dab240063bfcfa7917898dc44da4baadb3747bd0` and frozen product ancestor
`9db1753434162c0aa7c9f1189a1722e617880a52`.

## Change

`SeekDBMemoryIndex` fetches bounded FTS and vector candidates using one statement
with two filtered derived tables and `UNION ALL`. All request values are bound.
The result is demultiplexed into existing search channels for admission and RRF.
Current-head checks, incremental projection semantics, transactional writes, and
single-channel strategies remain in their existing paths. Runtime composition
selects the new strategy only for seekdb with an embedding model.

No schema, dependency, official test, or evaluation protocol changes are included.

## Existing evidence

On Windows/Python 3.14, the implementation's support suite passed 70 tests and
skipped one native test. Static lint/format checks passed; type checking reported
no errors and three existing deprecation warnings. Independent review reproduced
70 passed/1 skipped, added 18 passing relation/parameter/routing checks, and ran
eight passing official embedding compatibility tests. These support groups do
not prove native SQL, index use, or retrieval quality.

The unchanged official hybrid test failed with `SeekDBUnavailableError` because
`pylibseekdb` is unavailable in that Windows environment. Native SQL/EXPLAIN,
seekdb process restart, and the full quality/latency workload have not run.

## Native validation

Use an isolated Linux x86_64/Python 3.12 environment and the unchanged competition
dependency pins, including `pylibseekdb==1.3.0.post4`. Use a fresh task-owned
temporary directory and database; do not connect to an existing service.

From the repository root:

```sh
make -C competition install
make -C competition check-baseline
make -C competition test-hybrid
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  competition/.venv/bin/python -m pytest -q -p pytest_asyncio.plugin -p no:cacheprovider \
  tests/builtin/persistence/test_seekdb_memory_index.py \
  tests/e2e/test_seekdb_hybrid_restart.py
```

Record actual driver SQL and parameters, EXPLAIN plans, test outcomes, and exact
Python/dependency versions. A skipped native case is not acceptance.

Prioritize these unresolved native risks:

1. Derived-table UNION must execute on the pinned engine and EXPLAIN must show
   both `TEXT RETRIEVAL SCAN` and `VECTOR INDEX`.
2. Tagged hybrid ANN uses a correlated COUNT predicate and APPROXIMATE. Test
   all/any/no-match filters, including selective positive tags whose qualifying
   neighbors lie beyond the unfiltered top K. Verify both plans and candidate
   counts; the old vector-only tagged strategy uses exact search.
3. Outer identity sorting stabilizes the bounded ANN result, not its cutoff
   membership. Test more equal-distance candidates than the candidate budget,
   repeated queries, and restart behavior.
4. Run the required same-database frozen-path comparison on 173 documents,
   20 queries and three scopes with fixed 384-dimensional embeddings. Verify
   each query's Recall@10/MRR@10 does not regress, mean recall is at least 0.95,
   full Memory.search p50 is at most 500 ms, and all identities, current versions,
   exact bodies and channels are valid and unique.

The included restart test covers real persistence in separate processes, with
SQLite and seekdb reported separately. Its native plan loop covers untagged and
missing-tag cases; selective positive-tag plan testing remains an additional
required validation. Synthetic examples do not establish formal workload results.
