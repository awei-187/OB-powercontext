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

"""Transactional source dependency eligibility, independent of immutable evidence."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator
from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from powercontext.artifacts import ArtifactRef, MemoryCitation
from powercontext.builtin.artifacts.memory import MemoryService
from powercontext.builtin.persistence.tables import SOURCE_LIFECYCLE_NODES_TABLE
from powercontext.builtin.sources import validate_scope_id
from powercontext.sources import SourceRef

if TYPE_CHECKING:
    from powercontext.builtin.runtime.application import BuiltinRuntime
    from powercontext.builtin.runtime.relational import RelationalContexts


class SourceLifecycleError(ValueError):
    """Invalid lifecycle registration, event, or resolution request."""

    def __init__(self, code: str) -> None:
        self.code = code
        messages = {
            "invalid-text": "node IDs and reasons must be nonblank strings",
            "invalid-source": "a SourceRef and positive integer revision are required",
            "invalid-memory": "a Memory citation is required",
            "invalid-topic": "a Topic Memory reference is required",
            "invalid-policy": "policy must be all or any",
            "empty-parents": "derived nodes require parents",
            "duplicate-parents": "duplicate parents and self-dependencies are forbidden",
            "binding-conflict": "node is already bound differently",
            "missing-parent": "parents must already be registered",
            "citation-membership": "citation is not present in the referenced Memory revision",
            "noncurrent-body": "registered Memory body must still be current",
            "unknown-source": "unknown Source or mismatched lifecycle revision",
            "event-conflict": "stale or conflicting lifecycle event",
            "invalid-graph": "stored dependency graph is cyclic or incomplete",
            "body-changed": "registered Memory body changed outside lifecycle management",
            "unknown-purpose": "unknown lifecycle resolution purpose",
            "unavailable-node": "unknown or unavailable lifecycle node",
            "unreadable-reference": "lifecycle reference cannot be read in this scope",
        }
        super().__init__(messages.get(code, code))


def _nonblank(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SourceLifecycleError("invalid-text")
    return value


class SourceLifecycleEvent(BaseModel):
    """One strictly typed, immutable Source state transition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: StrictStr
    revision: StrictInt = Field(gt=0)
    sequence: StrictInt = Field(gt=0)
    available: StrictBool
    reason: StrictStr

    @field_validator("node_id", "reason")
    @classmethod
    def nonblank(cls, value: str) -> str:
        return _nonblank(value)


class _Node(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str
    kind: Literal["source", "memory", "topic"]
    reference: SourceRef | MemoryCitation | ArtifactRef
    parents: tuple[str, ...] = ()
    policy: Literal["all", "any"] = "all"
    revision: int | None = None
    available: bool = True
    event: SourceLifecycleEvent | None = None

    def binding(self) -> dict[str, object]:
        return self.model_dump(exclude={"available", "event"})


class SourceLifecycleApplication:
    """Select a durable dependency graph in the Runtime's own database."""

    def __init__(self, runtime: BuiltinRuntime, contexts: RelationalContexts) -> None:
        self.runtime = runtime
        self.contexts = contexts

    def for_scope(self, scope_id: str, /) -> ScopedSourceLifecycle:
        return ScopedSourceLifecycle(self, validate_scope_id(scope_id))


class ScopedSourceLifecycle:
    """Single-writer DAG whose native state changes commit with its event."""

    def __init__(self, application: SourceLifecycleApplication, scope_id: str) -> None:
        self._application = application
        self.scope_id = scope_id

    @asynccontextmanager
    async def _transaction(self) -> AsyncGenerator[AsyncConnection, None]:
        runtime = self._application.runtime
        async with (
            runtime._scope_operation(self.scope_id),
            runtime._locked(self.scope_id),
            self._application.contexts.database.transaction() as connection,
        ):
            yield connection

    def _memory(self, connection: AsyncConnection) -> MemoryService:
        services = self._application.contexts._services_for(self.scope_id)
        _, catalog = services.sources(connection)
        return services.memory(catalog, connection)

    async def _load(self, connection: AsyncConnection) -> dict[str, _Node]:
        rows = await connection.scalars(
            select(SOURCE_LIFECYCLE_NODES_TABLE.c.payload).where(
                SOURCE_LIFECYCLE_NODES_TABLE.c.scope_id == self.scope_id
            )
        )
        nodes = (_Node.model_validate_json(payload) for payload in rows)
        return {node.node_id: node for node in nodes}

    async def _store(self, connection: AsyncConnection, node: _Node, *, new: bool = False) -> None:
        table = SOURCE_LIFECYCLE_NODES_TABLE
        key = hashlib.sha256(node.node_id.encode("utf-8")).hexdigest()
        values = {
            "payload": node.model_dump_json(),
            "available": node.available,
            "topic_artifact_id": node.reference.artifact_id if isinstance(node.reference, ArtifactRef) else None,
        }
        if new:
            statement = insert(table).values(scope_id=self.scope_id, node_key=key, **values)
        else:
            statement = update(table).where(table.c.scope_id == self.scope_id, table.c.node_key == key).values(**values)
        await connection.execute(statement)

    async def register_source(self, node_id: str, source_ref: SourceRef, *, revision: int) -> None:
        _nonblank(node_id)
        if type(revision) is not int or revision <= 0 or not isinstance(source_ref, SourceRef):
            raise SourceLifecycleError("invalid-source")
        await self._register(_Node(node_id=node_id, kind="source", reference=source_ref, revision=revision))

    async def register_memory(
        self, node_id: str, citation: MemoryCitation, *, parents: tuple[str, ...], policy: str
    ) -> None:
        if not isinstance(citation, MemoryCitation) or citation.memory_ref.family != "memory":
            raise SourceLifecycleError("invalid-memory")
        await self._register_derived(node_id, "memory", citation, parents, policy)

    async def register_topic(
        self, node_id: str, artifact_ref: ArtifactRef, *, parents: tuple[str, ...], policy: str
    ) -> None:
        if not isinstance(artifact_ref, ArtifactRef) or artifact_ref.family != "topic-memory":
            raise SourceLifecycleError("invalid-topic")
        await self._register_derived(node_id, "topic", artifact_ref, parents, policy)

    async def _register_derived(
        self,
        node_id: str,
        kind: Literal["memory", "topic"],
        reference: MemoryCitation | ArtifactRef,
        parents: tuple[str, ...],
        policy: str,
    ) -> None:
        _nonblank(node_id)
        if policy not in ("all", "any"):
            raise SourceLifecycleError("invalid-policy")
        if not isinstance(parents, (tuple, list)) or not parents:
            raise SourceLifecycleError("empty-parents")
        for parent in parents:
            _nonblank(parent)
        if len(set(parents)) != len(parents) or node_id in parents:
            raise SourceLifecycleError("duplicate-parents")
        await self._register(
            _Node(node_id=node_id, kind=kind, reference=reference, parents=tuple(sorted(parents)), policy=policy)
        )

    async def _register(self, node: _Node) -> None:
        async with self._transaction() as connection:
            nodes = await self._load(connection)
            previous = nodes.get(node.node_id)
            if previous is not None and previous.binding() != node.binding():
                raise SourceLifecycleError("binding-conflict")
            if any(parent not in nodes for parent in node.parents):
                raise SourceLifecycleError("missing-parent")
            # Requiring existing parents and immutable bindings also prevents cycles.
            await self._validate_reference(connection, node)
            if previous is not None:
                return
            if node.kind != "source":
                supported = (nodes[parent].available for parent in node.parents)
                node = node.model_copy(update={"available": all(supported) if node.policy == "all" else any(supported)})
            nodes[node.node_id] = node
            await self._synchronize_memory(connection, nodes, reason="source lifecycle registration")
            await self._store(connection, node, new=True)

    async def _validate_reference(self, connection: AsyncConnection, node: _Node) -> None:
        repositories = self._application.contexts.repositories
        try:
            if isinstance(node.reference, SourceRef):
                await repositories.sources.get(connection, self.scope_id, node.reference)
            elif isinstance(node.reference, ArtifactRef):
                await repositories.artifacts.get(connection, self.scope_id, node.reference)
            else:
                service = self._memory(connection)
                citation = node.reference
                exact = await service.revision(citation.memory_ref)
                if not any(
                    item.entry_id == citation.entry_id and item.entry_version_id == citation.entry_version_id
                    for item in exact.content.manifest.entries
                ):
                    raise SourceLifecycleError("citation-membership")
                await service.validate_citation(citation)
                head = await service.head(citation.memory_ref.artifact_id)
                if not any(
                    item.entry_id == citation.entry_id and item.entry_version_id == citation.entry_version_id
                    for item in head.content.manifest.entries
                ):
                    raise SourceLifecycleError("noncurrent-body")
        except (ValueError, LookupError) as error:
            raise SourceLifecycleError("unreadable-reference") from error

    async def apply(self, event: SourceLifecycleEvent) -> list[str]:
        # Revalidate even model_construct/model_copy inputs at the public boundary.
        event = SourceLifecycleEvent.model_validate(event.model_dump())
        async with self._transaction() as connection:
            nodes = await self._load(connection)
            source = nodes.get(event.node_id)
            if source is None or source.kind != "source" or source.revision != event.revision:
                raise SourceLifecycleError("unknown-source")
            previous = source.event
            if previous is not None:
                if event.sequence < previous.sequence or (event.sequence == previous.sequence and event != previous):
                    raise SourceLifecycleError("event-conflict")
                if event == previous:
                    return sorted(node_id for node_id, node in nodes.items() if node.available)
            original = dict(nodes)
            nodes[event.node_id] = source.model_copy(update={"event": event, "available": event.available})
            pending = {node_id for node_id, node in nodes.items() if node.kind != "source"}
            evaluated = set(nodes) - pending
            while pending:
                ready = sorted(node_id for node_id in pending if set(nodes[node_id].parents) <= evaluated)
                if not ready:
                    raise SourceLifecycleError("invalid-graph")
                for node_id in ready:
                    node = nodes[node_id]
                    support = (nodes[parent].available for parent in node.parents)
                    available = all(support) if node.policy == "all" else any(support)
                    nodes[node_id] = node.model_copy(update={"available": available})
                evaluated.update(ready)
                pending.difference_update(ready)
            await self._synchronize_memory(connection, nodes, reason=event.reason)
            for node_id, node in nodes.items():
                if node != original[node_id]:
                    await self._store(connection, node)
            return sorted(node_id for node_id, node in nodes.items() if node.available)

    async def _synchronize_memory(self, connection: AsyncConnection, nodes: dict[str, _Node], *, reason: str) -> None:
        service = self._memory(connection)
        bindings: dict[str, dict[str, tuple[MemoryCitation, bool]]] = {}
        for node in nodes.values():
            if isinstance(node.reference, MemoryCitation):
                citation = node.reference
                entries = bindings.setdefault(citation.memory_ref.artifact_id, {})
                previous = entries.get(citation.entry_id)
                # Graph nodes keep their own policy; independent aliases can each
                # support this exact native body. Never merge by text or across scopes.
                if previous is not None and previous[0].entry_version_id != citation.entry_version_id:
                    raise SourceLifecycleError("body-changed")
                available = node.available or (previous is not None and previous[1])
                entries[citation.entry_id] = (citation, available)
        for artifact_id, expected in bindings.items():
            head, versions = await service.head_entries(artifact_id)
            current = {entry.entry_id: entry for entry in versions}
            for entry_id, (citation, _) in expected.items():
                if entry_id not in current or current[entry_id].entry_version_id != citation.entry_version_id:
                    raise SourceLifecycleError("body-changed")
            for available in (False, True):
                changed = tuple(
                    current[item.entry_id]
                    for item in head.content.manifest.entries
                    if item.entry_id in expected
                    and expected[item.entry_id][1] == available
                    and (item.state == "active") != available
                )
                if changed:
                    operation = service.reactivate if available else service.forget
                    head = await operation(head, entries=changed, reason=reason)

    async def resolve(self, node_id: str, *, purpose: str) -> SourceRef | MemoryCitation | ArtifactRef:
        _nonblank(node_id)
        if purpose not in ("generation", "audit"):
            raise SourceLifecycleError("unknown-purpose")
        async with self._transaction() as connection:
            node = (await self._load(connection)).get(node_id)
            if node is None or (purpose == "generation" and not node.available):
                raise SourceLifecycleError("unavailable-node")
            return node.reference


__all__ = ["SourceLifecycleError", "SourceLifecycleEvent"]
