# Source withdrawal and restoration

`open_builtin_runtime()` exposes `runtime.lifecycle.for_scope(scope_id)`. The service registers a caller-provided,
immutable dependency DAG in the Runtime database. It does not infer dependencies from text. A scope must exist,
parents must be registered first, and each node ID has one immutable binding. Repeating the same registration is
idempotent; changing its kind, reference, lifecycle revision, parent set, or policy is an error. Parent order has no
semantic significance. Node IDs are preserved exactly, including Unicode and whitespace around a nonblank value.

```python
from powercontext.builtin.runtime.source_lifecycle import SourceLifecycleEvent

service = runtime.lifecycle.for_scope(scope_id)
await service.register_source("document", captured.source_ref, revision=1)
await service.register_memory("fact", result.entry.citation, parents=("document",), policy="all")
await service.register_topic("summary", topic_ref, parents=("fact",), policy="all")
await service.apply(SourceLifecycleEvent(
    node_id="document", revision=1, sequence=1, available=False, reason="source withdrawn",
))
historical_citation = await service.resolve("fact", purpose="audit")
await service.apply(SourceLifecycleEvent(
    node_id="document", revision=1, sequence=2, available=True, reason="source restored",
))
original_citation = await service.resolve("fact", purpose="generation")
```

All registration, event and resolution methods are asynchronous. References must be readable in the selected scope.
Memory citations must belong to their exact referenced revision and still identify the current body version. The
binding does not support external body revision or compaction of its registered Memory entry during its lifetime.
Unregistered records keep their ordinary behavior. Multiple graph nodes may bind the same native body, including
Memory inputs that the native writer deduplicates. Each node retains its own all/any policy and resolution eligibility;
the body remains natively eligible while at least one of its aliases is supported. Memory aggregation matches scope,
Memory artifact ID, entry ID and entry version, allowing citations of that version from different Memory snapshots.
Topic aggregation matches scope, artifact ID and exact revision. Equal text, a different artifact, another revision or
another scope cannot supply support. Registering an unsupported alias never hides an independently supported body.
When every alias loses support, native recall excludes the body; restoring any alias makes it available again.

`SourceLifecycleEvent` rejects extra fields, non-string or blank IDs/reasons, coercion of booleans or numeric strings,
and nonpositive revisions/sequences. The lifecycle revision is independent of the Source's content identity. Events
may target only registered Source nodes with exactly that lifecycle revision. Sequence numbers are tracked per Source;
gaps are allowed, lower numbers are rejected, and an equal sequence must match the entire prior event, including its
reason. A successful replay returns the currently available node IDs without creating a Memory revision. The returned
list is sorted by node ID and includes available Source nodes.

`all` requires every parent; `any` requires at least one independently sufficient parent. These policies are applied
at registration and at every event, at all graph depths. Each node represents one whole body; partial summary
rewriting is not performed. `generation` rejects an unavailable node; `audit` returns its original reference regardless
of eligibility. Unknown nodes and unknown purposes raise `SourceLifecycleError`, a `ValueError` subclass.

The `pc_source_lifecycle_nodes` table stores immutable bindings, current states and each Source's last accepted event.
The table is created additively during normal database initialization. No files beside the database or process-local
state are required. Scope foreign keys and predicates isolate nodes; SHA-256 keys keep long logical node IDs out of
database index width limits. References and node IDs remain intact in the serialized payload.

An operation uses the Runtime scope lock and one database transaction. Native `MemoryService.forget`/`reactivate`
updates run on that transaction's connection and preserve immutable entry bodies and citations. Event metadata and
all derived states commit with these native revisions. An exception, cancellation before commit, or native capacity
refusal rolls the transaction back, so retrying the same event can finish after the underlying failure is corrected.
A caller uncertain whether commit completed may safely replay the exact event. Registered inactive Memory bodies
must not be compacted or externally rewritten. Existing native capacity limits remain effective on restoration.

Topic publication, head and vector/FTS projections are retained for exact historical reads. SQLite and
OceanBase/seekdb search SQL excludes lifecycle-ineligible topics before candidate limits and channel fusion,
including detail chunks and vector candidates. Reference revisions are read from the existing serialized payload,
so this alias identity rule requires no schema migration. Restoration therefore needs neither republishing nor new embeddings.
Context assembly consumes these ordinary native search results. Topic browsing/exact reads remain audit-capable.

The graph is loaded per scope per operation. Availability evaluation scans ready DAG layers, and state writes touch
changed nodes only. Memory synchronization reads the bound native heads and batches changed entries by target state.
This is designed for small explicit dependency graphs; it is not a multi-writer graph protocol or a performance claim
for graphs containing millions of nodes. The single-writer assumption is part of the competition contract.

Product tests are in `tests/e2e/test_source_lifecycle.py` and `tests/e2e/test_source_lifecycle_aliases.py`. They use real SQLite, including FTS and sqlite-vec, independent
process restarts, native SQL failure injection, capacity failures, scope isolation, and deterministic DAG oracles.
The explicit embedding fixture supplies deterministic vectors only; no database or Runtime substitute is used.
