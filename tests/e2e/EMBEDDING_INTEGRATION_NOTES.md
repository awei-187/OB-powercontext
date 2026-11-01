# Embedding integration fixture correction

The upstream `memory-02-embedding-batches/instruction.md` at commit
`dab240063bfcfa7917898dc44da4baadb3747bd0`, lines 42–61, requires caching
successful provider results, propagating provider failures without caching them,
and rejecting a vector-count mismatch. It does not give the wrapper a
Memory-specific normalization gate. The original public provider successfully
returns a zero vector for the empty string under its default unit profile.

Two integration fixtures in published `01e344db24e089fa910cbf53b7c0ddfb29e3b4a1`
incorrectly primed a successful zero vector and expected a later native operation
to fetch a replacement. With correct successful-result caching, native Memory
instead rejects that cached zero vector. These were mistaken test premises, not
provider failures, and are withdrawn here.

`test_integrated_embedding_contract.py` now warms a valid cached entry, makes the
provider actually raise once for another entry, and verifies that native remember
retries the failed request. It retains exact request counts, successful cache
reuse, two scopes, lifecycle deactivation/reactivation, idempotency, exact evidence
citations and Context Pack reconstruction across separate interpreter processes.

`test_integrated_pdf_embedding.py` uses stable valid page vectors. Both successful
page embeddings must remain cached across duplicate ingestion in two scopes; only
the context query adds a request. The test retains page-number/document metadata,
exact original text, source journal idempotency, citation identities, scope
isolation and SQLite/process-restart checks. It no longer expects a successful
page embedding to refresh solely because a downstream consumer dislikes it.

The separate boundary test
`test_memory_unit_validation_does_not_change_wrapper_success_cache` demonstrates
both responsibilities: the wrapper preserves and caches the provider's successful
zero vector; native Memory still rejects its zero norm. That rejection neither
changes the wrapper result nor implicitly invalidates its cache. No Memory
validation is relaxed and no official test is modified.

The earlier algorithm-test correction is separate: successful vectors are reused
without an additional Memory gate; actual exceptions and cardinality mismatches
remain uncached and retryable. These notes explain our fixture corrections; they
are not an alternative source of official requirements.
