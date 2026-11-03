"""YX1 记忆文本编解码。

PowerContext 的 memory text 是给人和模型读的纯文本，不是字段袋。这里用「头部 + 正文」的
行式编码把研续的结构化字段无损塞进去，同时保证文本本身可读、可被 FTS 检索。
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Mapping

FORMAT_MARKER = "YX1"
BODY_SEPARATOR = "---"

TITLE = "title"
DATE = "date"
STATUS = "status"
TAGS = "tags"
URL = "url"
REFS = "refs"

HEADER_KEYS: tuple[str, ...] = (TITLE, DATE, STATUS, TAGS, URL, REFS)
_LIST_KEYS = frozenset({TAGS, REFS})
_DEFAULTS: Mapping[str, str] = {TITLE: "", DATE: "", STATUS: "", URL: ""}

_LIST_SEPARATOR = ","


class CodecError(ValueError):
    """头部字段非法，无法安全编码/解码。"""


def _split_list(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(_LIST_SEPARATOR) if item.strip()]


def _join_list(values: Iterable[str]) -> str:
    seen: list[str] = []
    for value in values:
        item = str(value).strip()
        if item and item not in seen:
            seen.append(item)
    return _LIST_SEPARATOR.join(seen)


def _clean_scalar(key: str, value: str) -> str:
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    if "\n" in text:
        raise CodecError(f"头部字段 {key} 不能包含换行；请把多行内容放进正文。")
    return text.strip()


def encode(
    *,
    title: str = "",
    date: str = "",
    status: str = "",
    tags: Iterable[str] = (),
    url: str = "",
    refs: Iterable[str] = (),
    body: str = "",
) -> str:
    """把结构化字段编码成 PowerContext memory text。只输出非空头部键，保持文本干净。"""
    scalars = {
        TITLE: _clean_scalar(TITLE, title),
        DATE: _clean_scalar(DATE, date),
        STATUS: _clean_scalar(STATUS, status),
        URL: _clean_scalar(URL, url),
    }
    lists = {TAGS: _join_list(tags), REFS: _join_list(refs)}

    lines = [FORMAT_MARKER]
    for key in HEADER_KEYS:
        value = lists[key] if key in _LIST_KEYS else scalars[key]
        if value:
            lines.append(f"{key}={value}")
    lines.append(BODY_SEPARATOR)

    text = "\n".join(lines)
    body_text = str(body).replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    return f"{text}\n{body_text}" if body_text else text


def decode(text: str) -> dict[str, object]:
    """把 memory text 还原成结构化字段。非 YX1 文本按「纯正文」宽容处理。"""
    normalized = unicodedata.normalize("NFC", str(text or ""))
    lines = normalized.split("\n")

    if not lines or lines[0].strip() != FORMAT_MARKER:
        return {**dict(_DEFAULTS), TAGS: [], REFS: [], "body": normalized.strip("\n")}

    header: dict[str, str] = {}
    index = 1
    while index < len(lines):
        line = lines[index]
        if line.strip() == BODY_SEPARATOR:
            index += 1
            break
        key, separator, value = line.partition("=")
        if separator and key.strip() in HEADER_KEYS:
            header[key.strip()] = value
        index += 1

    result: dict[str, object] = {**dict(_DEFAULTS)}
    for key, value in header.items():
        result[key] = _split_list(value) if key in _LIST_KEYS else value.strip()
    for key in _LIST_KEYS:
        result.setdefault(key, [])
    result["body"] = "\n".join(lines[index:]).strip("\n")
    return result


def byte_length(text: str) -> int:
    """PowerContext 计数方式：NFC 归一化后的 UTF-8 字节数。"""
    return len(unicodedata.normalize("NFC", text).encode("utf-8"))
