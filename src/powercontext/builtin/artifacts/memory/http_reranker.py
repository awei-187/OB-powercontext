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

"""HTTP scoring with identity-preserving, globally ordered Memory selection."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from powercontext.builtin.artifacts.memory.models import MemoryHit
from powercontext.builtin.artifacts.memory.reranking import MemoryRerankDecision
from powercontext.builtin.inference import InferenceUsage

if TYPE_CHECKING:
    import httpx


class HTTPMemoryReranker:
    """Score bounded batches using a caller-owned client, then select globally.

    The client supplies precomputed authentication headers, timeouts and transport
    configuration and remains open after reranking. Client auth flows are disabled
    per request to prevent challenge-response resends. Failures propagate without
    a partial decision or a fallback to the coarse order. No requests are retried
    by this adapter.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        client: httpx.AsyncClient,
        batch_size: int = 32,
        policy_id: str = "http-cross-encoder-v1",
    ) -> None:
        if type(batch_size) is not int or batch_size < 1:
            raise ValueError("batch_size must be a positive integer")  # noqa: TRY003
        self._endpoint = endpoint
        self._client = client
        self._batch_size = batch_size
        self.policy_id = policy_id

    async def rerank(
        self,
        query: str,
        candidates: tuple[MemoryHit, ...],
        limit: int,
        /,
    ) -> MemoryRerankDecision:
        """Return original one-based ranks sorted by score, breaking ties by rank."""
        if not candidates:
            raise ValueError("rerank requires at least one candidate")  # noqa: TRY003
        if type(limit) is not int or not 1 <= limit <= len(candidates):
            raise ValueError("rerank limit must be an integer between one and the candidate count")  # noqa: TRY003

        scores: list[tuple[int, int | float]] = []
        requests = 0
        for start in range(0, len(candidates), self._batch_size):
            batch = candidates[start : start + self._batch_size]
            response = await self._client.request(
                "POST",
                self._endpoint,
                json={
                    "query": query,
                    "candidates": [{"rank": rank, "text": hit.text} for rank, hit in enumerate(batch, start=start + 1)],
                },
                # Auth challenges and redirects must not resend the candidates.
                auth=None,
                follow_redirects=False,
            )
            requests += 1
            response.raise_for_status()
            scores.extend(_batch_scores(response.json(), range(start + 1, start + len(batch) + 1)))

        scores.sort(key=lambda item: (-item[1], item[0]))
        return MemoryRerankDecision(
            selected_ranks=tuple(rank for rank, _score in scores[:limit]),
            usage=InferenceUsage(requests=requests),
        )


def _batch_scores(payload: object, expected_ranks: range) -> list[tuple[int, int | float]]:
    """Validate exact schema and batch coverage without coercing JSON values."""
    if not isinstance(payload, dict) or payload.keys() != {"scores"} or not isinstance(payload["scores"], list):
        raise ValueError("rerank response must contain only a scores array")  # noqa: TRY003
    remaining = set(expected_ranks)
    scores: list[tuple[int, int | float]] = []
    for item in payload["scores"]:
        if not isinstance(item, dict) or item.keys() != {"rank", "score"}:
            raise ValueError("each rerank score must contain only rank and score")  # noqa: TRY003
        rank, score = item["rank"], item["score"]
        if type(rank) is not int or rank not in remaining:
            raise ValueError("rerank response contains a duplicate or out-of-batch rank")  # noqa: TRY003
        if type(score) not in (int, float) or (isinstance(score, float) and not math.isfinite(score)):
            raise ValueError("rerank score must be a finite number")  # noqa: TRY003
        remaining.remove(rank)
        scores.append((rank, score))
    if remaining:
        raise ValueError("rerank response is missing batch ranks")  # noqa: TRY003
    return scores


__all__ = ["HTTPMemoryReranker"]
