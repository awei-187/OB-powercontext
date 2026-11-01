# Query-driven literal Memory evidence

`PrepareContextRequest(evidence_selection=True)` enables offline passage selection in
`PreparedContextBuilder.build_scopes_result`. The strict boolean defaults to `False`;
ordinary prepare output is unchanged when it is omitted or false.

The selector consumes the supplied `PreparedMemoryCandidates`. It does not retrieve
additional documents, read files, persist derived state, call a model, or contact a
service. Runtime retrieval, authorization, Memory persistence, and citation lookup
continue to use their existing interfaces. A restarted Runtime can reconstruct a new
selection from its persisted Memory; previously issued citations still identify the
original revision and entry version.

The builder's evidence mode uses Memory candidates only, taking precedence over text
assembly and Code rendering. Other supplied Artifact families are ignored. Runtime
recall itself is unchanged: callers using an assembly that excludes Memory may have
no Memory candidates to select.

## Results and identity

`PreparedContextBuild.fragments` is a tuple of `EvidenceFragment` values. Each has
`address: MemoryEntryAddress`, `start: int`, `end: int`, and `text: str`. Coordinates
are half-open Python character offsets into the original entry. Every nonempty
fragment equals `entry.text[start:end]`; normalization is used only for scoring.

`origins` contains the corresponding `MemoryEntryAddress` values in exactly the same
order. Every JSON item carries `citation.scope_id`, `citation.memory_ref`,
`citation.entry_id`, `citation.entry_version_id`, `content`, `start`, and `end`.
Convert the three Memory identity fields to `MemoryCitation` and call the relevant
scope's `memory.get(GetMemoryEntryRequest(citation=...))` to verify a fragment.

Duplicate candidates are identified by the complete scope/family/artifact/revision/
entry/version tuple. Conflicting text for one exact identity raises
`PreparedContextInvariantError("evidence-version-conflict")`. Missing or mismatched
Memory references, missing scope identity, and excessive Memory candidate counts
also fail before a result is returned. Equal text in different scopes keeps separate
citations. The selector does not reinterpret old revisions as the current head.

## Selection and budget

The implementation segments sentences while retaining original offsets, handles
common abbreviations, decimal points, CJK punctuation, and line endings, and removes
repeated literal sentences within each entry. It scores passages with query term
frequency, inverse sentence frequency, sentence coverage, and document coverage.
English inflections use a small deterministic normalization; CJK uses bigrams.
Scores are lexical heuristics, not probabilities or semantic judgments.

A deterministic greedy pass chooses relevant complete sentences by score divided by
the square root of their incremental byte cost. Adjacent passages in the same entry
merge, preserving intervening whitespace and reducing citation overhead. Output is
ordered by candidate document and original character position. If a complete
sentence cannot fit, a query-centered literal window may use the remaining space.
It adds no ellipsis, summary, or generated text. Unmatched queries can return an empty
context. Repeated calls have no cache or state to invalidate.

Every attempted addition is measured using the final UTF-8 rendering, including the
existing trust policy, envelope markers, compact JSON, complete citations, escaped
content, and character offsets. Unicode line separators are JSON-escaped to keep
the envelope on distinct physical lines; decoding recovers their exact characters.
`content_bytes` measures the final string. `probe_budget` uses the same evidence
selection path, so its delivered count and unused bytes describe the actual result.

The packing pass is greedy, not a globally optimal knapsack solver. Lexical selection
may miss paraphrases and evidence expressed with different terminology. Sentence
segmentation and inflection handling are heuristic. No benchmark labels, document
IDs, fixed responses, additional dependencies, or pretrained weights are embedded.

## Validation

Focused tests live in `tests/builtin/runtime/test_evidence_selection.py`. The SQLite
integration test in `tests/e2e/test_evidence_persistence.py` uses five independent
Python processes: ingest, select, select again with a different hash seed, mutate,
and verify. It checks duplicate ingestion, scope separation, deterministic readback,
six byte budgets, revision changes, retirement, and historical citation lookup.

The competition's public acceptance assets are unchanged. Public tests do not
establish the private SciFact token-recall or complete-evidence thresholds.
