# Reviewed PDF and successful embedding cache successor

This candidate starts at PDF-only commit `88c3b4bf18ef72ea1ef6283229f6992498055b3e`. Its only product change is `builtin/inference/coalescing.py`, exactly matching reviewed SHA-256 `b4e26c47effca06c2529f960c65a4382362abd14ae2dbf476b16be84566d3087`. All other 429 product files and all 85 official competition files remain byte-identical to the parent. The reviewed PDF quality implementation is unchanged; native question 11 is excluded.

The incoming product and cumulative test patches target 01e344db, while this parent retained the older 764028 coalescer. Both patches were first reconstructed on their exact 01e344db base. Their final files were compared with the reviewed source, then copied into this separate worktree. The actual parent-relative product diff removes Memory canonical validation from the generic wrapper and its profile argument/imports. Cardinality checks, provider error/cancellation propagation, batching, LRU, query/document key spaces and usage accounting remain intact. Successful provider values, including the official provider's zero vector, are returned and cached unchanged. Native Memory keeps its independent validation.

## Contract and test corrections

The independent product review and cumulative integration-test review both passed before this commit. The latter independently ran 12 cases: 3 corrected integration/boundary cases plus 9 original Memory canonical cases. Its patch hash is `fc677e0611bd2623cf4c4f5ea2f8b4154187b3bbc68be320173df50d6023575d`. Two incoming integration test files differed only by CRLF/LF; normalized hashes are recorded locally and no test assertion was changed during integration.

The prior 22 independent failures imposed withdrawn Memory-specific wrapper requirements: 6 whole-batch malformed-vector exceptions, 4 zero-norm exceptions, 3 downstream malformed-vector refresh expectations, 1 downstream zero refresh expectation, and 8 successful-value refresh expectations. Their historical files/logs and explicit withdrawal rationale are preserved in the source/review evidence; they are not counted as passing or silently marked skip/xfail. The upstream official contract and its unchanged zero-vector provider are the requirement source.

Current integration fixtures exercise actual provider failure and retry, fixed successful page embeddings, usage/cache reuse, scope isolation, lifecycle idempotency, exact citations, selected evidence, Context Pack reconstruction and SQLite/process restart. A separate boundary verifies that native Memory rejects a cached zero norm while the wrapper continues to preserve/cache that successful provider result. See tests/e2e/EMBEDDING_INTEGRATION_NOTES.md. No Memory validation or official test is weakened.

## Executed candidate checks

| Group | Result |
| --- | --- |
| official | 94 passed |
| regression | 775 passed |
| pdf | 86 passed |
| independent | 43 passed |
| contract | 8 passed |
| canonical | 9 passed |

**1015 distinct passed, 27 skipped, zero failures.** The nine-challenge official group includes PDF and embedding. The regression group covers all prior feature/native SQLite/cross-process protection plus the reviewed embedding tests and corrected integration cases. PDF includes 503-page extraction fidelity, scope/revision/restart, malformed stream/CMap controls and 16 quality formulations. Independent PDF controls add 43 cases; the unchanged official-provider contract adds 8; original Memory canonical adds 9. Src-only repeats comprise PDF 43, embedding contract 8 and embedding official 8 (59 repeated passes, not added).

All 11 related Python files pass project Ruff, competition Ruff, formatting and type checks. pip check and unchanged-official/frozen-ancestor checks pass. Actual imports select this candidate; pypdf remains 6.19.0 in the existing read-only dependency directory. No installation occurred. Windows Python 3.14.7 and other borrowed versions differ from the official Linux pins as documented in the local version comparison. The 27 skipped cases require a live backend.

The parent reported Linux 8-contract + 8-official passes for the identical minimal product, but final AMD/Linux validation of this full combined commit remains a separate pending action. Private quality gates and the original platform INFRASTRUCTURE root cause are not established by these tests.

This is a local successor checkpoint only: no push or platform submission. The PDF-only published branch and other worktrees remain unchanged. Its minimal incremental bundle requires this parent commit and is verified in a repository seeded only with the parent's history.
