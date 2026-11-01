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

"""HTTP protocol and native Memory tests using an offline loopback service."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Generator, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Any

import httpx
import pytest

from powercontext.artifacts import ArtifactRef
from powercontext.builtin.artifacts.memory import HTTPMemoryReranker, MemoryHit


class _ScoringServer:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.headers: list[httpx.Headers] = []
        self.responder: Callable[[dict[str, Any]], tuple[int, bytes]] = self.score
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                owner.requests.append(body)
                owner.headers.append(httpx.Headers(self.headers.items()))
                status, content = owner.responder(body)
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(content)))
                if status == 307:
                    self.send_header("Location", "/score")
                if status == 401:
                    self.send_header("WWW-Authenticate", 'Digest realm="test", nonce="abc", qop="auth", algorithm=MD5')
                self.end_headers()
                self.wfile.write(content)

            def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - stdlib override
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.endpoint = f"http://127.0.0.1:{self.server.server_port}/score"
        self.thread = Thread(target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True)

    @staticmethod
    def score(body: dict[str, Any]) -> tuple[int, bytes]:
        return 200, json.dumps({
            "scores": [{"rank": item["rank"], "score": item["rank"] % 5} for item in reversed(body["candidates"])]
        }).encode()


@pytest.fixture
def scoring_server() -> Iterator[_ScoringServer]:
    service = _ScoringServer()
    service.thread.start()
    try:
        yield service
    finally:
        service.server.shutdown()
        service.server.server_close()
        service.thread.join(timeout=5)


def _hits(count: int) -> tuple[MemoryHit, ...]:
    return tuple(
        MemoryHit(
            memory_ref=ArtifactRef(family="memory", artifact_id=f"memory-{i % 2}", revision=2),
            entry_id=f"entry-{i}",
            entry_version_id=f"entry-{i}-v2",
            text=f'候选 {i}\n"unchanged" 🐟',
            score=1 / i,
            matched_by=("fts",),
        )
        for i in range(1, count + 1)
    )


@pytest.mark.parametrize("count,batch_size,limit", [(1, 32, 1), (8, 2, 8), (9, 2, 1), (173, 7, 10), (33, 32, 10)])
def test_http_batches_global_order_and_identity(scoring_server, count, batch_size, limit) -> None:
    candidates = _hits(count)
    original = tuple(hit.model_dump() for hit in candidates)

    async def scenario() -> None:
        async with httpx.AsyncClient(trust_env=False) as client:
            reranker = HTTPMemoryReranker(scoring_server.endpoint, client=client, batch_size=batch_size)
            decision = await reranker.rerank("查询 🐟", candidates, limit)
            assert not client.is_closed
        expected = tuple(sorted(range(1, count + 1), key=lambda rank: (-(rank % 5), rank))[:limit])
        assert decision.selected_ranks == expected
        assert decision.usage.requests == len(scoring_server.requests) == (count + batch_size - 1) // batch_size
        assert decision.usage.input_tokens is None and decision.usage.output_tokens is None
        assert not decision.used_fallback and decision.discarded_rank_count == 0
        assert reranker.policy_id == "http-cross-encoder-v1"

    asyncio.run(scenario())
    sent = []
    for body in scoring_server.requests:
        assert set(body) == {"query", "candidates"}
        assert body["query"] == "查询 🐟"
        assert 1 <= len(body["candidates"]) <= batch_size
        sent.extend(body["candidates"])
    assert sorted(sent, key=lambda item: item["rank"]) == [
        {"rank": rank, "text": hit.text} for rank, hit in enumerate(candidates, start=1)
    ]
    assert tuple(hit.model_dump() for hit in candidates) == original


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        1,
        "scores",
        {},
        {"scores": None},
        {"scores": {}},
        {"scores": []},
        {"scores": [], "extra": True},
        {"scores": [None]},
        {"scores": [[]]},
        {"scores": [{}]},
        {"scores": [{"rank": 1}]},
        {"scores": [{"score": 1}]},
        {"scores": [{"rank": 1, "score": 1, "extra": True}]},
        *({"scores": [{"rank": rank, "score": 1}]} for rank in [0, -1, 2, True, False, 1.0, "1", None, []]),
        *(
            {"scores": [{"rank": 1, "score": score}]}
            for score in [True, False, "1", None, [], {}, float("nan"), float("inf"), -float("inf")]
        ),
        {"scores": [{"rank": 1, "score": 1}, {"rank": 1, "score": 2}]},
    ],
)
def test_http_rejects_invalid_schema(scoring_server, payload) -> None:
    scoring_server.responder = lambda body: (200, json.dumps(payload).encode())

    async def scenario() -> None:
        async with httpx.AsyncClient(trust_env=False) as client:
            with pytest.raises(ValueError):
                await HTTPMemoryReranker(scoring_server.endpoint, client=client).rerank("q", _hits(1), 1)

    asyncio.run(scenario())


@pytest.mark.parametrize("content", [b"", b"not json", b'{"scores":', b"\xff"])
def test_invalid_json_raises_value_error(scoring_server, content) -> None:
    scoring_server.responder = lambda body: (200, content)

    async def scenario() -> None:
        async with httpx.AsyncClient(trust_env=False) as client:
            with pytest.raises(ValueError):
                await HTTPMemoryReranker(scoring_server.endpoint, client=client).rerank("q", _hits(1), 1)

    asyncio.run(scenario())


@pytest.mark.parametrize("batch_size", [0, -1, True, False, 1.5, "2", None])
def test_invalid_batch_size_fails_before_http(batch_size) -> None:
    async def scenario() -> None:
        async with httpx.AsyncClient(trust_env=False) as client:
            with pytest.raises(ValueError):
                HTTPMemoryReranker("http://unused.invalid", client=client, batch_size=batch_size)

    asyncio.run(scenario())


@pytest.mark.parametrize("count,limit", [(0, 1), (1, 0), (1, -1), (1, 2), (1, True), (1, 1.0), (1, "1"), (1, None)])
def test_invalid_bounds_do_not_send(scoring_server, count, limit) -> None:
    async def scenario() -> None:
        async with httpx.AsyncClient(trust_env=False) as client:
            with pytest.raises(ValueError):
                await HTTPMemoryReranker(scoring_server.endpoint, client=client).rerank("q", _hits(count), limit)

    asyncio.run(scenario())
    assert scoring_server.requests == []


@pytest.mark.parametrize("status", [301, 307, 400, 429, 500, 503])
def test_non_success_retains_httpx_exception(scoring_server, status) -> None:
    scoring_server.responder = lambda body: (status, b"not json")

    async def scenario() -> None:
        async with httpx.AsyncClient(trust_env=False, follow_redirects=True) as client:
            with pytest.raises(httpx.HTTPStatusError) as error:
                await HTTPMemoryReranker(scoring_server.endpoint, client=client).rerank("q", _hits(1), 1)
            assert error.value.response.status_code == status
            assert str(error.value.request.url) == scoring_server.endpoint

    asyncio.run(scenario())
    assert len(scoring_server.requests) == 1


@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError])
def test_transport_exceptions_propagate_unchanged(error_type) -> None:
    error = error_type("offline")

    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(error_type) as caught:
                await HTTPMemoryReranker("http://unused.invalid", client=client).rerank("q", _hits(1), 1)
            assert caught.value is error

    asyncio.run(scenario())


@pytest.mark.parametrize("use_mock", [False, True], ids=["loopback", "mock"])
@pytest.mark.parametrize("challenge_rank", [1, 3], ids=["first-batch", "later-batch"])
def test_digest_challenge_does_not_resend_candidates(scoring_server, use_mock, challenge_rank) -> None:
    def respond(body: dict[str, Any]) -> tuple[int, bytes]:
        if body["candidates"][0]["rank"] == challenge_rank and "authorization" not in scoring_server.headers[-1]:
            return 401, b""
        return scoring_server.score(body)

    scoring_server.responder = respond

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        scoring_server.requests.append(body)
        scoring_server.headers.append(request.headers)
        status, content = respond(body)
        return httpx.Response(
            status,
            content=content,
            headers={"WWW-Authenticate": 'Digest realm="test", nonce="abc", qop="auth", algorithm=MD5'},
        )

    async def scenario() -> None:
        auth = httpx.DigestAuth("test-user", "synthetic-password")
        async with httpx.AsyncClient(
            auth=auth, transport=httpx.MockTransport(handler) if use_mock else None, trust_env=False
        ) as client:
            reranker = HTTPMemoryReranker(scoring_server.endpoint, client=client, batch_size=2)
            with pytest.raises(httpx.HTTPStatusError) as error:
                await reranker.rerank("q", _hits(5), 2)
            assert error.value.response.status_code == 401
            assert error.value.response.history == []
            assert len(scoring_server.requests) == (challenge_rank + 1) // 2
            assert [item["rank"] for body in scoring_server.requests for item in body["candidates"]] == list(
                range(1, challenge_rank + 2)
            )
            assert client.auth is auth and not client.is_closed

    asyncio.run(scenario())


@pytest.mark.parametrize("auth_kind", ["digest", "basic", "custom"])
def test_precomputed_auth_headers_survive_disabled_auth_flows(scoring_server, auth_kind) -> None:
    class RefreshAuth(httpx.Auth):
        def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
            raise AssertionError("client auth flow must not run for scoring requests")  # noqa: TRY003
            yield request  # pragma: no cover - keeps this an auth-flow generator

    header = "Bearer synthetic-token"
    auth = {
        "digest": httpx.DigestAuth("test-user", "synthetic-password"),
        "basic": httpx.BasicAuth("test-user", "synthetic-password"),
        "custom": RefreshAuth(),
    }[auth_kind]

    def respond(body: dict[str, Any]) -> tuple[int, bytes]:
        assert scoring_server.headers[-1]["authorization"] == header
        return scoring_server.score(body)

    scoring_server.responder = respond

    async def scenario() -> None:
        async with httpx.AsyncClient(auth=auth, headers={"Authorization": header}, trust_env=False) as client:
            decision = await HTTPMemoryReranker(scoring_server.endpoint, client=client, batch_size=2).rerank(
                "q", _hits(3), 2
            )
            assert decision.selected_ranks == (3, 2)
            assert decision.usage.requests == len(scoring_server.requests) == 2
            assert client.auth is auth and not client.is_closed
            assert client.headers["authorization"] == header

    asyncio.run(scenario())


def test_cross_batch_rank_cannot_replace_missing_rank(scoring_server) -> None:
    # The first batch is valid; replaying its rank in the second must fail.
    scoring_server.responder = lambda body: (200, b'{"scores":[{"rank":1,"score":0.9}]}')

    async def scenario() -> None:
        async with httpx.AsyncClient(trust_env=False) as client:
            with pytest.raises(ValueError):
                await HTTPMemoryReranker(scoring_server.endpoint, client=client, batch_size=1).rerank("q", _hits(3), 2)

    asyncio.run(scenario())
    assert len(scoring_server.requests) == 2


def test_negative_zero_and_large_integer_scores(scoring_server) -> None:
    scores = [-(10**400), -1.5, -0.0, 0, 10**400, 10**400 + 1]
    scoring_server.responder = lambda body: (
        200,
        json.dumps({
            "scores": [
                {"rank": item["rank"], "score": scores[item["rank"] - 1]} for item in reversed(body["candidates"])
            ]
        }).encode(),
    )

    async def scenario() -> None:
        async with httpx.AsyncClient(trust_env=False) as client:
            decision = await HTTPMemoryReranker(scoring_server.endpoint, client=client, batch_size=2).rerank(
                "q", _hits(6), 6
            )
        assert decision.selected_ranks == (6, 5, 3, 4, 2, 1)

    asyncio.run(scenario())


def test_repeated_and_concurrent_calls_keep_separate_state(scoring_server) -> None:
    async def scenario() -> None:
        async with httpx.AsyncClient(trust_env=False) as client:
            reranker = HTTPMemoryReranker(scoring_server.endpoint, client=client, batch_size=2)
            first, second = await asyncio.gather(
                reranker.rerank("first", _hits(5), 2), reranker.rerank("second", _hits(3), 1)
            )
            third = await reranker.rerank("third", _hits(1), 1)
        assert first.selected_ranks == (4, 3) and first.usage.requests == 3
        assert second.selected_ranks == (3,) and second.usage.requests == 2
        assert third.selected_ranks == (1,) and third.usage.requests == 1

    asyncio.run(scenario())
    assert len(scoring_server.requests) == 6


def test_native_memory_preserves_all_hit_fields_and_usage(scoring_server) -> None:
    from powercontext.builtin.artifacts.memory import MemoryEntryInput
    from powercontext.builtin.persistence.sqlite import SQLiteConfig
    from powercontext.builtin.runtime import BuiltinConfig, open_builtin_contexts

    async def scenario() -> None:
        async with httpx.AsyncClient(trust_env=False) as client:
            reranker = HTTPMemoryReranker(scoring_server.endpoint, client=client, batch_size=2, policy_id="local-test")
            async with open_builtin_contexts(
                BuiltinConfig(database=SQLiteConfig()), memory_reranker=reranker
            ) as contexts:
                service = (await contexts.get("http-rerank-test")).artifacts.memory
                memory = await service.remember(
                    memory=None,
                    entries=tuple(
                        MemoryEntryInput(kind="fact", text=f"Project {word} fact.")
                        for word in ["alpha", "beta", "gamma", "delta", "epsilon", "zeta"]
                    ),
                    mode="append",
                )
                assert memory is not None
                result = await service.search("project", memories=(memory,), limit=3, mode="fts")
                assert result.rerank is not None
                trace = result.rerank
                assert len(trace.candidate_hits) == 6
                assert trace.selected_ranks == (4, 3, 2)
                assert result.hits == tuple(trace.candidate_hits[rank - 1] for rank in trace.selected_ranks)
                assert trace.usage.requests == len(scoring_server.requests) == 3
                assert trace.policy_id == "local-test"
                assert not trace.used_fallback and trace.discarded_rank_count == 0
            assert not client.is_closed

    asyncio.run(scenario())
