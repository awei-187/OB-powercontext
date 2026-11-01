# PDF retrieval filter repair validation

Baseline: `61dfd35a9dd27a2ca665d9eb41ca2a8f03c05a46`. The supplied four-file patch SHA256 is `0be18a851069957472c7036c86c1f323ca98dab52354b8f19863b2864c84a563`. PDF module raw Windows SHA256 is `75ee28b5991774cd2da140b00d173a817bce9d026667003e6573ce0fc83579a8`; canonical Git/LF SHA256 is `95589b8d74b0d449e6fc8ee62b5cb347108a9eaaf82b590be508646589ca38d8`. All 517 protected product/official/dependency files remain unchanged, including reviewed embedding and native hybrid implementations.

Independent focused review closed both preceding P2 findings: all 16 original document-label checks and both ordinary-note controls pass without weakening expectations. Candidate eligibility is checked before labels guide retrieval; label grouping retains relevant evidence from opaque or ambiguous document IDs. The original mixed-document target remains retrievable. No fixed company/page/question lookup was introduced.

This integration ran only the necessary key official and cross-feature protection groups after the independent verdict; it did not repeat the author's 188-case suite or the earlier 795-case suite. Every check child was verified on one CPU with Windows Idle priority. No global power setting changed. Local Python is Windows 3.14.7 with existing read-only SQLAlchemy 2.0.54 and pypdf 6.19.0 dependencies; this is not the complete official Linux environment.

| Executed group | Passed | Skipped | Failed |
| --- | ---: | ---: | ---: |
| key-official | 14 | 0 | 0 |
| protection | 23 | 1 | 0 |

Key official covers PDF and embedding. Protection covers PDF/embedding exact citations, usage, scope and process restart, the native hybrid index tests and its separate SQLite restart control. The unavailable native seekdb backend is skipped rather than claimed as passed. Four changed Python files pass project/competition lint, formatting and type checks. One supplied test string was split to satisfy E501, with identical AST and recorded hashes; product code remains exactly reviewed.

Read cost is material: independent single-CPU/Idle measurement on the existing 623-page mixed corpus was 12.512 seconds, 603 Memory.get calls, 9 searches and 1,152 requested candidate slots, returning the target at rank 5 with 20/20 exact readbacks. Public inspected requirements disclose no per-query deadline or numerical get cap, so the reviewer found no demonstrated mandatory performance breach. Hidden total deadlines, private quality/score and Linux/native performance remain unknown. The 24-search bound is not a total API-call bound. No performance guarantee is claimed.

The prior blocked f630 evidence and failed probes are retained outside the repository; they are not relabeled passing. No official test or expectation changed. New work uses this dedicated branch, preserving all previously published branches. Platform submission is coordinated separately.
