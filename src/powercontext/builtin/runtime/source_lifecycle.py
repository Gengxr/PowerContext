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

"""Propagate Source withdrawal and restoration through explicit evidence dependencies.

Each scope holds a DAG of Source, Memory and Topic Memory nodes registered by the caller.
A derived node is usable when ``all`` or ``any`` of its parents are usable. The usable set
is persisted with every registration and event, and mirrored onto native state: Memory
entries are deactivated or reactivated, and unsupported Topic Memory is hidden from search
and Context. Registered references are never rewritten, so audits can still read the
exact historical content.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, insert, select, update

from powercontext.artifacts import ArtifactRef
from powercontext.builtin.artifacts.memory.models import MemoryCitation
from powercontext.builtin.persistence.tables import SOURCE_LIFECYCLE_NODES_TABLE
from powercontext.builtin.runtime.models import GetMemoryEntryRequest
from powercontext.builtin.sources import validate_scope_id
from powercontext.builtin.statistics import ModelUsagePurpose
from powercontext.sources.models import SourceRef

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection

    from powercontext.builtin.persistence.database import AsyncDatabase
    from powercontext.builtin.runtime.application import BuiltinRuntime

LifecyclePolicy = Literal["all", "any"]
LifecyclePurpose = Literal["generation", "audit"]
_NodeKind = Literal["source", "memory", "topic"]
_REASON = "source lifecycle"


class SourceLifecycleError(ValueError):
    """Raised when a lifecycle registration, event or resolution violates the contract."""


class SourceLifecycleEvent(BaseModel):
    """One availability change of a registered Source at an exact lifecycle revision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str = Field(strict=True)
    revision: Annotated[int, Field(strict=True, gt=0)]
    sequence: Annotated[int, Field(strict=True, gt=0)]
    available: bool = Field(strict=True)
    reason: str = Field(strict=True)

    @field_validator("node_id", "reason")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")  # noqa: TRY003
        return value


@dataclass(frozen=True, slots=True)
class _Node:
    node_id: str
    ordinal: int
    kind: _NodeKind
    reference: SourceRef | MemoryCitation | ArtifactRef
    parents: tuple[str, ...]
    policy: LifecyclePolicy | None
    revision: int | None
    available: bool
    native_suppressed: bool
    last_event: SourceLifecycleEvent | None

    def binding(self) -> tuple[object, ...]:
        return (self.kind, self.reference, self.parents, self.policy, self.revision)


class ScopedSourceLifecycle:
    """Register evidence dependencies and apply Source lifecycle events in one scope."""

    def __init__(self, runtime: BuiltinRuntime, scope_id: str) -> None:
        self._runtime = runtime
        self.scope_id = scope_id

    async def register_source(self, node_id: str, source_ref: SourceRef, /, *, revision: int) -> None:
        """Register a captured Source root; it starts available at ``revision``."""

        _require_node_id(node_id)
        if not isinstance(source_ref, SourceRef):
            raise SourceLifecycleError("Source nodes require a SourceRef")
        if type(revision) is not int or revision < 1:
            raise SourceLifecycleError("Source lifecycle revision must be a positive integer")
        try:
            await self._runtime.records.for_scope(self.scope_id).get_source(source_ref.source_type, source_ref.source_id)
        except Exception as error:
            raise SourceLifecycleError(f"Source {source_ref.source_id!r} is not readable") from error
        await self._register(node_id, "source", source_ref, (), None, revision)

    async def register_memory(
        self,
        node_id: str,
        citation: MemoryCitation,
        /,
        *,
        parents: tuple[str, ...],
        policy: LifecyclePolicy,
    ) -> None:
        """Register one Memory entry supported by previously registered parents."""

        _require_node_id(node_id)
        if not isinstance(citation, MemoryCitation):
            raise SourceLifecycleError("Memory nodes require a MemoryCitation")
        parents = _validate_parents(node_id, parents, policy)
        try:
            await self._runtime.memory.for_scope(self.scope_id).get(GetMemoryEntryRequest(citation=citation))
        except Exception as error:
            raise SourceLifecycleError(f"Memory entry {citation.entry_id!r} is not readable") from error
        if await self._register(node_id, "memory", citation, parents, policy, None):
            await self._synchronize_memory()

    async def register_topic(
        self,
        node_id: str,
        artifact: ArtifactRef,
        /,
        *,
        parents: tuple[str, ...],
        policy: LifecyclePolicy,
    ) -> None:
        """Register one Topic Memory revision supported by previously registered parents."""

        _require_node_id(node_id)
        if not isinstance(artifact, ArtifactRef) or artifact.family != "topic-memory":
            raise SourceLifecycleError("Topic nodes require a topic-memory ArtifactRef")
        parents = _validate_parents(node_id, parents, policy)
        try:
            await self._runtime.records.for_scope(self.scope_id).get_artifact_revision(
                artifact.family, artifact.artifact_id, artifact.revision
            )
        except Exception as error:
            raise SourceLifecycleError(f"Topic Memory {artifact.artifact_id!r} is not readable") from error
        await self._register(node_id, "topic", artifact, parents, policy, None)

    async def apply(self, event: SourceLifecycleEvent, /) -> list[str]:
        """Apply one Source event, propagate it, and return every available node ID.

        Replaying the last applied event is idempotent but still finishes native
        propagation, so a retry after an interrupted Memory write converges.
        """

        if not isinstance(event, SourceLifecycleEvent):
            raise SourceLifecycleError("apply requires a SourceLifecycleEvent")
        async with (
            self._runtime._scoped_operation(self.scope_id),
            self._runtime._locked(self.scope_id),
            self._database().transaction() as connection,
        ):
            nodes = await _load_nodes(connection, self.scope_id)
            node = nodes.get(event.node_id)
            if node is None or node.kind != "source":
                raise SourceLifecycleError(f"unknown Source node {event.node_id!r}")
            if event.revision != node.revision:
                raise SourceLifecycleError("event revision does not match the Source lifecycle revision")
            last = node.last_event
            replay = last is not None and event.sequence == last.sequence
            if replay and event != last:
                raise SourceLifecycleError("event sequence was already used by a different event")
            if last is not None and event.sequence < last.sequence:
                raise SourceLifecycleError("event sequence must increase")
            if not replay:
                await connection.execute(
                    _node_update(self.scope_id, node.node_id).values(
                        available=event.available, last_event=event.model_dump_json()
                    )
                )
                nodes = await _propagate(connection, self.scope_id)
        await self._synchronize_memory()
        return sorted(node_id for node_id, item in nodes.items() if item.available)

    async def resolve(self, node_id: str, /, *, purpose: LifecyclePurpose) -> SourceRef | MemoryCitation | ArtifactRef:
        """Return the registered reference; ``generation`` requires the node to be available."""

        if purpose not in ("generation", "audit"):
            raise SourceLifecycleError(f"unknown lifecycle purpose {purpose!r}")
        async with self._database().transaction() as connection:
            node = (await _load_nodes(connection, self.scope_id)).get(node_id)
        if node is None:
            raise SourceLifecycleError(f"unknown lifecycle node {node_id!r}")
        if purpose == "generation" and not node.available:
            raise SourceLifecycleError(f"lifecycle node {node_id!r} is not available for generation")
        return node.reference

    async def available(self) -> list[str]:
        """Return every currently available node ID in node ID order."""

        async with self._database().transaction() as connection:
            nodes = await _load_nodes(connection, self.scope_id)
        return sorted(node_id for node_id, node in nodes.items() if node.available)

    async def suppressed_topic_artifacts(self) -> frozenset[str]:
        """Return Topic Memory artifact IDs registered only by unavailable nodes."""

        async with self._database().transaction() as connection:
            nodes = await _load_nodes(connection, self.scope_id)
        topics = [node for node in nodes.values() if node.kind == "topic"]
        hidden = {node.reference.artifact_id for node in topics if not node.available}  # type: ignore[union-attr]
        shown = {node.reference.artifact_id for node in topics if node.available}  # type: ignore[union-attr]
        return frozenset(hidden - shown)

    async def _register(
        self,
        node_id: str,
        kind: _NodeKind,
        reference: SourceRef | MemoryCitation | ArtifactRef,
        parents: tuple[str, ...],
        policy: LifecyclePolicy | None,
        revision: int | None,
    ) -> bool:
        async with (
            self._runtime._scoped_operation(self.scope_id),
            self._runtime._locked(self.scope_id),
            self._database().transaction() as connection,
        ):
            nodes = await _load_nodes(connection, self.scope_id)
            existing = nodes.get(node_id)
            if existing is not None:
                if existing.binding() != (kind, reference, parents, policy, revision):
                    raise SourceLifecycleError(f"lifecycle node {node_id!r} is already bound differently")
                return False
            missing = [parent for parent in parents if parent not in nodes]
            if missing:
                raise SourceLifecycleError(f"unregistered parents {missing!r}")
            available = True if kind == "source" else _supported(policy, [nodes[parent].available for parent in parents])
            ordinal = int(
                await connection.scalar(
                    select(func.max(SOURCE_LIFECYCLE_NODES_TABLE.c.ordinal)).where(
                        SOURCE_LIFECYCLE_NODES_TABLE.c.scope_id == self.scope_id
                    )
                )
                or 0
            )
            await connection.execute(
                insert(SOURCE_LIFECYCLE_NODES_TABLE).values(
                    scope_id=self.scope_id,
                    node_id=node_id,
                    ordinal=ordinal + 1,
                    kind=kind,
                    reference=reference.model_dump_json(),
                    parents=json.dumps(list(parents)),
                    policy=policy,
                    revision=revision,
                    available=available,
                    native_suppressed=False,
                    last_event=None,
                )
            )
        return True

    async def _synchronize_memory(self) -> None:
        """Mirror node availability onto native Memory entry states.

        A node is marked as suppressed before its entry is deactivated, and the mark is
        cleared only after reactivation, so an interrupted write is finished by a retry and
        entries deactivated for other reasons are never reactivated here.
        """

        runtime = self._runtime
        async with runtime._context(self.scope_id, embedding_purpose=ModelUsagePurpose.MEMORY_INDEXING) as context:
            async with runtime._locked(self.scope_id):
                async with self._database().transaction() as connection:
                    nodes = [node for node in (await _load_nodes(connection, self.scope_id)).values() if node.kind == "memory"]
                    for node in nodes:
                        if not node.available and not node.native_suppressed:
                            await connection.execute(
                                _node_update(self.scope_id, node.node_id).values(native_suppressed=True)
                            )
                withdraw = {node.reference.entry_id for node in nodes if not node.available}  # type: ignore[union-attr]
                restore = {
                    node.reference.entry_id  # type: ignore[union-attr]
                    for node in nodes
                    if node.available and node.native_suppressed
                }
                restore -= withdraw
                if not withdraw and not restore:
                    return
                service = context.artifacts.memory
                memory = await service.head(context.artifacts.memory_artifact_id)
                states = {item.entry_id: item.state for item in memory.content.manifest.entries}
                entries = await service.entries(memory)
                deactivate = [entry for entry in entries if entry.entry_id in withdraw and states[entry.entry_id] == "active"]
                if deactivate:
                    memory = await service.forget(memory, entries=deactivate, reason=_REASON)
                reactivate = [
                    entry for entry in entries if entry.entry_id in restore and states[entry.entry_id] == "inactive"
                ]
                if reactivate:
                    memory = await service.reactivate(memory, entries=reactivate, reason=_REASON)
                if restore:
                    async with self._database().transaction() as connection:
                        for node in nodes:
                            if node.available and node.native_suppressed:
                                await connection.execute(
                                    _node_update(self.scope_id, node.node_id).values(native_suppressed=False)
                                )

    def _database(self) -> AsyncDatabase:
        database = getattr(self._runtime._provider, "database", None)
        if database is None:
            raise SourceLifecycleError("source lifecycle requires a relational Runtime")
        return database


class SourceLifecycleApplication:
    """Select the Source lifecycle service for one scope."""

    def __init__(self, runtime: BuiltinRuntime) -> None:
        self._runtime = runtime

    def for_scope(self, scope_id: str, /) -> ScopedSourceLifecycle:
        return ScopedSourceLifecycle(self._runtime, validate_scope_id(scope_id))


def _require_node_id(node_id: object) -> None:
    if not isinstance(node_id, str) or not node_id.strip():
        raise SourceLifecycleError("lifecycle node_id must be a non-blank string")
    if len(node_id) > SOURCE_LIFECYCLE_NODES_TABLE.c.node_id.type.length:
        raise SourceLifecycleError("lifecycle node_id is too long")


def _validate_parents(node_id: str, parents: object, policy: object) -> tuple[str, ...]:
    if policy not in ("all", "any"):
        raise SourceLifecycleError("lifecycle policy must be 'all' or 'any'")
    if not isinstance(parents, (tuple, list)) or not parents:
        raise SourceLifecycleError("derived lifecycle nodes require at least one parent")
    parents = tuple(parents)
    if not all(isinstance(parent, str) and parent for parent in parents):
        raise SourceLifecycleError("lifecycle parents must be node IDs")
    if len(set(parents)) != len(parents):
        raise SourceLifecycleError("lifecycle parents must not repeat")
    if node_id in parents:
        raise SourceLifecycleError("lifecycle node cannot depend on itself")
    return parents


def _supported(policy: LifecyclePolicy | None, support: list[bool]) -> bool:
    return all(support) if policy == "all" else any(support)


def _node_update(scope_id: str, node_id: str):
    table = SOURCE_LIFECYCLE_NODES_TABLE
    return update(table).where(table.c.scope_id == scope_id, table.c.node_id == node_id)


async def _propagate(connection: AsyncConnection, scope_id: str) -> dict[str, _Node]:
    """Recompute derived availability in registration (topological) order."""

    nodes = await _load_nodes(connection, scope_id)
    current = {node_id: node.available for node_id, node in nodes.items()}
    for node in sorted(nodes.values(), key=lambda item: item.ordinal):
        if node.kind == "source":
            continue
        available = _supported(node.policy, [current[parent] for parent in node.parents])
        current[node.node_id] = available
        if available != node.available:
            await connection.execute(_node_update(scope_id, node.node_id).values(available=available))
    return await _load_nodes(connection, scope_id)


async def _load_nodes(connection: AsyncConnection, scope_id: str) -> dict[str, _Node]:
    table = SOURCE_LIFECYCLE_NODES_TABLE
    rows = (
        (await connection.execute(select(table).where(table.c.scope_id == scope_id).order_by(table.c.ordinal)))
        .mappings()
        .all()
    )
    nodes: dict[str, _Node] = {}
    for row in rows:
        kind = row["kind"]
        reference_type = {"source": SourceRef, "memory": MemoryCitation, "topic": ArtifactRef}[kind]
        nodes[row["node_id"]] = _Node(
            node_id=row["node_id"],
            ordinal=int(row["ordinal"]),
            kind=kind,
            reference=reference_type.model_validate_json(row["reference"]),
            parents=tuple(json.loads(row["parents"])),
            policy=row["policy"],
            revision=None if row["revision"] is None else int(row["revision"]),
            available=bool(row["available"]),
            native_suppressed=bool(row["native_suppressed"]),
            last_event=None if row["last_event"] is None else SourceLifecycleEvent.model_validate_json(row["last_event"]),
        )
    return nodes


__all__ = [
    "ScopedSourceLifecycle",
    "SourceLifecycleApplication",
    "SourceLifecycleError",
    "SourceLifecycleEvent",
]
