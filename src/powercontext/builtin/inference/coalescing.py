# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Event-loop-local embedding coalescing and bounded, in-memory vector reuse."""

from __future__ import annotations

import asyncio
import math
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from powercontext.builtin.artifacts.memory.canonical import canonical_embedding
from powercontext.builtin.inference.models import EmbeddingResult, EmbeddingVector, InferenceUsage
from powercontext.builtin.inference.protocols import EmbeddingModel, QueryEmbeddingModel, embed_query

if TYPE_CHECKING:
    from powercontext.builtin.artifacts.memory.models import EmbeddingProfile


@dataclass(frozen=True, eq=False)
class _BatchUsage:
    # Identity distinguishes separate requests even when their usage is equal.
    requests: int
    input_tokens: int | None
    output_tokens: int | None


@dataclass(frozen=True)
class _Completed:
    vector: EmbeddingVector
    batch: _BatchUsage


def _batch_usage(result: EmbeddingResult, expected: int, *, profile: EmbeddingProfile) -> _BatchUsage:
    if len(result.vectors) != expected:
        msg = "Embedding vector count does not match the request text count"
        raise ValueError(msg)
    # Validate the complete response before publishing any shared result or
    # caching its prefix. Native Memory rejects these values too; caching them
    # first would keep serving an error even after the provider recovers.
    for vector in result.vectors:
        # Reuse Memory's profile rules, including positive dimensions and a
        # non-zero norm for unit profiles. Discard the normalized copy: this
        # wrapper must return and cache the provider's original valid vector.
        canonical_embedding(vector, dimension=profile.dimension, normalization=profile.normalization)
    usage = result.usage
    return _BatchUsage(usage.requests, usage.input_tokens, usage.output_tokens)


def _observe_failure(future: asyncio.Future[_Completed]) -> None:
    # A request may finish after all its callers have been cancelled.
    if not future.cancelled():
        future.exception()


def _sum_tokens(values: list[int | None]) -> int | None:
    known = [value for value in values if value is not None]
    return sum(known) if known else None


async def _wait_results(futures: list[asyncio.Future[_Completed]]) -> list[_Completed]:
    # asyncio.wait never forwards caller cancellation to the supplied futures.
    # Inspect each completion promptly, including provider cancellation, without
    # abandoning independent batches when a different batch fails.
    pending = set(futures)
    while pending:
        done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
        for future in done:
            future.result()
    return [future.result() for future in futures]


class CoalescingEmbeddingModel:
    """Share pending embedding work and cache successful vectors in LRU order.

    Use one wrapper per deployment-fixed model on one event loop. Cancellation
    of a caller leaves shared provider work running. Cache entries are derived,
    process-local values; a new wrapper starts cold and does not alter durable
    Memory indexes. Query embeddings use a separate key space for asymmetric
    providers, and share document work for symmetric providers.
    """

    def __init__(
        self,
        model: EmbeddingModel,
        *,
        max_batch_size: int = 64,
        coalesce_ms: float = 5.0,
        cache_size: int = 1024,
    ) -> None:
        if isinstance(max_batch_size, bool) or not isinstance(max_batch_size, int) or max_batch_size < 1:
            msg = "max_batch_size must be a positive integer"
            raise ValueError(msg)
        if isinstance(cache_size, bool) or not isinstance(cache_size, int) or cache_size < 0:
            msg = "cache_size must be a non-negative integer"
            raise ValueError(msg)
        if not math.isfinite(coalesce_ms) or coalesce_ms < 0:
            msg = "coalesce_ms must be finite and non-negative"
            raise ValueError(msg)
        self.profile = model.profile
        self._model = model
        self._max_batch_size = max_batch_size
        self._delay = coalesce_ms / 1000
        self._cache_size = cache_size
        self._cache: OrderedDict[tuple[bool, str], EmbeddingVector] = OrderedDict()
        self._inflight: dict[tuple[bool, str], asyncio.Future[_Completed]] = {}
        self._pending: dict[tuple[bool, str], asyncio.Future[_Completed]] = {}
        self._timer: asyncio.TimerHandle | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
        """Return ordered vectors, charging each shared provider batch once."""
        return await self._embed(texts, query=False)

    async def embed_query(self, texts: tuple[str, ...], /) -> EmbeddingResult:
        """Preserve optional query-specific provider semantics."""
        return await self._embed(texts, query=isinstance(self._model, QueryEmbeddingModel))

    async def _embed(self, texts: tuple[str, ...], *, query: bool) -> EmbeddingResult:
        loop = asyncio.get_running_loop()
        if self._loop is not None and self._loop is not loop:
            msg = "CoalescingEmbeddingModel must be used on a single event loop"
            raise RuntimeError(msg)
        self._loop = loop
        vectors: dict[str, EmbeddingVector] = {}
        waiting: dict[str, asyncio.Future[_Completed]] = {}
        # Register the entire input without yielding, so callers can attach to
        # queued or executing work before any provider result is published.
        for text in texts:
            key = (query, text)
            if key in self._cache:
                self._cache.move_to_end(key)
                vectors[text] = self._cache[key]
            elif text not in waiting:
                future = self._inflight.get(key)
                if future is None:
                    future = loop.create_future()
                    future.add_done_callback(_observe_failure)
                    self._inflight[key] = future
                    self._pending[key] = future
                waiting[text] = future
        if self._pending and self._timer is None:
            self._timer = loop.call_later(self._delay, self._flush)
        completed = await _wait_results(list(waiting.values()))
        batches: set[_BatchUsage] = set()
        for text, result in zip(waiting, completed, strict=True):
            vectors[text] = result.vector
            batches.add(result.batch)
        return EmbeddingResult(
            vectors=tuple(vectors[text] for text in texts),
            usage=InferenceUsage(
                requests=sum(batch.requests for batch in batches),
                input_tokens=_sum_tokens([batch.input_tokens for batch in batches]),
                output_tokens=_sum_tokens([batch.output_tokens for batch in batches]),
            ),
        )

    def _flush(self) -> None:
        self._timer = None
        pending, self._pending = self._pending, {}
        for query in (False, True):
            items = [(key, future) for key, future in pending.items() if key[0] is query]
            for start in range(0, len(items), self._max_batch_size):
                # Independent batches must complete even if another hangs or fails.
                task = asyncio.create_task(self._run_batch(items[start : start + self._max_batch_size], query=query))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)

    async def _run_batch(
        self,
        items: list[tuple[tuple[bool, str], asyncio.Future[_Completed]]],
        *,
        query: bool,
    ) -> None:
        texts = tuple(key[1] for key, _ in items)
        try:
            result = await embed_query(self._model, texts) if query else await self._model.embed(texts)
            batch = _batch_usage(result, len(texts), profile=self.profile)
        except asyncio.CancelledError:
            for _, future in items:
                future.cancel()
            raise
        except Exception as error:
            for _, future in items:
                future.set_exception(error)
        else:
            for (key, future), vector in zip(items, result.vectors, strict=True):
                if self._cache_size:
                    self._cache[key] = vector
                    self._cache.move_to_end(key)
                    if len(self._cache) > self._cache_size:
                        self._cache.popitem(last=False)
                future.set_result(_Completed(vector, batch))
        finally:
            for key, _ in items:
                del self._inflight[key]


__all__ = ["CoalescingEmbeddingModel"]
