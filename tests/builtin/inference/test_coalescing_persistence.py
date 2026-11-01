"""Real SQLite integration; no external embedding provider or credentials."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import textwrap
from pathlib import Path

from powercontext.builtin.artifacts.memory import EmbeddingProfile, MemoryEntryInput
from powercontext.builtin.inference import EmbeddingResult, InferenceUsage
from powercontext.builtin.inference.coalescing import CoalescingEmbeddingModel
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import BuiltinConfig, open_builtin_contexts


class SemanticEmbedding:
    profile = EmbeddingProfile(profile_id="restart-test", model="offline", dimension=2)

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
        self.calls.append(texts)
        return EmbeddingResult(
            vectors=tuple((1.0, 0.0) if "alpha" in text else (0.0, 1.0) for text in texts),
            usage=InferenceUsage(requests=1, input_tokens=len(texts)),
        )


def test_reopen_preserves_memory_identity_vectors_and_scope_isolation(tmp_path: Path) -> None:
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'restart.db'}"))

    async def write():
        base = SemanticEmbedding()
        model = CoalescingEmbeddingModel(base, coalesce_ms=0)
        async with open_builtin_contexts(config, embedding_model=model) as contexts:
            first = (await contexts.get("first")).artifacts.memory
            second = (await contexts.get("second")).artifacts.memory
            reference = await first.remember(
                memory=None,
                entries=(MemoryEntryInput(kind="fact", text="alpha private evidence"),),
                mode="append",
            )
            assert reference is not None
            other = await second.remember(
                memory=None,
                entries=(MemoryEntryInput(kind="fact", text="beta separate evidence"),),
                mode="append",
            )
            assert other is not None
            assert (await first.search("alpha", memories=(reference,), limit=1, mode="vector")).hits[0].text == (
                "alpha private evidence"
            )
            return reference, other

    references = asyncio.run(write())

    async def reopen() -> None:
        # New event loop and wrapper represent a cold process-local cache.
        base = SemanticEmbedding()
        model = CoalescingEmbeddingModel(base, coalesce_ms=0)
        async with open_builtin_contexts(config, embedding_model=model) as contexts:
            first = (await contexts.get("first")).artifacts.memory
            second = (await contexts.get("second")).artifacts.memory
            for service, reference, query, expected in (
                (first, references[0], "alpha", "alpha private evidence"),
                (second, references[1], "beta", "beta separate evidence"),
            ):
                result = await service.search(query, memories=(reference,), limit=1, mode="vector")
                assert result.hits[0].text == expected
                assert result.hits[0].memory_ref == reference.as_ref()
            assert base.calls == [("alpha",), ("beta",)], "persisted documents must not be re-embedded on reopen"
            isolated = await second.search("alpha", memories=(references[1],), limit=10, mode="vector")
            assert all(hit.text != "alpha private evidence" for hit in isolated.hits)
            assert base.calls == [("alpha",), ("beta",)], "the shared query is already cached"

    asyncio.run(reopen())

    # Also prove that durable indexes and exact identities survive a completely
    # new interpreter, with no wrapper, event loop, or Memory object in common.
    (tmp_path / "memories.json").write_text(
        json.dumps([reference.model_dump(mode="json") for reference in references]), encoding="utf-8"
    )
    script = textwrap.dedent(
        """
        import asyncio
        import json
        import sys
        from pathlib import Path
        from powercontext.builtin.artifacts.memory import Memory
        from powercontext.builtin.inference import coalescing
        from powercontext.builtin.persistence.sqlite import SQLiteConfig
        from powercontext.builtin.runtime import BuiltinConfig, open_builtin_contexts
        from tests.builtin.inference.test_coalescing_persistence import SemanticEmbedding

        root, data = map(Path, sys.argv[1:])
        assert Path(coalescing.__file__).resolve().is_relative_to(root / "src")
        memories = [Memory.model_validate(value) for value in json.loads((data / "memories.json").read_text())]

        async def verify():
            base = SemanticEmbedding()
            model = coalescing.CoalescingEmbeddingModel(base, coalesce_ms=0)
            config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{data / 'restart.db'}"))
            async with open_builtin_contexts(config, embedding_model=model) as contexts:
                for scope, memory, query, expected in zip(
                    ("first", "second"), memories, ("alpha", "beta"),
                    ("alpha private evidence", "beta separate evidence"), strict=True,
                ):
                    service = (await contexts.get(scope)).artifacts.memory
                    result = await service.search(query, memories=(memory,), limit=1, mode="vector")
                    assert result.hits[0].text == expected
                    assert result.hits[0].memory_ref == memory.as_ref()
                assert base.calls == [("alpha",), ("beta",)]
            print("fresh-process SQLite identity and vector readback passed")

        asyncio.run(verify())
        """
    )
    root = Path(__file__).resolve().parents[3]
    process = subprocess.run(
        [sys.executable, "-c", script, str(root), str(tmp_path)],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    assert "fresh-process SQLite identity and vector readback passed" in process.stdout
