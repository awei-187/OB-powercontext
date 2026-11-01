# Reviewed PowerContext integration

Seven accepted features are integrated on `dab240063bfcfa7917898dc44da4baadb3747bd0`. Frozen v1.2.0 ancestor `9db1753434162c0aa7c9f1189a1722e617880a52` remains reachable. This branch contains CSV evidence, Pi sessions, HTTP reranking, incremental context packs, source-count triggers, query/budget evidence selection and coalesced embeddings. Withdrawal and Gaode are excluded.

Product files match their accepted source snapshots byte-for-byte after line-ending normalization. CSV tests received type-narrowing assertions; three new integration modules cover real project classes, SQLite, loopback HTTP, subprocess restart, scopes, idempotency, native processing and evidence/delta interactions. No official tests or dependency declarations were changed. The judge loads `src`; tests and this document are supporting evidence only.

## Executed checks

Windows 11, CPython 3.14.7, isolated outputs, read-only reuse of an existing dependency environment. All product imports were verified to resolve to this integration checkout. Async/native tests required the ordinary host execution context because the restricted sandbox could not initialize asyncio socketpair. No dependency installation was performed.

| Test group | Result |
| --- | --- |
| official | 84 passed |
| targeted | 660 passed |
| independent-csv | 23 passed |
| independent-rerank | 22 passed |
| independent-pi | 45 passed |
| independent-delta | 25 passed |
| independent-trigger | 6 passed |
| independent-evidence | 18 passed |
| independent-embedding | 40 passed |

These disjoint command groups reported **923 passes**. Standalone reruns of the four integration cases are not added again. The targeted group includes those cases. This is a selected regression suite, not a claim that the entire repository suite was executed.

Ruff formatting: 32 Python files passed. Project lint: 2 pre-existing diagnostics. Competition lint: 14 pre-existing diagnostics. Type check: 16 pre-existing diagnostics (7 errors, 9 warnings). Diagnostics were compared by file, rule, severity and message against the identical baseline with the same environment; no added diagnostics. `pip check`, frozen-ancestor validation and diff whitespace check passed. All 85 tracked competition files are unchanged.

`test_family_processing.py` did not collect because casbin is absent. Additional inference-adapter result: collection failed because `opentelemetry.sdk` is absent; no tests executed. No installation was attempted. `uv` and `prek` are unavailable, so the repository's full pre-commit command was not run; the targeted Ruff/format/type checks above were run directly using the existing environment. Official Linux x86_64 / Python 3.12 is unavailable locally (WSL not installed; no Docker/Podman environment found). These Windows results do not substitute for the official environment.

## Platform preflight

Platform question 600070 was identified by the parent task; the platform states eight 20-point subtasks. This delivery implements the seven accepted features listed here and makes no score claim. No new dependencies were added. Public tests use local, offline providers; private quality gates and judge authorization were not inferred from those passes.

| Feature | Reviewed contract and executable coverage | Remaining gate |
| --- | --- | --- |
| CSV | Exactly five metadata keys; encoded SourceID length <=256; exact whitespace column/key identity; whole-document validation, UTF-8 BOM, Python strict CSV parsing. Public, product, independent tests and SQLite restart row-order checks. | No private data gate claimed. |
| Pi | Control-node connectivity, complete ancestors/tool records, durable checkpoint lifecycle and rewrite failure without advancing progress. Native ingestion/restart and lossless huge-integer checks. | Uses fresh databases and final-schema restarts. No migration from earlier preview database formats. |
| HTTP rerank | Original one-based ranks across batches, global-rank tie ordering, exact response schema and one adapter request per batch; actual requests in usage. Per-request auth=None and redirects disabled. | Private 173-summary/20-query Recall@10 >=0.95 and MRR >=0.80 not run. |
| Delta | Empty/None prepared content; canonical wire encoding, Base64, SHA and complete byte accounting; independent-process reconstruction. Prefix-only protocol retained. | Private 40-turn net saving >=45%, including initial full pack, not run. Some inputs have negative savings; no universal saving guarantee. |
| Source count | Positive strict integers rejecting bool/string/float; unique scoped journal identities after each family's successful cursor; replay/receipt upgrade not recounted; lineage counted but excluded from generation evidence; count OR elapsed-time admission; Memory rechecks after one window while Topic continues accepted waves. Native workers, restart, rollback and CSV/Pi interaction tests. | Optional family-processing module cannot collect without casbin in this borrowed environment. |
| Embedding | Cache-size zero still coalesces; late callers share flights; cancellation and failure isolation; usage assigned once per actual batch retaining tokens; entire batch validated against native vector profile before publication. Official native six-scope x24 same-text test asserts four underlying batches and six subsequent cached queries add none. | No official Linux/Python 3.12 run. |
| Evidence | Default off; half-open character spans, exact citation origins and scope; budget includes policy/envelope/JSON/citations/text. Integrated prepared-context -> delta reconstruction preserves bytes, bounds, historical citations, scope and authorization after restart. | Private 48-request gate at 1400/1800 bytes, recall >=0.65 and 40% complete gold coverage, not run. |

## Provenance

CSV source commits: `559e9b04c3a0c682fd9581c320cd1c83835e8168`, `fdea2ae2400a86e4816ebffd6b875b5e0c95a4f9`. Other accepted source worktrees were uncommitted changes based on the integration baseline. Complete hashes and source statuses are retained in the local delivery manifest. The embedding snapshot includes the final unit-normalization profile repair. Full Pi patch was used without stacking its alternative incremental numeric-repair patch.

Product digest: `b70d391cc18a119b09fef94264a9a2a0013f44e1352bd2816d0da13af21d5e1d`. Definition: SHA-256 of sorted UTF-8 lines `path + NUL + file_sha256 + LF`, covering the following changed product files.

| Product file | SHA-256 |
| --- | --- |
| `src/powercontext/builtin/artifacts/memory/__init__.py` | `49719f510a1b26076a2ca4e370733452e07e3c70e31f78a0109636829338473e` |
| `src/powercontext/builtin/artifacts/memory/http_reranker.py` | `6bfec616adbafa191a00e366e996836fe83162964feb8908da1a2d5f60c5b19b` |
| `src/powercontext/builtin/inference/coalescing.py` | `1b28aaae1d99c676b93a1dee8f69f44e5c6dd271e48d44f228a72f477cd95488` |
| `src/powercontext/builtin/runtime/application.py` | `073f0811837af70db7b474d9afb27f7ca0f59e1d32b664ed3521070b84326ceb` |
| `src/powercontext/builtin/runtime/artifact_processing.py` | `8d2fc97eb281c06a790a70ee623d4b48e957be94bb0d4bb2d25e276298cb75d8` |
| `src/powercontext/builtin/runtime/composition.py` | `3736553ad507ad4adf2d11c0f1e5515779ee086ff08f1587d95a47eaea27d417` |
| `src/powercontext/builtin/runtime/config.py` | `a0bc777af7fce83daae671b88eb466be497ebe1175c6e87493fa988e87388e9a` |
| `src/powercontext/builtin/runtime/context_pack.py` | `a1cf2e34d3bd8fedfee1d4c8d7aa7cf120038b0e309a4fe1e1be5d42c0d262d7` |
| `src/powercontext/builtin/runtime/models.py` | `fff46e4e6700375a2b251d11f8ccf24f3581bd435502b40984a2689dc08024df` |
| `src/powercontext/builtin/runtime/prepared_context.py` | `9c9711ec7f1fed9a03c901c5a623217aa0f2b28c50fbe0ed77c1b746e929958d` |
| `src/powercontext/builtin/runtime/prepared_evidence.py` | `9a482c28152394d4319c42006af0a79ce245d15b8c48434e718965c47d3f02d7` |
| `src/powercontext/builtin/runtime/processing_discovery.py` | `c212d7739cdd6699dd1e1c07897986f9e47d6c8d4685dc87fa567adada950eac` |
| `src/powercontext/sources/csv_rows.py` | `aad3bef48d4fe6af9b984f8b826e035da1d0c22a0e402659b7efc4882e294f9d` |
| `src/powercontext/sources/observations.py` | `587c2f684fe4508fb79e43fe96f6b914d9c73d415df33255d41581c489d9a460` |
| `src/powercontext/sources/pi_session.py` | `c926a12dec6dc9ba78a9ba076811a7136e8643969f8be66059df24718bf4da0e` |
| `src/powercontext/sources/projections.py` | `f3c1d4548d6c2e2ec5d1254aa0cedbadad6083be9bab7542caf67ae6910bab58` |
