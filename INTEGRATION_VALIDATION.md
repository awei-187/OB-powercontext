# Reviewed PowerContext integration

Eight accepted features are integrated on `dab240063bfcfa7917898dc44da4baadb3747bd0`. Frozen v1.2.0 ancestor `9db1753434162c0aa7c9f1189a1722e617880a52` remains reachable. This branch contains CSV evidence, Pi sessions, HTTP reranking, incremental context packs, source-count triggers, query/budget evidence selection, coalesced embeddings and source withdrawal/restoration. Gaode is excluded. The seven-feature checkpoint remains in history as `85d39fe7f4edacd6a8e829b9597fab5ca681f876`.

Product files match their accepted source snapshots after line-ending normalization, except for two shared files combined by applying non-overlapping reviewed patch hunks (`application.py`, `composition.py`) and 16 SQLite SQL line wraps that remove new competition E501 diagnostics. Parsed Python AST equality after SQL-whitespace normalization verifies that wrapping changed no SQL tokens or predicates. CSV tests received type-narrowing assertions; four new integration modules cover real project classes, SQLite, loopback HTTP, subprocess restart, scopes, idempotency, native processing and evidence/delta/lifecycle interactions. No official tests or dependency declarations were changed. The judge loads `src`; tests and this document are supporting evidence only.

## Executed checks

Windows 11, CPython 3.14.7, isolated outputs, read-only reuse of an existing dependency environment. All product imports were verified to resolve to this integration checkout. Async/native tests required the ordinary host execution context because the restricted sandbox could not initialize asyncio socketpair. No dependency installation was performed.

| Test group | Result |
| --- | --- |
| official | 88 passed |
| independent-csv | 23 passed |
| independent-rerank | 22 passed |
| independent-pi | 45 passed |
| independent-delta | 25 passed |
| independent-trigger | 6 passed |
| independent-evidence | 18 passed |
| independent-embedding | 40 passed |
| independent-withdrawal | 15 passed |
| targeted-distinct-after-focused-rerun | 760 passed |

The final deduplicated result is **1042 passed, 27 skipped, 0 unresolved failures**. The complete targeted command initially reported 759 passed, 1 failed and 27 skipped. Its one failure was a new test fixture reading `MemoryEntryRecord.sources` instead of `MemoryEntryRecord.entry.sources`; after correcting that field access, both lifecycle integration cases passed in a focused rerun. Product code did not change for this fix. The targeted count above includes each case once, with the repaired case replaced by its passing result; it does not claim that the original command exited successfully. Other standalone reruns are not added again. Two additional SQL scripts passed without being counted as pytest cases. This is a selected regression suite, not a claim that the entire repository suite was executed.

Ruff formatting: 40 Python files passed. Project lint: 2 pre-existing diagnostics. Competition lint: 14 pre-existing diagnostics. Type check: 16 pre-existing diagnostics (7 errors, 9 warnings). Diagnostics were compared by file, rule, severity and message against the identical baseline with the same environment; no added diagnostics. `pip check`, frozen-ancestor validation and diff whitespace check passed. All 85 tracked competition files are unchanged.

`test_family_processing.py` did not collect because casbin is absent. Additional inference-adapter result: collection failed because `opentelemetry.sdk` is absent; no tests executed. No installation was attempted. `uv` and `prek` are unavailable, so the repository's full pre-commit command was not run; the targeted Ruff/format/type checks above were run directly using the existing environment. Official Linux x86_64 / Python 3.12 is unavailable locally (WSL not installed; no Docker/Podman environment found). These Windows results do not substitute for the official environment.

## Platform preflight

Platform question 600070 was identified by the parent task; the platform states eight 20-point subtasks. This delivery implements the eight accepted features listed here and makes no score claim. No new dependencies were added. Public tests use local, offline providers; private quality gates and judge authorization were not inferred from those passes.

| Feature | Reviewed contract and executable coverage | Remaining gate |
| --- | --- | --- |
| CSV | Exactly five metadata keys; encoded SourceID length <=256; exact whitespace column/key identity; whole-document validation, UTF-8 BOM, Python strict CSV parsing. Public, product, independent tests and SQLite restart row-order checks. | No private data gate claimed. |
| Pi | Control-node connectivity, complete ancestors/tool records, durable checkpoint lifecycle and rewrite failure without advancing progress. Native ingestion/restart and lossless huge-integer checks. | Uses fresh databases and final-schema restarts. No migration from earlier preview database formats. |
| HTTP rerank | Original one-based ranks across batches, global-rank tie ordering, exact response schema and one adapter request per batch; actual requests in usage. Per-request auth=None and redirects disabled. | Private 173-summary/20-query Recall@10 >=0.95 and MRR >=0.80 not run. |
| Delta | Empty/None prepared content; canonical wire encoding, Base64, SHA and complete byte accounting; independent-process reconstruction. Prefix-only protocol retained. | Private 40-turn net saving >=45%, including initial full pack, not run. Some inputs have negative savings; no universal saving guarantee. |
| Source count | Positive strict integers rejecting bool/string/float; unique scoped journal identities after each family's successful cursor; replay/receipt upgrade not recounted; lineage counted but excluded from generation evidence; count OR elapsed-time admission; Memory rechecks after one window while Topic continues accepted waves. Native workers, restart, rollback and CSV/Pi interaction tests. | Optional family-processing module cannot collect without casbin in this borrowed environment. |
| Embedding | Cache-size zero still coalesces; late callers share flights; cancellation and failure isolation; usage assigned once per actual batch retaining tokens; entire batch validated against native vector profile before publication. Official native six-scope x24 same-text test asserts four underlying batches and six subsequent cached queries add none. | No official Linux/Python 3.12 run. |
| Evidence | Default off; half-open character spans, exact citation origins and scope; budget includes policy/envelope/JSON/citations/text. Integrated prepared-context -> delta reconstruction preserves bytes, bounds, historical citations, scope and authorization after restart. | Private 48-request gate at 1400/1800 bytes, recall >=0.65 and 40% complete gold coverage, not run. |
| Withdrawal | Per-node all/any eligibility remains independent of native alias OR; scope and exact reference revision constrain support. Native recall filters before candidate limits; audit reads remain available. Real SQLite rollback/replay/restart and exact-identity SQL checks passed. CSV/Pi lifecycle events do not add journal identities or advance processing generations; selected evidence and delta track withdrawal/restoration across processes. | 27 live OceanBase/seekdb parameter cases skipped. No live OceanBase backend run; optional topic-memory application module lacks platformdirs. Registered Memory bodies may not be externally rewritten or compacted. |

## Provenance

CSV source commits: `559e9b04c3a0c682fd9581c320cd1c83835e8168`, `fdea2ae2400a86e4816ebffd6b875b5e0c95a4f9`. Other accepted source worktrees were uncommitted changes based on the integration baseline. Complete hashes and source statuses are retained in the local delivery manifest. The embedding snapshot includes the final unit-normalization profile repair. Full Pi patch was used without stacking its alternative incremental numeric-repair patch.

Product digest: `bb8409d920c53b83f15fabc56faf917b6241a6a01aa6b3a6226e63a1bb3219cc`. Definition: SHA-256 of sorted UTF-8 lines `path + NUL + file_sha256 + LF`, covering the following changed product files.

| Product file | SHA-256 |
| --- | --- |
| `src/powercontext/builtin/artifacts/memory/__init__.py` | `49719f510a1b26076a2ca4e370733452e07e3c70e31f78a0109636829338473e` |
| `src/powercontext/builtin/artifacts/memory/http_reranker.py` | `6bfec616adbafa191a00e366e996836fe83162964feb8908da1a2d5f60c5b19b` |
| `src/powercontext/builtin/inference/coalescing.py` | `1b28aaae1d99c676b93a1dee8f69f44e5c6dd271e48d44f228a72f477cd95488` |
| `src/powercontext/builtin/persistence/oceanbase/topic_memory_index.py` | `29d46e39fd953b0a70d6158eb82fb2d96f3a05f60f9242723cdb6727dcc4cb61` |
| `src/powercontext/builtin/persistence/sqlite/topic_memory_index.py` | `5037a0cb9191da4d6fe117e3f3c939b3c79cc1cb7133f163366c3ef05bf21c0a` |
| `src/powercontext/builtin/persistence/tables.py` | `3741a64fa43cc593a9906fa883c1a465b175937c584fc780af4d1175bf7c173d` |
| `src/powercontext/builtin/persistence/topic_memory_index.py` | `d7c4b76b10f0f66eb7537d1beac4b904201a4c99d0b43f48bfaca1ec75375c94` |
| `src/powercontext/builtin/runtime/application.py` | `29fa6e7e7c892aced5108fc9f269531208c8dfbc578c0c62faf06e4d0320bfda` |
| `src/powercontext/builtin/runtime/artifact_processing.py` | `8d2fc97eb281c06a790a70ee623d4b48e957be94bb0d4bb2d25e276298cb75d8` |
| `src/powercontext/builtin/runtime/composition.py` | `213285fc8555bea583112f0f781c46556d37d1e32641ba5411a1778869610c25` |
| `src/powercontext/builtin/runtime/config.py` | `a0bc777af7fce83daae671b88eb466be497ebe1175c6e87493fa988e87388e9a` |
| `src/powercontext/builtin/runtime/context_pack.py` | `a1cf2e34d3bd8fedfee1d4c8d7aa7cf120038b0e309a4fe1e1be5d42c0d262d7` |
| `src/powercontext/builtin/runtime/models.py` | `fff46e4e6700375a2b251d11f8ccf24f3581bd435502b40984a2689dc08024df` |
| `src/powercontext/builtin/runtime/prepared_context.py` | `9c9711ec7f1fed9a03c901c5a623217aa0f2b28c50fbe0ed77c1b746e929958d` |
| `src/powercontext/builtin/runtime/prepared_evidence.py` | `9a482c28152394d4319c42006af0a79ce245d15b8c48434e718965c47d3f02d7` |
| `src/powercontext/builtin/runtime/processing_discovery.py` | `c212d7739cdd6699dd1e1c07897986f9e47d6c8d4685dc87fa567adada950eac` |
| `src/powercontext/builtin/runtime/source_lifecycle.py` | `500ab5a4acc3067755a5403f7b8cc9b77ce01bfcb3c3e0a75bb2cd08d254d44a` |
| `src/powercontext/sources/csv_rows.py` | `aad3bef48d4fe6af9b984f8b826e035da1d0c22a0e402659b7efc4882e294f9d` |
| `src/powercontext/sources/observations.py` | `587c2f684fe4508fb79e43fe96f6b914d9c73d415df33255d41581c489d9a460` |
| `src/powercontext/sources/pi_session.py` | `c926a12dec6dc9ba78a9ba076811a7136e8643969f8be66059df24718bf4da0e` |
| `src/powercontext/sources/projections.py` | `f3c1d4548d6c2e2ec5d1254aa0cedbadad6083be9bab7542caf67ae6910bab58` |
