"""YX1 记忆文本编解码的单元测试（纯函数，不需要 PowerContext）。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import codec  # noqa: E402


def test_roundtrip_full_fields() -> None:
    text = codec.encode(
        title="复现 baseline 指标",
        date="2026-11-02",
        status="open",
        tags=["实验", "基线"],
        url="https://example.org/paper",
        refs=["mem_abc", "mem_def"],
        body="第一行\n\n第三行（保留空行）",
    )
    fields = codec.decode(text)
    assert fields["title"] == "复现 baseline 指标"
    assert fields["date"] == "2026-11-02"
    assert fields["status"] == "open"
    assert fields["tags"] == ["实验", "基线"]
    assert fields["url"] == "https://example.org/paper"
    assert fields["refs"] == ["mem_abc", "mem_def"]
    assert fields["body"] == "第一行\n\n第三行（保留空行）"


def test_empty_header_keys_are_omitted() -> None:
    text = codec.encode(title="只有标题", body="正文")
    assert text.split("\n")[0] == codec.FORMAT_MARKER
    assert "status=" not in text
    assert "tags=" not in text
    assert codec.decode(text)["title"] == "只有标题"
    assert codec.decode(text)["status"] == ""
    assert codec.decode(text)["tags"] == []


def test_body_may_contain_separator_line() -> None:
    text = codec.encode(title="t", body="上\n---\n下")
    fields = codec.decode(text)
    assert fields["body"] == "上\n---\n下"


def test_header_value_cannot_contain_newline() -> None:
    with pytest.raises(codec.CodecError):
        codec.encode(title="第一行\n第二行")


def test_tags_are_deduplicated_and_trimmed() -> None:
    text = codec.encode(tags=[" a ", "a", "", "b"])
    assert codec.decode(text)["tags"] == ["a", "b"]


def test_crlf_is_normalized() -> None:
    text = codec.encode(title="t", body="a\r\nb")
    assert "\r" not in text
    assert codec.decode(text)["body"] == "a\nb"


def test_decode_tolerates_foreign_text() -> None:
    fields = codec.decode("这不是研续写入的记忆")
    assert fields["body"] == "这不是研续写入的记忆"
    assert fields["title"] == ""


def test_byte_length_counts_nfc_utf8() -> None:
    assert codec.byte_length("中文") == 6
    assert codec.byte_length("abc") == 3
