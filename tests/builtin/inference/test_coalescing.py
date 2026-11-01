"""Offline contract regressions for the coalescing embedding model."""

from __future__ import annotations

import asyncio
import gc
import math
import runpy
from collections import Counter
from pathlib import Path

import pytest

from powercontext.builtin.artifacts.memory import EmbeddingProfile
from powercontext.builtin.inference import EmbeddingResult, InferenceUsage, embed_query
from powercontext.builtin.inference.coalescing import CoalescingEmbeddingModel


class OfflineEmbedding:
    profile = EmbeddingProfile(profile_id="coalescing-test", model="offline", dimension=2)

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
        self.calls.append(texts)
        return EmbeddingResult(
            vectors=tuple((float(len(text)), float(sum(map(ord, text)))) for text in texts),
            usage=InferenceUsage(requests=2, input_tokens=3 * len(texts), output_tokens=0),
        )


def run(coroutine) -> None:
    async def bounded() -> None:
        await asyncio.wait_for(coroutine, timeout=5)

    asyncio.run(bounded())


@pytest.mark.parametrize("window", [0, 5])
def test_concurrent_order_exact_text_identity_and_usage(window) -> None:
    async def scenario() -> None:
        base = OfflineEmbedding()
        model = CoalescingEmbeddingModel(base, max_batch_size=2, coalesce_ms=window)
        first_texts = ("same", "", "same", " e\u0301 ", "é")
        second_texts = ("é", "", "same")
        first, second = await asyncio.gather(model.embed(first_texts), model.embed(second_texts))
        assert model.profile is base.profile
        assert Counter(text for batch in base.calls for text in batch) == Counter(dict.fromkeys(first_texts, 1))
        for texts, result in [(first_texts, first), (second_texts, second)]:
            assert result.vectors == tuple((float(len(text)), float(sum(map(ord, text)))) for text in texts)
            batches = [batch for batch in base.calls if set(texts).intersection(batch)]
            assert result.usage.requests == 2 * len(batches)
            assert result.usage.input_tokens == sum(3 * len(batch) for batch in batches)
            assert result.usage.output_tokens == 0
        cached = await model.embed(first_texts)
        assert cached.vectors == first.vectors
        assert cached.usage.requests == 0

    run(scenario())


@pytest.mark.parametrize("cache_size", [0, 2])
def test_late_waiter_survives_first_waiter_cancellation(cache_size) -> None:
    class Blocked(OfflineEmbedding):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
            self.started.set()
            await self.release.wait()
            return await super().embed(texts)

    async def scenario() -> None:
        base = Blocked()
        model = CoalescingEmbeddingModel(base, coalesce_ms=0, cache_size=cache_size)
        first = asyncio.create_task(model.embed(("shared", "shared")))
        await base.started.wait()
        late = asyncio.create_task(model.embed(("shared",)))
        await asyncio.sleep(0)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        base.release.set()
        result = await late
        assert result.vectors == ((6.0, 631.0),)
        assert result.usage.requests == 2
        assert base.calls == [("shared",)]
        again = await model.embed(("shared",))
        assert len(base.calls) == (2 if cache_size == 0 else 1)
        assert again.usage.requests == (2 if cache_size == 0 else 0)

    run(scenario())


@pytest.mark.parametrize("cache_size", [0, 8])
@pytest.mark.parametrize("query", [False, True])
def test_zero_vector_late_waiter_cancellation_and_cache_usage(cache_size, query) -> None:
    class ZeroEmbedding(OfflineEmbedding):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
            self.calls.append(texts)
            self.started.set()
            await self.release.wait()
            return EmbeddingResult(
                vectors=tuple((0.0, 0.0) if text == "" else (3.0, 4.0) for text in texts),
                usage=InferenceUsage(requests=3, input_tokens=7, output_tokens=2),
            )

        async def embed_query(self, texts: tuple[str, ...], /) -> EmbeddingResult:
            return await self.embed(texts)

    async def scenario() -> None:
        base = ZeroEmbedding()
        model = CoalescingEmbeddingModel(base, coalesce_ms=0, cache_size=cache_size)
        embed = model.embed_query if query else model.embed
        owner = asyncio.create_task(embed(("", "alpha")))
        await base.started.wait()
        late = asyncio.create_task(embed(("", "", "alpha")))
        await asyncio.sleep(0)
        owner.cancel()
        with pytest.raises(asyncio.CancelledError):
            await owner
        base.release.set()
        result = await late
        assert result.vectors == ((0.0, 0.0), (0.0, 0.0), (3.0, 4.0))
        assert result.usage == InferenceUsage(requests=3, input_tokens=7, output_tokens=2)
        assert base.calls == [("", "alpha")]
        repeated = await embed(("alpha", "", ""))
        assert repeated.vectors == ((3.0, 4.0), (0.0, 0.0), (0.0, 0.0))
        assert repeated.usage.requests == (0 if cache_size else 3)
        assert base.calls == ([("", "alpha")] if cache_size else [("", "alpha"), ("alpha", "")])

    run(scenario())


def test_partial_failure_does_not_block_independent_batches_or_retry() -> None:
    class Flaky(OfflineEmbedding):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.fail = True

        async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
            if texts == ("bad",) and self.fail:
                self.fail = False
                self.started.set()
                await self.release.wait()
                msg = "provider unavailable"
                raise RuntimeError(msg)
            return await super().embed(texts)

    async def scenario() -> None:
        base = Flaky()
        model = CoalescingEmbeddingModel(base, max_batch_size=1, coalesce_ms=0)
        mixed = asyncio.create_task(model.embed(("bad", "good")))
        await base.started.wait()
        good = await model.embed(("good",))
        assert good.vectors[0][0] == 4
        assert not mixed.done()
        bad = asyncio.create_task(model.embed(("bad",)))
        await asyncio.sleep(0)
        base.release.set()
        for caller in (mixed, bad):
            with pytest.raises(RuntimeError, match="provider unavailable"):
                await caller
        assert (await model.embed(("bad",))).vectors[0][0] == 3
        assert base.calls.count(("good",)) == 1

    run(scenario())


@pytest.mark.parametrize("count", [0, 1, 3])
def test_bad_cardinality_rejects_entire_batch_and_can_retry(count) -> None:
    class Invalid(OfflineEmbedding):
        fail = True

        async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
            if self.fail:
                self.fail = False
                return EmbeddingResult(vectors=((1.0, 0.0),) * count)
            return await super().embed(texts)

    async def scenario() -> None:
        base = Invalid()
        model = CoalescingEmbeddingModel(base, coalesce_ms=0)
        with pytest.raises(ValueError):
            await model.embed(("a", "b"))
        assert (await model.embed(("a", "b"))).vectors == ((1.0, 97.0), (1.0, 98.0))
        assert base.calls == [("a", "b")]

    run(scenario())


@pytest.mark.parametrize(
    "bad_vector",
    [
        (1.0,),
        (1.0, 2.0, 3.0),
        (float("nan"), 1.0),
        (float("inf"), 1.0),
        (1.0, -float("inf")),
        (0.0, 0.0),
        (-0.0, 0.0),
    ],
    ids=["short", "long", "nan", "infinity", "negative-infinity", "zero", "signed-zero"],
)
@pytest.mark.parametrize("query", [False, True], ids=["document", "query"])
def test_successful_vectors_are_cached_independently_of_memory_validation(bad_vector, query) -> None:
    class InvalidOnce(OfflineEmbedding):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.fail = True

        async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
            if "bad" in texts and self.fail:
                self.fail = False
                self.calls.append(texts)
                self.started.set()
                await self.release.wait()
                return EmbeddingResult(
                    vectors=tuple(bad_vector if text == "bad" else (4.0, 425.0) for text in texts),
                    usage=InferenceUsage(requests=3, input_tokens=17, output_tokens=5),
                )
            return await super().embed(texts)

        async def embed_query(self, texts: tuple[str, ...], /) -> EmbeddingResult:
            return await self.embed(texts)

    async def scenario() -> None:
        base = InvalidOnce()
        model = CoalescingEmbeddingModel(base, max_batch_size=2, coalesce_ms=0, cache_size=16)
        embed = model.embed_query if query else model.embed
        first = asyncio.create_task(embed(("good", "bad")))
        await base.started.wait()
        late = asyncio.create_task(embed(("bad",)))
        # The independent batch must succeed even while another batch waits.
        assert (await embed(("independent",))).vectors[0][0] == 11
        base.release.set()
        results = await asyncio.gather(first, late)
        assert results[0].vectors[0] == (4.0, 425.0)
        for result in results:
            returned = result.vectors[-1]
            assert len(returned) == len(bad_vector)
            for actual, expected in zip(returned, bad_vector, strict=True):
                assert math.isnan(actual) if math.isnan(expected) else actual == expected
            assert result.usage == InferenceUsage(requests=3, input_tokens=17, output_tokens=5)
        assert base.calls.count(("good", "bad")) == 1
        assert (await embed(("good",))).usage.requests == 0
        cached = await embed(("bad", "good", "bad"))
        assert cached.vectors[1] == (4.0, 425.0)
        for index in (0, 2):
            for actual, expected in zip(cached.vectors[index], bad_vector, strict=True):
                assert math.isnan(actual) if math.isnan(expected) else actual == expected
        assert cached.usage.requests == 0
        assert base.calls == [("good", "bad"), ("independent",)]

    run(scenario())


@pytest.mark.parametrize(
    ("normalization", "vector"),
    [
        ("none", (0.0, -0.0)),
        ("unit", (3.0, 4.0)),
        ("unit", (float.fromhex("0x1.fffffffffffffp+1023"), 1.0)),
        ("unit", (float.fromhex("0x0.0000000000001p-1022"), 0.0)),
    ],
    ids=["none-zero", "unit-unnormalized", "unit-large", "unit-subnormal"],
)
@pytest.mark.parametrize("query", [False, True], ids=["document", "query"])
def test_valid_profile_vectors_are_cached_without_modification(normalization, vector, query) -> None:
    class Fixed(OfflineEmbedding):
        profile = EmbeddingProfile(
            profile_id="profile-boundary", model="offline", dimension=2, normalization=normalization
        )

        async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
            self.calls.append(texts)
            return EmbeddingResult(vectors=tuple(vector for _ in texts), usage=InferenceUsage(requests=3))

        async def embed_query(self, texts: tuple[str, ...], /) -> EmbeddingResult:
            return await self.embed(texts)

    async def scenario() -> None:
        base = Fixed()
        model = CoalescingEmbeddingModel(base, coalesce_ms=0)
        embed = model.embed_query if query else model.embed
        first = await embed(("value",))
        cached = await embed(("value",))
        assert first.vectors == cached.vectors == (vector,)
        assert first.usage.requests == 3
        assert cached.usage.requests == 0
        assert base.calls == [("value",)]

    run(scenario())


@pytest.mark.parametrize("cache_size", [0, 8])
def test_original_official_provider_empty_string_cache_budget(cache_size) -> None:
    official = Path(__file__).resolve().parents[3] / (
        "competition/challenges/memory-02-embedding-batches/acceptance/test_coalescing.py"
    )
    provider_class = runpy.run_path(str(official))["Embedding"]

    async def scenario() -> None:
        base = provider_class()
        model = CoalescingEmbeddingModel(base, coalesce_ms=0, cache_size=cache_size)
        assert model.profile is base.profile
        first = await model.embed(("",))
        second = await model.embed(("",))
        assert first.vectors == second.vectors == ((0.0,),)
        assert first.usage.requests == 1
        assert second.usage.requests == int(not cache_size)
        assert base.calls == [("",)] * (2 if not cache_size else 1)

    run(scenario())


@pytest.mark.parametrize("cache_size", [0, 8])
@pytest.mark.parametrize("normalization", ["unit", "none"])
@pytest.mark.parametrize("separate_callers", [False, True])
def test_official_provider_empty_text_result_and_neighbor_cache(cache_size, normalization, separate_callers) -> None:
    official = Path(__file__).resolve().parents[3] / (
        "competition/challenges/memory-02-embedding-batches/acceptance/test_coalescing.py"
    )
    provider_class = runpy.run_path(str(official))["Embedding"]

    async def scenario() -> None:
        provider = provider_class()
        provider.profile = provider.profile.model_copy(update={"normalization": normalization})
        texts = ("", "alpha", "")
        direct = await provider.embed(texts)
        model = CoalescingEmbeddingModel(provider, coalesce_ms=0, cache_size=cache_size)
        if separate_callers:
            zero, alpha = await asyncio.gather(model.embed(("", "")), model.embed(("alpha",)))
            assert zero.vectors == ((0.0,), (0.0,))
            assert alpha.vectors == ((5.0,),)
            assert zero.usage.requests == alpha.usage.requests == 1
        else:
            result = await model.embed(texts)
            assert result.vectors == direct.vectors == ((0.0,), (5.0,), (0.0,))
            assert result.usage.requests == 1
        again = await model.embed(texts)
        assert again.vectors == direct.vectors
        expected_calls = [texts, ("", "alpha")]
        if not cache_size:
            expected_calls.append(("", "alpha"))
        assert again.usage.requests == int(not cache_size)
        assert provider.calls == expected_calls
        cached_alpha = await model.embed(("alpha",))
        assert cached_alpha.vectors == ((5.0,),)
        assert cached_alpha.usage.requests == int(not cache_size)
        if not cache_size:
            expected_calls.append(("alpha",))
        assert provider.calls == expected_calls

    run(scenario())


def test_lru_access_refresh_and_cached_result_are_independent() -> None:
    async def scenario() -> None:
        base = OfflineEmbedding()
        model = CoalescingEmbeddingModel(base, cache_size=2, coalesce_ms=0)
        await model.embed(("a", "b"))
        cached = await model.embed(("a",))
        cached.vectors = ((999.0,),)
        cached.usage.requests = 999
        await model.embed(("c",))
        assert (await model.embed(("a",))).vectors == ((1.0, 97.0),)
        await model.embed(("b",))
        assert base.calls == [("a", "b"), ("c",), ("b",)]

    run(scenario())


def test_empty_and_mixed_cache_hits_preserve_provider_token_accounting() -> None:
    class MixedUsage(OfflineEmbedding):
        async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
            result = await super().embed(texts)
            if texts == ("unknown",):
                result.usage = InferenceUsage(requests=4)
            return result

    async def scenario() -> None:
        base = MixedUsage()
        model = CoalescingEmbeddingModel(base, max_batch_size=1, coalesce_ms=0)
        empty = await model.embed(())
        assert empty.vectors == () and empty.usage.requests == 0 and base.calls == []
        await model.embed(("cached",))
        result = await model.embed(("cached", "known", "unknown", "known"))
        assert result.usage.requests == 6
        assert result.usage.input_tokens == 3
        assert result.usage.output_tokens == 0
        assert len(result.vectors) == 4

    run(scenario())


def test_all_waiters_cancelled_failure_is_observed_and_retryable() -> None:
    class Abandoned(OfflineEmbedding):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.finished = asyncio.Event()
            self.fail = True

        async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
            if self.fail:
                self.fail = False
                self.started.set()
                await self.release.wait()
                self.finished.set()
                msg = "abandoned failure"
                raise RuntimeError(msg)
            return await super().embed(texts)

    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        errors = []
        loop.set_exception_handler(lambda _, context: errors.append(context))
        base = Abandoned()
        model = CoalescingEmbeddingModel(base, coalesce_ms=0)
        callers = [asyncio.create_task(model.embed(("a", "b"))) for _ in range(2)]
        await base.started.wait()
        for caller in callers:
            caller.cancel()
        await asyncio.gather(*callers, return_exceptions=True)
        base.release.set()
        await base.finished.wait()
        await asyncio.sleep(0)
        gc.collect()
        assert errors == []
        assert len((await model.embed(("a", "b"))).vectors) == 2

    run(scenario())


def test_cancellation_before_dispatch_keeps_surviving_caller() -> None:
    async def scenario() -> None:
        base = OfflineEmbedding()
        model = CoalescingEmbeddingModel(base, coalesce_ms=10)
        first = asyncio.create_task(model.embed(("x",)))
        survivor = asyncio.create_task(model.embed(("x",)))
        await asyncio.sleep(0)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert (await survivor).vectors == ((1.0, 120.0),)
        assert base.calls == [("x",)]

    run(scenario())


def test_provider_cancellation_is_not_cached() -> None:
    class CancelOnce(OfflineEmbedding):
        fail = True

        async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
            if self.fail:
                self.fail = False
                raise asyncio.CancelledError
            return await super().embed(texts)

    async def scenario() -> None:
        model = CoalescingEmbeddingModel(CancelOnce(), coalesce_ms=0)
        with pytest.raises(asyncio.CancelledError):
            await model.embed(("retry",))
        assert (await model.embed(("retry",))).vectors[0][0] == 5

    run(scenario())


def test_failed_batch_returns_without_waiting_for_unrelated_blocked_batch() -> None:
    class Independent(OfflineEmbedding):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
            if texts == ("blocked",):
                self.started.set()
                await self.release.wait()
            else:
                await self.started.wait()
                msg = "failed batch"
                raise RuntimeError(msg)
            return await super().embed(texts)

    async def scenario() -> None:
        base = Independent()
        model = CoalescingEmbeddingModel(base, max_batch_size=1, coalesce_ms=0)
        with pytest.raises(RuntimeError, match="failed batch"):
            await model.embed(("blocked", "bad"))
        survivor = asyncio.create_task(model.embed(("blocked",)))
        await asyncio.sleep(0)
        base.release.set()
        assert (await survivor).vectors[0][0] == 7
        assert base.calls == [("blocked",)]

    run(scenario())


def test_cache_is_cold_on_new_wrapper_and_cross_loop_reuse_is_explicitly_rejected() -> None:
    base = OfflineEmbedding()
    model = CoalescingEmbeddingModel(base, coalesce_ms=0)
    asyncio.run(model.embed(("same",)))
    with pytest.raises(RuntimeError, match="single event loop"):
        asyncio.run(model.embed(("same",)))
    replacement = CoalescingEmbeddingModel(base, coalesce_ms=0)
    asyncio.run(replacement.embed(("same",)))
    assert base.calls == [("same",), ("same",)]


def test_wrapper_instances_do_not_share_cache_or_pending_work() -> None:
    async def scenario() -> None:
        first_base, second_base = OfflineEmbedding(), OfflineEmbedding()
        first = CoalescingEmbeddingModel(first_base, coalesce_ms=0)
        second = CoalescingEmbeddingModel(second_base, coalesce_ms=0)
        await asyncio.gather(first.embed(("x",)), second.embed(("x",)))
        assert first_base.calls == second_base.calls == [("x",)]

    run(scenario())


def test_symmetric_queries_share_document_cache() -> None:
    async def scenario() -> None:
        base = OfflineEmbedding()
        model = CoalescingEmbeddingModel(base, coalesce_ms=0)
        document = await model.embed(("same",))
        query = await embed_query(model, ("same",))
        assert query.vectors == document.vectors
        assert query.usage.requests == 0
        assert base.calls == [("same",)]

    run(scenario())


def test_asymmetric_queries_are_isolated_from_document_work_and_cache() -> None:
    class Asymmetric(OfflineEmbedding):
        def __init__(self) -> None:
            super().__init__()
            self.queries: list[tuple[str, ...]] = []

        async def embed_query(self, texts: tuple[str, ...], /) -> EmbeddingResult:
            self.queries.append(texts)
            return EmbeddingResult(vectors=tuple((-1.0, 0.0) for _ in texts))

    async def scenario() -> None:
        base = Asymmetric()
        model = CoalescingEmbeddingModel(base, coalesce_ms=0)
        document, query = await asyncio.gather(model.embed(("same",)), embed_query(model, ("same",)))
        assert document.vectors == ((4.0, 422.0),)
        assert query.vectors == ((-1.0, 0.0),)
        assert (await embed_query(model, ("same",))).vectors == query.vectors
        assert (await model.embed(("same",))).vectors == document.vectors
        assert base.calls == base.queries == [("same",)]

    run(scenario())


def test_many_concurrent_callers_respect_unique_text_budget() -> None:
    async def scenario() -> None:
        base = OfflineEmbedding()
        model = CoalescingEmbeddingModel(base, max_batch_size=7, coalesce_ms=0, cache_size=0)
        inputs = [tuple(str((caller + offset) % 41) for offset in range(60)) for caller in range(100)]
        results = await asyncio.gather(*(model.embed(texts) for texts in inputs))
        assert len(base.calls) == 6
        assert all(0 < len(batch) <= 7 for batch in base.calls)
        assert Counter(text for batch in base.calls for text in batch) == Counter(map(str, range(41)))
        for texts, result in zip(inputs, results, strict=True):
            assert result.vectors == tuple((float(len(text)), float(sum(map(ord, text)))) for text in texts)
            assert result.usage.requests == 12

    run(scenario())


@pytest.mark.parametrize(
    "settings",
    [
        {"max_batch_size": 0},
        {"max_batch_size": -1},
        {"max_batch_size": 1.5},
        {"max_batch_size": True},
        {"cache_size": -1},
        {"cache_size": 1.5},
        {"cache_size": True},
        {"coalesce_ms": -1},
        {"coalesce_ms": float("inf")},
        {"coalesce_ms": float("nan")},
    ],
)
def test_invalid_settings_rejected_before_requests(settings) -> None:
    base = OfflineEmbedding()
    with pytest.raises(ValueError):
        CoalescingEmbeddingModel(base, **settings)
    assert base.calls == []
