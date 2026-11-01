# Challenge 11: native seekdb test candidate

Candidate `4096023bd521b7f2064ee2e0c412d5e67bea49e9` passed the unchanged official
native hybrid test on AMD/Linux on 2026-11-01. This is one native acceptance test,
not a formal score or proof of the full quality/latency workload. This local
documentation update is not committed or pushed.

## AMD/Linux acceptance update (2026-11-01)

The parent thread reported the completed AMD worker run: Python 3.12.3 and the
fixed `pylibseekdb==1.3.0.post4`; **1 passed, exit 0**, pytest 15.22 seconds,
15.99 seconds total, OOM count 0. Source diff was 0. The test executed the real
hybrid query, checked its results, and passed both EXPLAIN assertions:
`TEXT RETRIEVAL SCAN` and `VECTOR INDEX`. Its tagged, repeated, scope, current-head,
revision, inactive/reactivation, and single-channel assertions also completed.
This is parent/AMD-worker supplied evidence, not a rerun by this local task.

The successful run used `TMPDIR=/tmp/p11.skki3a4u` and a 56-byte absolute database
path. A separate 54-byte-path aopen/close probe succeeded; a 98-byte-path probe
with the same imports/profile wrapper, tmpfs and fixed wheel waited in aopen
until the 30-second process timeout. Earlier official runs likewise stalled
before SQLAlchemy and the candidate SQL; one stage trace showed a live event
loop while aopen awaited asyncio.to_thread.

Read-only inspection of the fixed wheel's libseekdb.so found the socket template
`%s/run/sql.sock`. Linux sockaddr_un.sun_path has 108 bytes; a 98-byte database
path plus this 13-byte suffix is 111 bytes, while 54/56-byte paths yield 67/69.
These observations support a Unix-socket path-length explanation. The exact
fixed native source revision and failing connect syscall were not established,
so this is not a claim that the formal competition platform had the same cause.
Current upstream main contains a socket-alias implementation and must not be
treated as identical to the fixed wheel.

For reproduction, use a fresh task-owned directory with a short real absolute
path on the approved local mount, and set TMPDIR only for the test process.
Keep the same product, official test and dependency pins. A symlink may be
expanded by the profile's Path.resolve(), so it is not a reliable shortening.
The initial NFS/block-manager IO error and subsequent long-path startup waits
remain recorded as failed/timeout attempts; they are not SQL execution failures.

Sources: [Linux unix(7)](https://man7.org/linux/man-pages/man7/unix.7.html),
[current upstream binding](https://github.com/oceanbase/seekdb-bindings/blob/main/lib/src/seekdb.c).
The fixed wheel SHA256 is
`ee2700b5990e5e4f11c4b980b182cf7b066817ddd91c7b876152b88a7c24a7ea`.

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

The historical Windows official hybrid attempt failed with `SeekDBUnavailableError`
because `pylibseekdb` is unavailable there. The later AMD official native test
passed as recorded above. Separate native process-restart tests and the full
quality/latency workload have not been reported as executed.

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

Remaining validation scope (do not infer completion from one official test):

1. The official derived-table UNION and both required EXPLAIN assertions now
   pass on the pinned AMD/Linux environment. Broader plan coverage remains useful.
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
