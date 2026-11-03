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

"""Captured raw events from the selected branch of a Pi v3 session file."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, JsonValue

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources.connectors import ConnectorRunCompletion, ConnectorRunSession, ConnectorRunStatus
from powercontext.sources.definitions import AdapterSourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

PI_EVENT_SOURCE_NAME = "pi-event"
PI_SESSION_CONNECTOR_NAME = "pi-session-history"
_CHECKPOINT_FORMAT = "pi-session-history/1"


class PiSessionInput(BaseModel):
    """A complete Pi JSONL session and the optional leaf selecting one branch."""

    model_config = ConfigDict(frozen=True)

    content: bytes
    leaf_id: str | None = None


class PiEventInput(BaseModel):
    """One visible event on the selected branch with its complete raw record."""

    model_config = ConfigDict(frozen=True)

    session_id: str
    event_id: str
    parent_id: str | None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]


class PiEventSource(Source):
    """An immutable captured Pi event identified by session and event ID.

    The event text is derived from ``record`` on demand so that large tool
    results are stored once in the observation payload.
    """

    session_id: str
    event_id: str
    parent_id: str | None
    event_type: str
    role: str
    record: dict[str, JsonValue]

    @property
    def content(self) -> str:
        visible = _visible_event(self.record)
        if visible is None:
            raise ValueError(f"Pi event {self.event_id!r} has no visible text")  # noqa: TRY003
        role, body = visible
        return f"{role}: {body}"


def pi_event_source_id(session_id: str, event_id: str) -> str:
    """Return a stable, delimiter-safe identity bounded by the Source limit."""

    identity = f"pi:{quote(session_id, safe='')}:{quote(event_id, safe='')}"
    if len(identity) <= MAX_SOURCE_ID_LENGTH:
        return identity
    digest = hashlib.sha256(json.dumps([session_id, event_id], ensure_ascii=False).encode("utf-8")).hexdigest()
    return f"pi-sha256:{digest}"


def parse_pi_session(value: PiSessionInput) -> tuple[PiEventInput, ...]:  # noqa: C901
    """Return the visible events from root to the selected leaf, or fail atomically."""

    records = _decode_records(value.content)
    header = records[0]
    if header.get("type") != "session" or not _is_int(header.get("version"), 3):
        raise ValueError("Pi session must start with a version 3 session header")  # noqa: TRY003
    session_id = header.get("id")
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("Pi session header requires a non-empty id")  # noqa: TRY003

    nodes: dict[str, dict[str, Any]] = {}
    for record in records[1:]:
        node_id = record.get("id")
        if not isinstance(node_id, str) or not node_id:
            raise ValueError("Pi session entries require a non-empty id")  # noqa: TRY003
        if node_id in nodes:
            raise ValueError(f"duplicate Pi session entry {node_id!r}")  # noqa: TRY003
        if not isinstance(record.get("type"), str):
            raise ValueError(f"Pi session entry {node_id!r} requires a type")  # noqa: TRY003, TRY004
        if "parentId" not in record:
            raise ValueError(f"Pi session entry {node_id!r} requires parentId")  # noqa: TRY003
        parent_id = record["parentId"]
        if parent_id is not None and (not isinstance(parent_id, str) or parent_id not in nodes):
            raise ValueError(f"Pi session entry {node_id!r} has an unknown parent")  # noqa: TRY003
        nodes[node_id] = record

    if value.leaf_id is None:
        if not nodes:
            return ()
        leaf_id = next(reversed(nodes))
    elif value.leaf_id in nodes:
        leaf_id = value.leaf_id
    else:
        raise ValueError(f"Pi session leaf {value.leaf_id!r} does not exist")  # noqa: TRY003

    path: list[dict[str, Any]] = []
    current: str | None = leaf_id
    while current is not None:
        record = nodes[current]
        path.append(record)
        current = record["parentId"]
    path.reverse()

    events: list[PiEventInput] = []
    for record in path:
        visible = _visible_event(record)
        if visible is None:
            continue
        role, body = visible
        events.append(
            PiEventInput(
                session_id=session_id,
                event_id=record["id"],
                parent_id=record["parentId"],
                event_type=record["type"],
                role=role,
                content=f"{role}: {body}",
                record=record,
            )
        )
    return tuple(events)


def _decode_records(content: bytes) -> list[dict[str, Any]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("Pi session must be valid UTF-8") from error  # noqa: TRY003
    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid Pi session JSON: {error}") from error  # noqa: TRY003
        if not isinstance(record, dict):
            raise ValueError("Pi session records must be JSON objects")  # noqa: TRY003, TRY004
        records.append(record)
    if not records:
        raise ValueError("Pi session is empty")  # noqa: TRY003
    return records


def _is_int(value: object, expected: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value == expected


def _visible_event(record: dict[str, Any]) -> tuple[str, str] | None:
    event_type = record["type"]
    if event_type in {"compaction", "branch_summary"}:
        summary = record.get("summary")
        if not isinstance(summary, str):
            raise ValueError(f"Pi {event_type} entry requires a summary")  # noqa: TRY003
        return (event_type, summary) if summary.strip() else None
    if event_type == "custom_message":
        body = _text_body(record.get("content"))
        return ("custom", body) if body.strip() else None
    if event_type != "message":
        return None

    message = record.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("role"), str) or not message["role"]:
        raise ValueError("Pi message entry requires a message with a role")  # noqa: TRY003
    role = message["role"]
    if role == "toolResult":
        text = _text_body(message.get("content"))
        body = f"[tool_result {message.get('toolName', '')} {message.get('toolCallId', '')}] {text}"
    elif role == "bashExecution":
        body = f"$ {_string(message.get('command'))}\n{_string(message.get('output'))}"
    else:
        body = _text_body(message.get("content"), tool_calls=True)
        if not body.strip() and isinstance(message.get("summary"), str):
            body = message["summary"]
        if not body.strip():
            return None
    return role, body


def _text_body(content: object, *, tool_calls: bool = False) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        raise ValueError("Pi message content must be a string or a list of blocks")  # noqa: TRY003, TRY004
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            raise ValueError("Pi content blocks must be JSON objects")  # noqa: TRY003, TRY004
        block_type = block.get("type")
        if block_type == "text":
            parts.append(_string(block.get("text")))
        elif block_type == "toolCall" and tool_calls:
            arguments = json.dumps(
                block.get("arguments", {}), ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            parts.append(f"[tool_call {block.get('name', '')} {block.get('id', '')}] {arguments}")
    return "\n".join(parts)


def _string(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("Pi visible text fields must be strings")  # noqa: TRY003, TRY004
    return value


class PiEventSourceAdapter:
    """Resolve and read captured Pi events without re-reading the session file."""

    input_class = PiEventInput
    name = PI_EVENT_SOURCE_NAME
    source_class = PiEventSource

    async def resolve(self, value: PiEventInput, /) -> PiEventSource:
        return PiEventSource(
            name=pi_event_source_id(value.session_id, value.event_id),
            materialization=SourceMaterialization.CAPTURED,
            session_id=value.session_id,
            event_id=value.event_id,
            parent_id=value.parent_id,
            event_type=value.event_type,
            role=value.role,
            record=value.record,
        )

    async def read(self, source: PiEventSource, /) -> PiEventInput:
        return PiEventInput(
            session_id=source.session_id,
            event_id=source.event_id,
            parent_id=source.parent_id,
            event_type=source.event_type,
            role=source.role,
            content=source.content,
            record=source.record,
        )


class PiEventTextEvidenceProjection:
    """Expose the complete event text with its session graph identity."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PiEventSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PiEventSource, /) -> TextEvidence:
        return TextEvidence(
            source_type=PI_EVENT_SOURCE_NAME,
            source_id=source.name,
            content=source.content,
            metadata={
                "session_id": source.session_id,
                "event_id": source.event_id,
                "parent_id": source.parent_id,
                "event_type": source.event_type,
                "role": source.role,
            },
        )


PI_EVENT_SOURCE_DEFINITION = AdapterSourceDefinition(
    PiEventSourceAdapter(),
    projections=(PiEventTextEvidenceProjection(),),
)


class PiSessionConnector:
    """Import unseen visible events from one selected branch of a Pi session file."""

    name = PI_SESSION_CONNECTOR_NAME
    version = "1"
    source_definitions = frozenset({PI_EVENT_SOURCE_NAME})

    def __init__(self, path: str | Path, leaf_id: str | None = None) -> None:
        self.path = Path(path)
        self.leaf_id = leaf_id

    async def run(self, session: ConnectorRunSession, /) -> ConnectorRunCompletion:
        events = parse_pi_session(PiSessionInput(content=self.path.read_bytes(), leaf_id=self.leaf_id))
        imported = _checkpoint_events(session.checkpoint)

        pending: list[tuple[str, str, PiEventInput]] = []
        for event in events:
            source_id = pi_event_source_id(event.session_id, event.event_id)
            digest = _record_digest(event)
            known = imported.get(source_id)
            if known is None:
                pending.append((source_id, digest, event))
            elif known != digest:
                raise ValueError(f"Pi event {event.event_id!r} changed after it was imported")  # noqa: TRY003

        updated = dict(imported)
        for source_id, digest, event in pending:
            await session.submit(source_id, PI_EVENT_SOURCE_NAME, event)
            updated[source_id] = digest
        return ConnectorRunCompletion(
            status=ConnectorRunStatus.COMPLETE,
            checkpoint={"format": _CHECKPOINT_FORMAT, "events": dict(sorted(updated.items()))},
        )


def _checkpoint_events(checkpoint: JsonValue | None) -> dict[str, str]:
    if checkpoint is None:
        return {}
    if (
        not isinstance(checkpoint, dict)
        or checkpoint.get("format") != _CHECKPOINT_FORMAT
        or not isinstance(checkpoint.get("events"), dict)
        or not all(isinstance(value, str) for value in checkpoint["events"].values())
    ):
        raise ValueError("unsupported Pi session checkpoint")  # noqa: TRY003
    return dict(checkpoint["events"])


def _record_digest(event: PiEventInput) -> str:
    canonical = json.dumps(
        {"session_id": event.session_id, "record": event.record},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "PI_EVENT_SOURCE_DEFINITION",
    "PiEventInput",
    "PiEventSource",
    "PiSessionConnector",
    "PiSessionInput",
    "parse_pi_session",
    "pi_event_source_id",
]
