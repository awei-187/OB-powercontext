"""真实 PowerContext 持久化 smoke test：write → 进程退出 → 重开 → read。

用法（两个独立 OS 进程，同一个 SQLite 文件）：
    python scripts/smoke_persistence.py write
    python scripts/smoke_persistence.py read

不做任何 mock，不用内存数据库；read 阶段若拿不回 write 阶段的数据即以非零码退出。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.pc_host import PowerContextHost  # noqa: E402

SMOKE_DIR = Path(os.environ.get("YANXU_SMOKE_DIR") or config.resolve_paths().data / "smoke")
STATE_FILE = SMOKE_DIR / "smoke-state.json"
SCOPE_IDEMPOTENCY_KEY = "yanxu-smoke-persistence"
KIND = "decision"
TEXT = "YX1\ntitle=金额一律用 Decimal 存储\ndate=2026-11-02\nstatus=confirmed\n---\n禁止 float；跨会话必须能读回本条。"
REASON = "smoke test: 验证跨进程持久化"
QUERY = "Decimal"


def _host() -> PowerContextHost:
    SMOKE_DIR.mkdir(parents=True, exist_ok=True)
    return PowerContextHost(
        workspace=SMOKE_DIR / "workspace",
        database_path=SMOKE_DIR / "smoke.db",
        scheduler_path=SMOKE_DIR / "scheduler.db",
        start_timeout=config.POWERCONTEXT_START_TIMEOUT,
    )


async def phase_write() -> int:
    from powercontext.client import PowerContextClient
    from powercontext.http import CreateScopeRequest, RememberMemoryRequest, SearchMemoryRequest

    host = _host()
    base_url = await host.start()
    print(f"[write] PowerContext Server 已启动: {base_url}")
    print(f"[write] SQLite 文件: {SMOKE_DIR / 'smoke.db'}")
    try:
        async with PowerContextClient(base_url, timeout=config.POWERCONTEXT_CLIENT_TIMEOUT) as client:
            capabilities = await client.get_capabilities()
            print(f"[write] capabilities.memory_extraction = {capabilities.memory_extraction}")
            print(f"[write] capabilities.search_modes      = {list(capabilities.search_modes)}")

            scope = await client.create_scope(
                CreateScopeRequest(
                    title="研续持久化验证",
                    summary="smoke test 专用 Scope",
                    idempotency_key=SCOPE_IDEMPOTENCY_KEY,
                )
            )
            print(f"[write] scope_id = {scope.scope_id} (version={scope.version})")

            saved = await client.remember_memory(
                RememberMemoryRequest(scope_id=scope.scope_id, kind=KIND, text=TEXT, reason=REASON)
            )
            assert saved.entry is not None, "remember_memory 未返回 entry"
            citation = saved.entry.citation
            print(f"[write] 已写入记忆 entry_id={citation.entry_id}")
            print(f"[write]            entry_version_id={citation.entry_version_id}")
            print(f"[write]            memory_ref={citation.memory_ref.model_dump(mode='json')}")
            print(f"[write]            version={saved.entry.version} state={saved.entry.state}")

            found = await client.search_memory(
                SearchMemoryRequest(scope_id=scope.scope_id, query=QUERY, mode="fts", limit=5)
            )
            print(f"[write] 写后立即 FTS 检索 '{QUERY}': {len(found.hits)} 命中, mode={found.mode}")

            STATE_FILE.write_text(
                json.dumps(
                    {
                        "scope_id": scope.scope_id,
                        "citation": citation.model_dump(mode="json"),
                        "text": TEXT,
                        "kind": KIND,
                        "reason": REASON,
                        "query": QUERY,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            print(f"[write] 期望值已落盘: {STATE_FILE}")
    finally:
        await host.stop()
    print("[write] Server 已停止，进程即将退出。")
    return 0


async def phase_read() -> int:
    from powercontext.client import PowerContextClient
    from powercontext.http import (
        GetMemoryEntryRequest,
        ListMemoryChangesRequest,
        ListMemoryEntriesRequest,
        MemoryCitation,
        SearchMemoryRequest,
    )

    if not STATE_FILE.is_file():
        print(f"[read] 失败：找不到 {STATE_FILE}，请先运行 write 阶段。")
        return 2

    expected = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    host = _host()
    base_url = await host.start()
    print(f"[read] 新进程重开 PowerContext Server: {base_url}")
    print(f"[read] 复用同一 SQLite: {SMOKE_DIR / 'smoke.db'} (exists={ (SMOKE_DIR / 'smoke.db').exists() })")

    failures: list[str] = []
    try:
        async with PowerContextClient(base_url, timeout=config.POWERCONTEXT_CLIENT_TIMEOUT) as client:
            scope_id = expected["scope_id"]

            # Scope 幂等：同一 idempotency_key 必须解析回同一个 scope_id
            from powercontext.http import CreateScopeRequest

            again = await client.create_scope(
                CreateScopeRequest(
                    title="研续持久化验证",
                    summary="smoke test 专用 Scope",
                    idempotency_key=SCOPE_IDEMPOTENCY_KEY,
                )
            )
            same_scope = again.scope_id == scope_id
            print(f"[read] Scope 幂等复用: {again.scope_id} == {scope_id} -> {same_scope}")
            if not same_scope:
                failures.append("scope_id 未跨进程复用")

            listed = await client.list_memory_entries(ListMemoryEntriesRequest(scope_id=scope_id))
            print(f"[read] list_memory_entries 返回 {len(listed.entries)} 条活跃记忆")
            if len(listed.entries) != 1:
                failures.append(f"期望 1 条记忆，实际 {len(listed.entries)} 条")

            citation = MemoryCitation.model_validate(expected["citation"])
            entry = await client.get_memory_entry(
                GetMemoryEntryRequest(scope_id=scope_id, citation=citation)
            )
            text_ok = entry.text == expected["text"]
            kind_ok = entry.kind == expected["kind"]
            version_ok = entry.citation.entry_version_id == citation.entry_version_id
            print(f"[read] get_memory_entry(旧 citation) -> kind={entry.kind} version={entry.version} state={entry.state}")
            print(f"[read]   文本一致   : {text_ok}")
            print(f"[read]   类型一致   : {kind_ok}")
            print(f"[read]   版本一致   : {version_ok}")
            if not text_ok:
                failures.append("记忆文本跨进程不一致")
                print(f"[read]   期望: {expected['text']!r}")
                print(f"[read]   实际: {entry.text!r}")
            if not kind_ok:
                failures.append("记忆 kind 跨进程不一致")
            if not version_ok:
                failures.append("entry_version_id 跨进程不一致")

            found = await client.search_memory(
                SearchMemoryRequest(scope_id=scope_id, query=expected["query"], mode="fts", limit=5)
            )
            hit_ok = len(found.hits) == 1
            print(f"[read] 重开后 FTS 检索 '{expected['query']}': {len(found.hits)} 命中, mode={found.mode} -> {hit_ok}")
            if not hit_ok:
                failures.append("FTS 检索结果跨进程不一致")

            changes = await client.list_memory_changes(
                ListMemoryChangesRequest(scope_id=scope_id, since_revision=0)
            )
            ops = [change.op for group in changes.revisions for change in group.changes]
            print(f"[read] list_memory_changes 变更序列: {ops}")
            if "add" not in ops:
                failures.append("变更历史中缺少 add 记录")

            print("[read] 读回的正文:")
            for line in entry.text.split("\n"):
                print(f"[read]   | {line}")
    finally:
        await host.stop()

    if failures:
        print("[read] 结论: 失败")
        for item in failures:
            print(f"[read]   - {item}")
        return 1
    print("[read] 结论: 通过 —— 记忆跨进程真实持久化，读回内容与写入完全一致。")
    return 0


def main() -> int:
    phase = sys.argv[1] if len(sys.argv) > 1 else ""
    if phase == "write":
        return asyncio.run(phase_write())
    if phase == "read":
        return asyncio.run(phase_read())
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
