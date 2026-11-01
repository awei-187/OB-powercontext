Historical checkpoint: current PDF + embedding candidate validation is in [PDF_EMBEDDING_VALIDATION.md](PDF_EMBEDDING_VALIDATION.md). The results and pending items below describe the earlier checkpoint only.

# Embedding contract correction: local checkpoint

This uncommitted candidate is based on published commit `764028023ef6e1713b93f2370c6c8d04d739ef0e`. No commit, push, platform submission, repository visibility or permission change was performed for this checkpoint. PDF/question 4 remains pending independent acceptance; question 11 is not included because native validation lacks pylibseekdb.

The generic coalescing wrapper preserves successful provider vectors and usage, including values that downstream Memory would reject. Vector-count mismatches and actual provider errors still fail their shared batch. Each returned vector is considered independently for LRU admission: a profile-incompatible value is returned without caching, while compatible neighbors retain their cache entries. Retrying the incompatible text does not recompute cached neighbors. Cache size zero, late shared waiters, cancellation, exact ordering, duplicate positions and per-batch token usage remain covered.

Source: accepted `contract-fix.patch`, SHA-256 `c3320cc915c65113b9691b549f4115228aa8c55ee3281de1aed0c0fce17150ef`. Candidate `coalescing.py` SHA-256: `995a683567b7e6d49bcaf26543959ce43f73ad8bd11c16a12a3b497375e90a46`. Both patched files reproduce the accepted source exactly after newline normalization. Only the wrapper product module changed relative to the published checkpoint; official tests and dependency declarations are unchanged.

## Actual results

| Command group | Result |
| --- | --- |
| official | 88 passed |
| targeted | 769 passed |
| embedding-contract | 48 passed |
| independent-csv | 23 passed |
| independent-rerank | 22 passed |
| independent-pi | 45 passed |
| independent-delta | 25 passed |
| independent-trigger | 6 passed |
| independent-evidence | 18 passed |
| independent-withdrawal | 15 passed |

Final disjoint count: **1059 passed, 27 skipped, 0 failed**. The targeted group includes the new subprocess integration case, so its standalone pass is not added again. The src-only snapshot passed a repeated 22 contract + 8 official tests; those 30 repeats are also excluded from the total. Module provenance checks confirmed that only the src-only snapshot supplied loaded powercontext modules. Both SQLite withdrawal SQL scripts passed and are not counted as pytest cases.

The new integration case uses a real Runtime, SQLite and two OS processes. A mixed good/zero response retains values and token usage; valid neighbors stay cached, the invalid item refreshes during a native Memory write, and duplicate/cross-scope writes do not leak identities. Evidence selection and context-pack deltas preserve exact citations through withdrawal and restart/restoration. Reopening reuses active vectors; native Memory reactivation rebuilds only the inactive entry's projection, after which wrapper cache hits report zero requests. Two initial fixture assumptions were corrected: the lifecycle root is explicitly captured rather than inferred from implicit lineage count, and native reactivation is permitted to rebuild its inactive projection. These were test-fixture corrections, with failures retained in local logs; no additional product change was needed.

The earlier ten independent assertions requiring successful provider responses to become whole-batch ValueError were withdrawn by the final contract review. Their files/logs remain in the historical delivery; they are neither silently deleted nor counted as passing here. The accepted 15 final-contract, 7 prior-contract, 8 mixed-cancellation and 18 independent algorithm/persistence cases are the 48-case embedding-contract group above.

Static checks: 41 Python files formatted; project Ruff 2 existing diagnostics, competition Ruff 14 existing diagnostics, ty 16 existing diagnostics (7 errors/9 warnings), compared to the same baseline and environment. No new diagnostics. `pip check`, frozen-ancestor and unchanged-official/dependency checks passed.

Windows x64 / CPython 3.14.7 with borrowed read-only dependencies; no installation. Official Linux/Python 3.12 and private quality gates were not run. The 27 skipped tests require a live OceanBase/seekdb backend. Optional modules requiring casbin, opentelemetry.sdk or platformdirs remain outside executed coverage. No claim is made that the platform's prior zero score has been reproduced or that its private gate now passes.

The complete original publication evidence is preserved in the local checkpoint's `before` directory, including its archive, manifests, hashes and test records. Full command lines, cwd, environment overrides, timings and earlier failures are retained in the local command ledger and logs.
