# PDF and embedding contract candidate

This candidate adds complete PDF page evidence and corrects generic embedding success handling on published commit `764028023ef6e1713b93f2370c6c8d04d739ef0e`. Generic successful vectors and provider usage are preserved, while each vector is independently eligible for cache reuse. PDF extraction validates physical pages and reachable encoded resources atomically before returning pages, including corrupt Flate/CMap rejection. No shared product file was changed for PDF; both PDF modules match the independently accepted source exactly. Two PDF test modules have type-only narrowing and equivalent formatting adjustments; source repositories and assertions remain intact.

## Executed validation

| Group | Result |
| --- | --- |
| official | 94 passed |
| targeted | 839 passed |
| embedding-contract | 48 passed |
| pdf-independent | 21 passed |
| pdf-cross | 1 passed |

**1003 distinct passed, 27 skipped, 0 unresolved failures in this combined round.** The official group includes all nine implemented challenges (PDF 6 plus prior eight challenges 88). The product group includes 70 real-PDF tests, complete 503-page extraction comparison, four-process PDF revision/scope/restart cases and all previously integrated feature tests. The new PDF/embedding case is counted separately once. The prior embedding-only checkpoint remains intact at 1059 passed/27 skipped; its counts are not added to this round.

The isolated src-only candidate separately passed PDF review 21, embedding contract 22 and embedding official 8 tests (51 repeated passes, excluded above). Import evidence confirms both product modules load from the candidate src-only tree and pypdf 6.19.0 loads from the existing PDF task dependency directory. No package installation occurred.

The new real-Runtime/SQLite case primes a mixed valid/zero provider response, verifies unchanged values and token usage, reuses its valid neighbor, refreshes the invalid member, ingests the same serialized two-page PDF twice in two scopes, and reopens in a separate interpreter. Source journal identities, page metadata and exact citations persist; evidence selection and serialized ContextPack deltas reconstruct identical content and respect the byte budget. Stored page embeddings survive restart; the new process embeds only its context query.

Initial combination-test failures were fixture errors and remain in local logs: priming included PDF trailing newlines although native Memory canonicalizes text; preparing context legitimately embeds its query; MemoryEntryRecord.entry.sources contains SourceRef values, which must be resolved through the durable Source journal. The final test checks these real contracts. No product repair or withdrawn assertion was hidden. The pre-existing optional recall token estimator logs that SourceObservation has no registered token projection; context generation and verified byte accounting still succeed. This estimator limitation was not changed.

## Static checks and limits

All 48 changed Python files pass the project formatter. Project Ruff retains 2 original diagnostics, competition Ruff retains 14 original diagnostics, and the full changed-file type check retains 16 original diagnostics (7 errors/9 warnings), all compared against the unchanged baseline. Both PDF product modules and all four PDF test modules pass their separate type checks. No new lint/type diagnostics remain. The two imported test modules now narrow optional scopes and Source types, annotate deliberately invalid runtime inputs with typing.cast, exercise frozen mutation through the same native __setattr__ operation, and split two string literals without changing their values. No rules were suppressed. After these changes, all 70 PDF tests and the combined restart case passed again; the final frozen-mutation spelling passed a further focused rerun. These 72 repeated passes replace affected checks rather than increasing the 1003 distinct count.

The frozen ancestor, unchanged official competition assets and dependency declarations were checked. Source hashes/status and patch applicability are verified in the final audit. All runtime databases/caches/logs are isolated under the integration directory. Prior failed fixture attempts and full command/environment/timing records remain available locally.

Actual execution used Windows x64 / CPython 3.14.7, not official Linux/Python 3.12. The 27 skipped tests need a live OceanBase/seekdb backend. Optional casbin/opentelemetry.sdk/platformdirs coverage and private FinanceBench gold recall/page F1/Recall@20, rerank/evidence/delta quality gates are not measured. No platform score is inferred.

Question 11 is not included because native pylibseekdb validation remains unavailable. Publication is authorized only as an ordinary appended commit on dot/competition-reviewed. Question 11, platform submission, default-branch, visibility and permission changes are outside this release. The parent handles official AMD Linux validation and platform submission using the recorded release commit.
