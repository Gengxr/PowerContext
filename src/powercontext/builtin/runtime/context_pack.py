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

"""Chunked Context Packs and prefix-reuse deltas for incremental context transport."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass

PACK_SCHEMA = "powercontext.context-pack.v1"
DELTA_SCHEMA = "powercontext.context-pack-delta.v1"
DEFAULT_CHUNK_BYTES = 512
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_PACK_FIELDS = frozenset({"schema", "items", "digest", "byte_count"})
_DELTA_FIELDS = frozenset({"schema", "base_digest", "target_digest", "prefix_items", "appended"})


class ContextPackError(ValueError):
    """Raised when a Context Pack, delta or chunking request violates the protocol."""


@dataclass(frozen=True, slots=True)
class ContextPack:
    """A complete context body split into ordered, individually valid UTF-8 chunks."""

    items: tuple[bytes, ...]

    def __post_init__(self) -> None:
        _validate_items(self.items, "items")

    @classmethod
    def build(cls, items: tuple[bytes, ...]) -> ContextPack:
        """Build a complete pack from in-memory chunks."""

        return cls(tuple(items) if isinstance(items, list) else items)

    @classmethod
    def from_content(cls, content: str, *, chunk_bytes: int = DEFAULT_CHUNK_BYTES) -> ContextPack:
        """Chunk ``content`` deterministically at line ends and UTF-8 character boundaries."""

        if not isinstance(content, str):
            raise ContextPackError("content must be a string")
        return cls(_chunk(content, chunk_bytes))

    @property
    def digest(self) -> str:
        return _pack_digest(self.items)

    @property
    def byte_count(self) -> int:
        return len(self.to_bytes())

    def to_bytes(self) -> bytes:
        payload: dict[str, object] = {
            "schema": PACK_SCHEMA,
            "items": _encode_items(self.items),
            "digest": self.digest,
        }
        return _with_self_count(payload)

    @classmethod
    def from_bytes(cls, data: bytes) -> ContextPack:
        """Decode a complete pack and verify its digest and byte count."""

        payload = _load_object(data, _PACK_FIELDS, PACK_SCHEMA)
        pack = cls(_decode_items(payload["items"], "items"))
        if payload["digest"] != pack.digest:
            raise ContextPackError("pack digest does not match its items")
        byte_count = payload["byte_count"]
        if not _is_int(byte_count) or byte_count != pack.byte_count:
            raise ContextPackError("pack byte_count does not match its encoding")
        return pack


@dataclass(frozen=True, slots=True)
class ContextPackDelta:
    """Keep ``prefix_items`` chunks of the base pack and append the target's suffix."""

    base_digest: str
    target_digest: str
    prefix_items: int
    appended: tuple[bytes, ...]

    def __post_init__(self) -> None:
        for field in ("base_digest", "target_digest"):
            value = getattr(self, field)
            if not isinstance(value, str) or not _DIGEST.fullmatch(value):
                raise ContextPackError(f"{field} must be a sha256 digest")
        if not _is_int(self.prefix_items) or self.prefix_items < 0:
            raise ContextPackError("prefix_items must be a non-negative integer")
        _validate_items(self.appended, "appended")

    @classmethod
    def between(cls, base: ContextPack, target: ContextPack) -> ContextPackDelta:
        """Reuse the longest common chunk prefix of ``base`` and send the rest of ``target``."""

        prefix = 0
        for left, right in zip(base.items, target.items, strict=False):
            if left != right:
                break
            prefix += 1
        return cls(base.digest, target.digest, prefix, target.items[prefix:])

    @property
    def byte_count(self) -> int:
        return len(self.to_bytes())

    def to_bytes(self) -> bytes:
        return _canonical_json({
            "schema": DELTA_SCHEMA,
            "base_digest": self.base_digest,
            "target_digest": self.target_digest,
            "prefix_items": self.prefix_items,
            "appended": _encode_items(self.appended),
        })

    @classmethod
    def from_bytes(cls, data: bytes) -> ContextPackDelta:
        """Decode and validate one serialized delta."""

        payload = _load_object(data, _DELTA_FIELDS, DELTA_SCHEMA)
        return cls(
            payload["base_digest"],
            payload["target_digest"],
            payload["prefix_items"],
            _decode_items(payload["appended"], "appended"),
        )


def apply_context_pack_delta(base: ContextPack, delta: ContextPackDelta) -> ContextPack:
    """Rebuild the target pack from a base pack and a delta, verifying both digests."""

    if not isinstance(base, ContextPack) or not isinstance(delta, ContextPackDelta):
        raise ContextPackError("apply requires a ContextPack and a ContextPackDelta")
    if base.digest != delta.base_digest:
        raise ContextPackError("delta base digest does not match the base pack")
    if delta.prefix_items > len(base.items):
        raise ContextPackError("delta prefix exceeds the base pack")
    target = ContextPack(base.items[: delta.prefix_items] + delta.appended)
    if target.digest != delta.target_digest:
        raise ContextPackError("rebuilt pack does not match the delta target digest")
    return target


def aligned_pack(base: ContextPack, content: str, *, chunk_bytes: int = DEFAULT_CHUNK_BYTES) -> ContextPack:
    """Chunk ``content`` reusing the leading chunks of ``base`` that it still starts with."""

    encoded = content.encode("utf-8")
    reused: list[bytes] = []
    offset = 0
    for item in base.items:
        if not item or not encoded.startswith(item, offset):
            break
        reused.append(item)
        offset += len(item)
    remainder = encoded[offset:].decode("utf-8")
    return ContextPack((*reused, *_chunk(remainder, chunk_bytes)))


def _chunk(content: str, chunk_bytes: int) -> tuple[bytes, ...]:
    if not _is_int(chunk_bytes) or chunk_bytes < 1:
        raise ContextPackError("chunk_bytes must be a positive integer")
    chunks: list[bytes] = []
    for line in content.splitlines(keepends=True):
        encoded = line.encode("utf-8")
        while len(encoded) > chunk_bytes:
            cut = chunk_bytes
            while cut > 0 and (encoded[cut] & 0xC0) == 0x80:
                cut -= 1
            if cut == 0:
                raise ContextPackError("chunk_bytes is smaller than one UTF-8 character")
            chunks.append(encoded[:cut])
            encoded = encoded[cut:]
        if encoded:
            chunks.append(encoded)
    return tuple(chunks)


def _validate_items(items: object, field: str) -> None:
    if not isinstance(items, tuple):
        raise ContextPackError(f"{field} must be a tuple of bytes")
    for item in items:
        if not isinstance(item, bytes):
            raise ContextPackError(f"{field} must contain bytes")
        try:
            item.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ContextPackError(f"{field} must contain valid UTF-8 chunks") from error


def _encode_items(items: tuple[bytes, ...]) -> list[str]:
    return [base64.b64encode(item).decode("ascii") for item in items]


def _decode_items(values: object, field: str) -> tuple[bytes, ...]:
    if not isinstance(values, list):
        raise ContextPackError(f"{field} must be a list of Base64 strings")
    items: list[bytes] = []
    for value in values:
        if not isinstance(value, str):
            raise ContextPackError(f"{field} must be a list of Base64 strings")
        try:
            item = base64.b64decode(value.encode("ascii"), validate=True)
        except (UnicodeEncodeError, binascii.Error) as error:
            raise ContextPackError(f"{field} contains invalid Base64") from error
        if base64.b64encode(item).decode("ascii") != value:
            raise ContextPackError(f"{field} contains non-canonical Base64")
        items.append(item)
    return tuple(items)


def _pack_digest(items: tuple[bytes, ...]) -> str:
    unsigned = _canonical_json({"schema": PACK_SCHEMA, "items": _encode_items(items)})
    return f"sha256:{hashlib.sha256(unsigned).hexdigest()}"


def _canonical_json(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _with_self_count(payload: dict[str, object]) -> bytes:
    count = 0
    while True:
        encoded = _canonical_json({**payload, "byte_count": count})
        if len(encoded) == count:
            return encoded
        count = len(encoded)


def _load_object(data: bytes, fields: frozenset[str], schema: str) -> dict[str, object]:
    if not isinstance(data, (bytes, bytearray)):
        raise ContextPackError("serialized payload must be bytes")
    try:
        payload = json.loads(bytes(data).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContextPackError("serialized payload must be UTF-8 JSON") from error
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ContextPackError(f"payload must contain exactly {sorted(fields)}")
    if payload["schema"] != schema:
        raise ContextPackError(f"payload schema must be {schema}")
    return payload


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


__all__ = [
    "ContextPack",
    "ContextPackDelta",
    "ContextPackError",
    "apply_context_pack_delta",
]
