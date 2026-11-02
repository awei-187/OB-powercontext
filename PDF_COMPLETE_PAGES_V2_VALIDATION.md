# Complete PDF pages v2: integration verification

Base `76eb215472eedb89ae0628eb1cd616a56a975055`. Exact supplied patch SHA256 `94844e1faf24a7726f4cd86b7afc48ddba904a4203c9690992e9e4772d9b5699`. This commit contains the independently accepted three product files and five added tests, plus this validation note. All 874 pre-existing protected product/test/official/dependency files retain their baseline bytes. Embedding and native hybrid implementation files are unchanged.

The change preserves native query tokens, batches provenance reads where the public scoped interface supports it, and allows an oversized source-evidence body only when the Memory write boundary establishes that it equals the authoritative complete PDF page projection. Ordinary notes and unrelated/altered long bodies retain the 8192-byte limit. Existing immutable entries and their hashes remain readable; history is not rewritten.

Independent review approved the exact patch: 15 focused cases passed, including the original unrelated-long-body counterexample, source authority and ordinary-boundary controls. A separate final-v2 process verified all six records across v2 and preserved v1 databases, including old full-page citations and canonical hashes. Author final-source evidence separately records official 94/94 and affected protection 200 passed/13 skipped. Those large suites were inspected by the reviewer; this integration did not rerun them wholesale.

## Checks executed in this checkout

| Group | Passed | Skipped | Failed |
| --- | ---: | ---: | ---: |
| protection | 54 | 1 | 0 |
| key-official | 14 | 0 | 0 |

Protection includes all five added test files, existing Memory canonical boundaries, PDF/embedding scope/citation/usage/process-restart integration, native hybrid index tests and the separate SQLite restart control. Key official covers PDF and embedding. The native seekdb backend skip is not a native pass. All invocations ran serially with verified single-CPU affinity and Windows Idle priority; no global power setting changed.

Project lint, formatting and types pass for all eight files. Competition lint reports four existing Python syntax-upgrade suggestions in Memory service (two UP040, two UP047). Baseline and candidate were checked with the same original file paths/import classification and have identical diagnostics; no rule was suppressed and reviewed product bytes were preserved.

Environment: Windows Python 3.14.7, existing read-only SQLAlchemy 2.0.54 and pypdf 6.19.0. No dependency was installed or changed. This is not Linux/Python 3.12 or live seekdb/OceanBase validation. Private annotation metrics, formal score and hidden deadlines remain unknown. The prior 603-get measurement belongs to the preceding implementation and is not a benchmark for this new bulk-read path. No new performance guarantee is claimed.

Full LF hashes, commands, observed results and independent review records are retained in the integration delivery. No official tests or existing expectations were modified. Platform submission is coordinated separately from this branch publication.
