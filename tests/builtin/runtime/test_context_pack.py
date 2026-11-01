"""Independent wire validation and replay tests for the public v1 protocol."""

from __future__ import annotations

import base64
import hashlib
import json
import random
import subprocess
import sys
from collections.abc import Mapping
from typing import cast

import pytest

from powercontext.builtin.runtime.context_pack import (
    ContextPack,
    ContextPackDelta,
    ContextPackError,
    apply_context_pack_delta,
)


def _wire(payload: Mapping[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def test_independent_pack_oracle_and_size_digit_boundaries():
    for length in (0, 1, 610, 620, 630, 7300, 7400, 7500):
        items = (b"x" * length, "海洋🙂\r\n\x00".encode())
        unsigned = {"schema": "powercontext.context-pack.v1", "items": [_b64(item) for item in items]}
        digest = "sha256:" + hashlib.sha256(_wire(unsigned)).hexdigest()
        payload = {**unsigned, "digest": digest, "byte_count": 0}
        while payload["byte_count"] != len(_wire(payload)):
            payload["byte_count"] = len(_wire(payload))
        pack = ContextPack.build(items)
        assert pack.to_bytes() == _wire(payload)
        assert pack.byte_count == len(_wire(payload))
        assert ContextPack.from_bytes(pack.to_bytes()) == pack


def _b64(item: bytes) -> str:
    return base64.b64encode(item).decode("ascii")


@pytest.mark.parametrize("limit", [1, 2, 3, 4, 5, 7, 511, 512, 513])
@pytest.mark.parametrize("content", ["", "a\r\nb\x00", "海洋", "🙂aé\u0301中" * 150])
def test_bounded_deterministic_utf8_chunks(content, limit):
    if any(len(character.encode()) > limit for character in content):
        with pytest.raises(ContextPackError):
            ContextPack.from_content(content, chunk_bytes=limit)
        return
    pack = ContextPack.from_content(content, chunk_bytes=limit)
    assert pack == ContextPack.from_content(content, chunk_bytes=limit)
    assert b"".join(pack.items) == content.encode()
    assert all(0 < len(item) <= limit and item.decode("utf-8") for item in pack.items)


@pytest.mark.parametrize("limit", [0, -1, True, 1.5, "512", None])
def test_invalid_chunk_limits(limit):
    with pytest.raises(ContextPackError):
        ContextPack.from_content("", chunk_bytes=limit)


def test_surrogate_content_is_protocol_error():
    with pytest.raises(ContextPackError):
        ContextPack.from_content("\ud800")


@pytest.mark.parametrize("kind", ["pack", "delta"])
def test_decoder_rejects_all_missing_extra_and_duplicate_fields(kind):
    base = ContextPack.build((b"alpha",))
    value = base if kind == "pack" else ContextPackDelta.between(base, ContextPack.build((b"beta",)))
    decoder = type(value).from_bytes
    payload = json.loads(value.to_bytes())
    for field in payload:
        with pytest.raises(ContextPackError):
            decoder(_wire({key: item for key, item in payload.items() if key != field}))
    for extra in ({"unexpected": 1}, {"schema": "v2"}):
        with pytest.raises(ContextPackError):
            decoder(_wire({**payload, **extra}))
    duplicate = b'{"schema":"ignored",' + value.to_bytes()[1:]
    with pytest.raises(ContextPackError):
        decoder(duplicate)
    for invalid in (b"null", b"[]", b"{", b"\xff", b"{} trailing", b"\xff\xfe{\x00}\x00"):
        with pytest.raises(ContextPackError):
            decoder(invalid)


@pytest.mark.parametrize(
    "value", [None, {}, "YQ==", [True], [1], [None], ["!"], ["é"], ["YQ"], ["YR=="], ["YQ==\n"], ["YQ==="]]
)
@pytest.mark.parametrize("kind", ["pack", "delta"])
def test_invalid_chunk_encoding(kind, value):
    base = ContextPack.build((b"a",))
    item = base if kind == "pack" else ContextPackDelta.between(base, base)
    payload = json.loads(item.to_bytes())
    payload["items" if kind == "pack" else "appended"] = value
    with pytest.raises(ContextPackError):
        type(item).from_bytes(_wire(payload))


@pytest.mark.parametrize("count", [True, False, 1.0, "150", None, -1, 0, 100000])
def test_pack_rejects_invalid_byte_count(count):
    payload = json.loads(ContextPack.build(()).to_bytes())
    payload["byte_count"] = count
    with pytest.raises(ContextPackError):
        ContextPack.from_bytes(_wire(payload))


@pytest.mark.parametrize("prefix", [True, False, 0.0, "0", None, -1])
def test_invalid_delta_prefix(prefix):
    pack = ContextPack.build(())
    payload = json.loads(ContextPackDelta.between(pack, pack).to_bytes())
    payload["prefix_items"] = prefix
    with pytest.raises(ContextPackError):
        ContextPackDelta.from_bytes(_wire(payload))


@pytest.mark.parametrize(
    "digest", [None, 0, "", "sha256:" + "g" * 64, "sha256:" + "0" * 63, "sha256:" + "0" * 64 + "\n"]
)
@pytest.mark.parametrize("field", ["base_digest", "target_digest"])
def test_invalid_delta_digest(field, digest):
    pack = ContextPack.build(())
    payload = json.loads(ContextPackDelta.between(pack, pack).to_bytes())
    payload[field] = digest
    with pytest.raises(ContextPackError):
        ContextPackDelta.from_bytes(_wire(payload))


def test_random_edits_all_valid_prefixes_and_idempotence():
    rng = random.Random(481)  # noqa: S311 - reproducible edits, not cryptography
    base = ContextPack.build(())
    for _ in range(120):
        items = list(base.items)
        start = rng.randrange(len(items) + 1)
        stop = rng.randrange(start, len(items) + 1)
        items[start:stop] = [str(rng.randrange(20)).encode() for _ in range(rng.randrange(5))]
        target = ContextPack.build(tuple(items))
        delta = ContextPackDelta.between(base, target)
        for prefix in range(delta.prefix_items + 1):
            alternate = ContextPackDelta(base.digest, target.digest, prefix, target.items[prefix:])
            rebuilt = apply_context_pack_delta(
                ContextPack.from_bytes(base.to_bytes()), ContextPackDelta.from_bytes(alternate.to_bytes())
            )
            assert rebuilt == target
        unchanged = ContextPackDelta.between(target, target)
        assert unchanged.appended == ()
        assert unchanged.prefix_items == len(target.items)
        assert apply_context_pack_delta(target, unchanged) == target
        assert delta.byte_count == len(delta.to_bytes())
        base = target


def test_wrong_base_target_and_bounds_fail_without_mutating_base():
    base = ContextPack.build((b"one", b"two"))
    target = ContextPack.build((b"one", b"three"))
    delta = ContextPackDelta.between(base, target)
    wire = base.to_bytes()
    invalid = (
        ContextPackDelta(target.digest, target.digest, 1, (b"three",)),
        ContextPackDelta(base.digest, base.digest, 1, (b"three",)),
        ContextPackDelta(base.digest, target.digest, 3, ()),
    )
    for value in invalid:
        with pytest.raises(ContextPackError):
            apply_context_pack_delta(base, value)
        assert base.to_bytes() == wire
    assert apply_context_pack_delta(base, delta) == target
    assert ContextPack.from_bytes(target.to_bytes()) == target  # full-pack recovery


def test_chunk_boundaries_are_part_of_identity():
    first = ContextPack.build((b"ab", b"c"))
    second = ContextPack.build((b"a", b"bc"))
    assert first.digest != second.digest
    assert apply_context_pack_delta(first, ContextPackDelta.between(first, second)) == second


def test_replay_in_fresh_process_uses_only_serialized_files(tmp_path):
    base = ContextPack.from_content("海洋\n" * 1000)
    target = ContextPack.from_content("海洋\n" * 999 + "changed🙂\n")
    (tmp_path / "base.json").write_bytes(base.to_bytes())
    (tmp_path / "delta.json").write_bytes(ContextPackDelta.between(base, target).to_bytes())
    script = """
import sys
from pathlib import Path
from powercontext.builtin.runtime.context_pack import ContextPack, ContextPackDelta, apply_context_pack_delta
path = Path(sys.argv[1])
base = ContextPack.from_bytes((path / 'base.json').read_bytes())
delta = ContextPackDelta.from_bytes((path / 'delta.json').read_bytes())
(path / 'rebuilt.json').write_bytes(apply_context_pack_delta(base, delta).to_bytes())
"""
    subprocess.run([sys.executable, "-c", script, str(tmp_path)], check=True)
    assert (tmp_path / "rebuilt.json").read_bytes() == target.to_bytes()


def test_invalid_in_memory_items_are_rejected():
    for items in ([b"a"], ("a",), (bytearray(b"a"),)):
        with pytest.raises(ContextPackError):
            ContextPack.build(cast(tuple[bytes, ...], items))
