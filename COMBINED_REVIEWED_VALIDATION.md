# Combined PDF, embedding and native hybrid candidate

Base PDF commit: `88c3b4bf18ef72ea1ef6283229f6992498055b3e`. The first local successor `fefb46c1f4cdb34b53e696f46fa717d9359ccd3a` carries the reviewed successful-response embedding cache contract. This second commit adds precisely the two product files and two tests from reviewed native candidate `4096023bd521b7f2064ee2e0c412d5e67bea49e9`, plus its updated acceptance explanation. No official tests, dependencies or other product files change.

The embedding module SHA-256 remains `b4e26c47effca06c2529f960c65a4382362abd14ae2dbf476b16be84566d3087`. Native index SHA-256 is `45f8801443a2830436db4a5343317acef6f6412db1808f8bf292cd17b8be4b16`; runtime composition SHA-256 is `cde611c0b4b54b436bf36cc60cf1d046988b32bc086c109e6a35f091e6575eaf`. Composition selects the new strategy only for seekdb with an embedding model; SQLite and other existing routes retain their prior behavior. The input composition base was compared byte-for-byte with this candidate before copying the reviewed final blob.

## Combined local checks

This is an early immutable code checkpoint authorized for AMD handoff while the complete combined suites are still running. The parent PDF+embedding checkpoint completed 1,015 passed and 27 skipped, plus 59 src-only repeated passes. The groups below completed after native integration on Windows Python 3.14.7 using existing read-only dependencies and explicit candidate imports. Final combined full-regression, official/PDF and src-only results are pending and must not be inferred from these counts.

| Group | Passed | Skipped | Failed |
| --- | ---: | ---: | ---: |
| native-support | 70 | 1 | 0 |
| native-independent | 18 | 0 | 0 |

All 15 related Python files pass project lint and formatting. Type checking returns exit 1 for three existing composition deprecation warnings, with no type errors. Competition lint returns exit 1 for nine unchanged composition diagnostics and one UP035 diagnostic in the reviewed native module (typing_extensions.override preserves the project's Python 3.11 support); this is not reported as a clean competition lint result. Exact reviewed product bytes are retained. An isolated comparison against the parent composition verifies the existing diagnostics. Frozen ancestry and unchanged official files pass. Native-support exercises SQLite process restart and the native test is skipped when pylibseekdb is absent. The local environment does not establish native seekdb behavior.

The initial borrowed SQLAlchemy 2.1.6 run had six native support assertion failures when accessing compiled.params after render_postcompile. Without any source or assertion edits, the existing CSV environment's SQLAlchemy 2.0.54 (the official pin) passes all 70 support cases; the repeated full regression under 2.0.54 is still running at this checkpoint. The first independent run also failed once because its local report-output directory did not exist; after creating that directory the unchanged 18 tests pass. Failed logs are retained. No dependency was installed; the record distinguishes both environments and their runs.

The parent supplied AMD evidence that the identical native source 4096023 passed the unchanged official hybrid test: Python 3.12.3, pylibseekdb 1.3.0.post4, 1 passed, exit 0, 15.99 seconds total, both TEXT RETRIEVAL SCAN and VECTOR INDEX EXPLAIN checks passed. A short task-owned TMPDIR was required; no product path workaround was applied. This evidence is for the source candidate, not a completed Linux run of this combined commit. Final combined AMD validation remains pending.

Full private retrieval quality/latency workloads and separate native process restart are not claimed. The platform's earlier infrastructure failure root cause remains unproven. No publication or evaluation is performed by this checkpoint; existing published branches remain untouched.
