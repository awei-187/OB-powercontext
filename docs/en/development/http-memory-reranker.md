# HTTP Memory reranking

`HTTPMemoryReranker` implements `MemoryReranker` using a caller-owned `httpx.AsyncClient`.
Inject it through `memory_reranker` when opening the built-in Runtime or Contexts.
The existing Memory service resolves selected ranks to the original hits, preserving
their text, Artifact references, entry IDs, entry version IDs, and coarse scores.

```python
import httpx

from powercontext.builtin.artifacts.memory import HTTPMemoryReranker
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import BuiltinConfig, open_builtin_contexts


async def open_application(endpoint: str) -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        reranker = HTTPMemoryReranker(endpoint, client=client, batch_size=32)
        async with open_builtin_contexts(
            BuiltinConfig(database=SQLiteConfig()), memory_reranker=reranker
        ) as contexts:
            context = await contexts.get("project")
            # Use context.artifacts.memory to remember and search Memory entries.
```

Install `powercontext[builtin]` and `httpx` for this example. The caller controls the
client's timeout and transport, and closes it after the Runtime. The adapter neither
creates nor closes the client.

For authentication, supply a precomputed `Authorization` header (for example a
Bearer token) through the client's `headers`. Each scoring POST sets `auth=None`
to disable client-level authentication flows, including Basic, Digest and custom
token-refresh flows. This prevents an HTTP 401 challenge from implicitly resending
the same candidates. A 401 raises `httpx.HTTPStatusError` after one attempt; Digest
challenge-response negotiation is unsupported. Existing headers and the client's
`auth` configuration are not mutated, so other users of the client are unaffected.

Each POST contains `query` and `candidates`, with only `rank` and `text` for each
candidate. Ranks are one-based positions in the entire input pool and never reset
at batch boundaries. The response must contain exactly a `scores` array, whose
records contain exactly an integer `rank` and a finite numeric `score`. Boolean
values and numeric strings are rejected. Responses may arrive in any rank order,
but must cover every rank in their own batch exactly once.

```json
{"query":"calibration","candidates":[{"rank":1,"text":"Calibration record."}]}
```

```json
{"scores":[{"rank":1,"score":0.75}]}
```

Batches run sequentially, each containing at most `batch_size` candidates. After
all batches validate, selection uses descending score and ascending original rank
for ties. Selection requires O(n log n) time and O(n) additional storage.
`decision.usage.requests` records completed scoring requests; a successful call
makes exactly `ceil(n / batch_size)` requests. The default policy ID is
`http-cross-encoder-v1`; a custom `policy_id` is copied into the Memory search trace.

Empty candidates, invalid limits and non-positive or non-integer batch sizes raise
`ValueError`. Invalid JSON, schema or rank coverage also raise `ValueError`. Non-2xx
responses, including redirects, raise `httpx.HTTPStatusError`; transport exceptions
propagate unchanged. There are no adapter retries, partial decisions or fallback
selections. To maintain the exact request budget, supply a transport without
automatic retries and hooks that do not initiate additional requests. Scores
determine selection only and do not overwrite the original hit scores.

The product tests use a local loopback HTTP server and SQLite without credentials:

```bash
python -m pytest -q tests/builtin/artifacts/memory/test_http_reranker.py
```
