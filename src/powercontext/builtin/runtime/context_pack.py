# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Portable v1 context packs and validated, stateless prefix deltas.

The digest covers chunk boundaries as well as their bytes. A receiver must keep
the complete reconstructed pack (not just its text) for the next delta.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import cast

_PACK_SCHEMA = "powercontext.context-pack.v1"
_DELTA_SCHEMA = "powercontext.context-pack-delta.v1"
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


class ContextPackError(ValueError):
    """Invalid context pack, wire encoding, or delta reconstruction."""


def _json_bytes(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ContextPackError("duplicate-field")
        result[key] = value
    return result


def _decode_payload(data: bytes, schema: str, fields: set[str]) -> dict[str, object]:
    if not isinstance(data, bytes):
        raise ContextPackError("wire-must-be-bytes")
    try:
        payload = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeError, ValueError, RecursionError) as error:
        raise ContextPackError("invalid-json") from error
    if not isinstance(payload, dict) or set(payload) != fields or payload["schema"] != schema:
        raise ContextPackError("invalid-schema-or-fields")
    return cast(dict[str, object], payload)


def _validate_items(items: tuple[bytes, ...]) -> None:
    if not isinstance(items, tuple) or any(not isinstance(item, bytes) for item in items):
        raise ContextPackError("items-must-be-bytes-tuple")


def _encode_items(items: tuple[bytes, ...]) -> list[str]:
    return [base64.b64encode(item).decode("ascii") for item in items]


def _decode_items(value: object) -> tuple[bytes, ...]:
    if not isinstance(value, list):
        raise ContextPackError("items-must-be-array")
    items: list[bytes] = []
    for encoded in value:
        if not isinstance(encoded, str):
            raise ContextPackError("item-must-be-base64-string")
        try:
            item = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as error:
            raise ContextPackError("invalid-base64") from error
        # Reject nonzero padding bits and redundant padding, too.
        if base64.b64encode(item).decode("ascii") != encoded:
            raise ContextPackError("noncanonical-base64")
        items.append(item)
    return tuple(items)


def _validate_digest(value: str) -> None:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ContextPackError("invalid-digest")


@dataclass(frozen=True)
class ContextPack:
    """Immutable complete pack; all metadata is derived from its byte chunks."""

    items: tuple[bytes, ...]
    digest: str = field(init=False)
    byte_count: int = field(init=False)

    def __post_init__(self) -> None:
        _validate_items(self.items)
        payload: dict[str, object] = {"schema": _PACK_SCHEMA, "items": _encode_items(self.items)}
        digest = "sha256:" + hashlib.sha256(_json_bytes(payload)).hexdigest()
        payload["digest"] = digest
        count = 0
        while True:
            payload["byte_count"] = count
            actual = len(_json_bytes(payload))
            if actual == count:
                break
            count = actual
        object.__setattr__(self, "digest", digest)
        object.__setattr__(self, "byte_count", count)

    @classmethod
    def build(cls, items: tuple[bytes, ...]) -> ContextPack:
        """Build a pack without rewriting, merging, or reordering byte chunks."""
        return cls(items)

    @classmethod
    def from_content(cls, content: str, *, chunk_bytes: int = 512) -> ContextPack:
        """Split text deterministically at UTF-8 boundaries within the byte limit."""
        if type(chunk_bytes) is not int or chunk_bytes <= 0:
            raise ContextPackError("invalid-chunk-limit")
        if not isinstance(content, str):
            raise ContextPackError("content-must-be-text")
        try:
            data = content.encode("utf-8")
        except UnicodeError as error:
            raise ContextPackError("invalid-utf8-content") from error
        items: list[bytes] = []
        start = 0
        while start < len(data):
            end = min(start + chunk_bytes, len(data))
            while end < len(data) and end > start and data[end] & 0xC0 == 0x80:
                end -= 1
            if end == start:
                raise ContextPackError("chunk-limit-too-small-for-codepoint")
            items.append(data[start:end])
            start = end
        return cls.build(tuple(items))

    def to_bytes(self) -> bytes:
        """Encode the complete canonical v1 JSON, including its own byte count."""
        return _json_bytes({
            "schema": _PACK_SCHEMA,
            "items": _encode_items(self.items),
            "digest": self.digest,
            "byte_count": self.byte_count,
        })

    @classmethod
    def from_bytes(cls, data: bytes) -> ContextPack:
        """Decode and verify fields, chunks, digest, and canonical wire size."""
        payload = _decode_payload(data, _PACK_SCHEMA, {"schema", "items", "digest", "byte_count"})
        pack = cls.build(_decode_items(payload["items"]))
        if payload["digest"] != pack.digest:
            raise ContextPackError("pack-digest-mismatch")
        if type(payload["byte_count"]) is not int or payload["byte_count"] != pack.byte_count:
            raise ContextPackError("pack-byte-count-mismatch")
        return pack


@dataclass(frozen=True)
class ContextPackDelta:
    """Retain a base prefix and replace the entire remaining suffix."""

    base_digest: str
    target_digest: str
    prefix_items: int
    appended: tuple[bytes, ...]

    def __post_init__(self) -> None:
        _validate_digest(self.base_digest)
        _validate_digest(self.target_digest)
        if type(self.prefix_items) is not int or self.prefix_items < 0:
            raise ContextPackError("invalid-prefix")
        _validate_items(self.appended)

    @classmethod
    def between(cls, base: ContextPack, target: ContextPack) -> ContextPackDelta:
        """Reuse the longest equal chunk prefix, including an unchanged whole pack."""
        if not isinstance(base, ContextPack) or not isinstance(target, ContextPack):
            raise ContextPackError("invalid-pack")
        prefix = 0
        for left, right in zip(base.items, target.items, strict=False):
            if left != right:
                break
            prefix += 1
        return cls(base.digest, target.digest, prefix, target.items[prefix:])

    @property
    def byte_count(self) -> int:
        """Actual delta wire size; this is not an additional JSON field."""
        return len(self.to_bytes())

    def to_bytes(self) -> bytes:
        return _json_bytes({
            "schema": _DELTA_SCHEMA,
            "base_digest": self.base_digest,
            "target_digest": self.target_digest,
            "prefix_items": self.prefix_items,
            "appended": _encode_items(self.appended),
        })

    @classmethod
    def from_bytes(cls, data: bytes) -> ContextPackDelta:
        payload = _decode_payload(
            data, _DELTA_SCHEMA, {"schema", "base_digest", "target_digest", "prefix_items", "appended"}
        )
        # The constructor validates the runtime types as well as their values.
        return cls(
            cast(str, payload["base_digest"]),
            cast(str, payload["target_digest"]),
            cast(int, payload["prefix_items"]),
            _decode_items(payload["appended"]),
        )


def apply_context_pack_delta(base: ContextPack, delta: ContextPackDelta) -> ContextPack:
    """Rebuild independently of the sender; fail closed on a stale or wrong base."""
    if not isinstance(base, ContextPack) or not isinstance(delta, ContextPackDelta):
        raise ContextPackError("invalid-pack-or-delta")
    if base.digest != delta.base_digest:
        raise ContextPackError("base-digest-mismatch")
    if delta.prefix_items > len(base.items):
        raise ContextPackError("prefix-out-of-bounds")
    target = ContextPack.build(base.items[: delta.prefix_items] + delta.appended)
    if target.digest != delta.target_digest:
        raise ContextPackError("target-digest-mismatch")
    return target
