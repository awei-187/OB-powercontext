#!/usr/bin/env python
"""从空数据目录播种一整套示例数据，跑通完整产品流程。

用法：
    python scripts/seed_demo.py                 # 播种到 data/demo
    python scripts/seed_demo.py --data-dir DIR  # 指定数据目录
    python scripts/seed_demo.py --force         # 目录非空时先清空重建

所有示例内容都是合成数据，标题统一带【示例】前缀；脚本只调用研续自己的 HTTP API，
其后端一律是真实的内嵌 PowerContext Server，不写任何本地兜底存储。
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from app import config  # noqa: E402
from app.main import create_app  # noqa: E402

TAG = "【示例】"
SYNTHETIC = f"{TAG}合成演示数据，全部数字均为虚构、非实测。"

LEDGER_PROJECT = {
    "name": f"{TAG}高吞吐量 KV 存储的写放大治理",
    "summary": f"{SYNTHETIC}针对 LSM-Tree 合并策略导致的写放大做实验与决策跟踪。",
    "goal": f"{SYNTHETIC}演示目标：把 P99 写延迟从 12ms 降到 8ms 以内，且写放大因子不超过 6。",
}

RETRIEVAL_PROJECT = {
    "name": f"{TAG}多模态检索的召回优化",
    "summary": f"{SYNTHETIC}第二个项目，用来验证项目之间互不串味。",
    "goal": f"{SYNTHETIC}演示目标：把跨模态检索的 Recall@10 从 0.42 提到 0.60。",
}

LEDGER_ENTRIES: list[dict] = [
    {
        "kind": "record",
        "title": "基线复现：默认 leveled 合并",
        "body": "YCSB A 负载，1 亿条 1KB value，单副本。P99 写延迟 12.4ms，写放大因子 9.8。"
        "合并线程在 major compaction 期间抢占前台 IO，延迟毛刺集中在合并窗口。",
        "status": "done",
        "tags": ["实验", "基线"],
        "reason": "作为后续所有优化的对照点",
    },
    {
        "kind": "decision",
        "title": "合并策略改为 size-tiered + 每日凌晨 major compaction",
        "body": "前台只做 size-tiered 小合并，大合并移到业务低峰。"
        "预期写放大从 9.8 降到 6 以下，代价是空间放大上升到 1.4 倍。",
        "status": "confirmed",
        "tags": ["决策", "合并策略"],
        "reason": "空间放大可接受，写延迟是硬指标",
    },
    {
        "kind": "open_question",
        "title": "写入抖动是否完全来自 flush 抢占 IO",
        "body": "改成 size-tiered 后仍有 2ms 量级抖动。怀疑 memtable 写满触发的冻结与转储"
        "与前台写入争用同一个 IO 队列，但还没有抓到直接证据。",
        "status": "open",
        "tags": ["待验证"],
        "reason": "评审时提出的疑点，先记账",
    },
    {
        "kind": "next_step",
        "title": "用 blktrace 抓一次抖动现场的 IO 队列深度",
        "body": "目标：确认 flush 与前台写是否在同一队列，以及队列深度峰值。"
        "如果确认，下一步再评估 io_uring 批量提交与独立队列隔离。",
        "status": "open",
        "tags": ["下一步"],
        "reason": "",
    },
    {
        "kind": "todo",
        "title": "补齐 4KB / 16KB value 的对比矩阵",
        "body": "目前只有 1KB value 的数据，评审时被问到过大 value 场景。"
        "需要跑完 4KB 和 16KB 各三组，并记录空间放大。",
        "status": "open",
        "tags": ["待办", "实验"],
        "reason": "",
    },
    {
        "kind": "source",
        "title": "OceanBase LSM-Tree 合并策略设计说明",
        "body": "官方文档中关于 minor / major compaction 触发条件与 size-tiered 策略适用场景的章节，"
        "是本项决策的主要依据。",
        "status": "confirmed",
        "tags": ["资料"],
        "url": "https://www.oceanbase.com/docs",
        "reason": "决策的直接出处",
    },
    {
        "kind": "record",
        "title": "一次录错的工作记录（稍后会被退役）",
        "body": "这条是故意留下的：用来演示 PowerContext 没有物理删除，只能 retire，且历史完整保留。",
        "status": "open",
        "tags": ["待退役"],
        "reason": "演示退役流程",
    },
]

RETIRE_TARGET_TITLE = "一次录错的工作记录（稍后会被退役）"

REVISED_QUESTION = {
    "title": "写入抖动是否完全来自 flush 抢占 IO",
    "body": "已确认：blktrace 抓到抖动现场 flush 与前台写共用同一 IO 队列，队列深度峰值 64。"
    "抖动根因就是转储抢占，不再是未知项。",
    "status": "resolved",
    "reason": "blktrace 证据到位，问题已关闭",
}

HANDOFF_OMISSIONS = [
    "大 value（4KB/16KB）场景的实验矩阵未跑，本周报不包含该结论",
    "尚未评估 io_uring 批量提交对前台延迟的影响",
]


def _line(label: str, value: object) -> None:
    print(f"  {label:<22} {value}")


async def _fresh(client: httpx.AsyncClient, project_id: str, title: str) -> dict:
    """重新读回条目，拿到当下有效的 MemoryCitation。

    PowerContext 的 citation 里 memory_ref.revision 是整个记忆工件的修订号，
    任何一条记忆写入都会让它前进；写完后隔了别的写入再拿旧 citation 去 revise，
    服务端会以 RevisionConflictError 拒绝。所以每次修订/退役前都必须重新读回。
    """
    response = await client.get(f"/api/projects/{project_id}/entries?include_inactive=true")
    response.raise_for_status()
    for entry in response.json():
        if entry["title"] == title:
            return entry
    raise SystemExit(f"找不到标题为「{title}」的记忆条目。")


async def _seed(client: httpx.AsyncClient) -> dict:
    print("\n[1/7] 创建两个项目（各自独立 Scope）")
    projects = {}
    for key, payload in (("ledger", LEDGER_PROJECT), ("retrieval", RETRIEVAL_PROJECT)):
        response = await client.post("/api/projects", json=payload)
        response.raise_for_status()
        project = response.json()
        projects[key] = project
        _line(payload["name"], f"{project['project_id']} / {project['scope_id']}")

    ledger_id = projects["ledger"]["project_id"]
    retrieval_id = projects["retrieval"]["project_id"]

    print("\n[2/7] 向台账项目写入 7 条记忆")
    for entry in LEDGER_ENTRIES:
        response = await client.post(f"/api/projects/{ledger_id}/entries", json=entry)
        response.raise_for_status()
        view = response.json()
        _line(f"{view['kind_label']} · {view['title'][:24]}", f"{view['ref_label']} state={view['state']}")

    print("\n[3/7] 修订一条未解决问题（revise 保留 entry_id，推进版本）")
    question = await _fresh(client, ledger_id, REVISED_QUESTION["title"])
    stale_citation = question["citation"]
    before = question["ref_label"]
    response = await client.patch(
        f"/api/projects/{ledger_id}/entries/{question['citation']['entry_id']}",
        json={
            "citation": question["citation"],
            "reason": REVISED_QUESTION["reason"],
            "patch": {**{k: question[k] for k in ("kind", "title", "date", "tags", "url")},
                      "body": REVISED_QUESTION["body"], "status": REVISED_QUESTION["status"]},
        },
    )
    response.raise_for_status()
    revised = response.json()
    _line("修订前 / 修订后", f"{before} → {revised['ref_label']}")
    _line("entry_id 是否不变", question["citation"]["entry_id"] == revised["citation"]["entry_id"])
    _line("工件修订号", f"r{stale_citation['memory_ref']['revision']} → r{revised['citation']['memory_ref']['revision']}")

    print("\n[4/7] 用过期引用再修订一次，确认服务端真的会拒绝")
    print("       （内嵌 Server 会为此打印一段 RevisionConflictError 回溯，这是预期的）")
    stale = await client.patch(
        f"/api/projects/{ledger_id}/entries/{question['citation']['entry_id']}",
        json={
            "citation": stale_citation,
            "reason": "故意使用过期引用",
            "patch": {**{k: question[k] for k in ("kind", "title", "date", "tags", "url")},
                      "body": "这次应当被拒绝", "status": "open"},
        },
    )
    _line("HTTP 状态", stale.status_code)
    _line("错误码", stale.json()["error"].get("code"))
    _line("服务端错误码", stale.json()["error"].get("server_code"))
    _line("服务端消息", stale.json()["error"].get("message"))
    _line("研续给出的提示", stale.json()["error"].get("hint"))
    if stale.status_code != 409:
        raise SystemExit(f"预期 409 修订冲突，实际 {stale.status_code}：{stale.text}")

    print("\n[5/7] 退役一条误写记忆（无物理删除，历史保留）")
    victim = await _fresh(client, ledger_id, RETIRE_TARGET_TITLE)
    response = await client.post(
        f"/api/projects/{ledger_id}/entries/{victim['citation']['entry_id']}/retire",
        json={"citation": victim["citation"], "reason": "示例：误写入，退役而不是删除"},
    )
    response.raise_for_status()
    _line("退役后 state", response.json()["state"] if response.json() else "(none)")
    history = await client.get(f"/api/projects/{ledger_id}/entries/{victim['citation']['entry_id']}/history")
    history.raise_for_status()
    _line("可读回的历史快照数", len(history.json()["snapshots"]))
    _line("变更操作序列", " → ".join(change["op"] for change in history.json()["changes"]))

    print("\n[6/7] 保存交接（本人撰写，引用真实记忆 → basis=verified）")
    draft = await client.get(f"/api/projects/{ledger_id}/handoff/draft")
    draft.raise_for_status()
    preview = draft.json()
    _line("预填已确认状态", f"{len(preview['state'])} 条（均带真实 MemoryCitation）")
    response = await client.post(
        f"/api/projects/{ledger_id}/handoff",
        json={
            "objective": preview["objective"],
            "disposition": preview["disposition"],
            "state": preview["state"],
            "next_action": preview["next_action"],
            "omissions": HANDOFF_OMISSIONS,
        },
    )
    response.raise_for_status()
    handoff = response.json()
    _line("交接工件", f"handoff/{handoff['selected_revision']['artifact_id']}@r{handoff['selected_revision']['revision']}")
    _line("边界 Source", handoff["boundary_source_id"])

    revision = handoff["selected_revision"]

    missing_revision = await client.post(
        f"/api/projects/{ledger_id}/handoff/acknowledge",
        json={
            "status": "accepted",
            "live_state_checked": True,
            "capability_checked": True,
            "authorization_checked": True,
            "message": "示例：故意不带 revision",
        },
    )
    _line(
        "不带核对版本就接手 →",
        f"HTTP {missing_revision.status_code} {missing_revision.json()['error']['code']}",
    )
    if missing_revision.status_code == 200:
        raise SystemExit("预期缺少 revision 的接手被拒绝，实际却成功了。")

    unverified = await client.post(
        f"/api/projects/{ledger_id}/handoff/acknowledge",
        json={
            "status": "accepted",
            "revision": revision,
            "live_state_checked": False,
            "message": "示例：故意不核对",
        },
    )
    _line(
        "未核对三项就接手 →",
        f"HTTP {unverified.status_code} {unverified.json()['error']['code']}",
    )
    if unverified.status_code == 200:
        raise SystemExit("预期未核对的 accepted 接手被拒绝，实际却成功了。")

    acknowledged = await client.post(
        f"/api/projects/{ledger_id}/handoff/acknowledge",
        json={
            "status": "accepted",
            "revision": revision,
            "live_state_checked": True,
            "capability_checked": True,
            "authorization_checked": True,
            "message": "示例：已逐条核对状态，本周继续取证",
        },
    )
    acknowledged.raise_for_status()
    receipt = acknowledged.json()
    if receipt["selected_revision"]["revision"] != revision["revision"]:
        raise SystemExit("回执里的 Revision 与本人核对过的 Revision 不一致。")
    _line(
        "核对后接手 →",
        f"Revision {receipt['selected_revision']['revision']} · receipt Source {receipt['receipt_source_id']}",
    )

    print("\n[7/7] 校验隔离并生成周报")
    probe = await client.post(
        f"/api/projects/{retrieval_id}/search", json={"query": "合并", "limit": 20}
    )
    probe.raise_for_status()
    leaked = probe.json()
    _line("另一项目检索「合并」", f"命中 {len(leaked)} 条（应为 0）")
    if leaked:
        raise SystemExit("项目隔离失败：另一个 Scope 检索到了台账项目的记忆。")

    restore = await client.get(f"/api/projects/{ledger_id}/restore")
    restore.raise_for_status()
    brief = restore.json()
    _line("恢复简报 · 活跃记忆", brief["entry_total"])
    _line("恢复简报 · 上次交接", f"Revision {brief['handoff']['selected_revision']['revision']}")
    checks = brief["handoff"]["evidence_checks"]
    _line("证据回溯检查", f"{sum(1 for c in checks if c['status'] == 'available')}/{len(checks)} 条仍可回溯")

    report = await client.post(
        f"/api/projects/{ledger_id}/report",
        json={"report_type": "weekly", "include_done_todos": True},
    )
    report.raise_for_status()
    return {"brief": brief, "markdown": report.json()["markdown"], "title": report.json()["title"]}


async def _run(data_dir: Path) -> None:
    app = create_app(data_dir=data_dir)
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://yanxu.seed", timeout=180.0) as client:
            status = await client.get("/api/system/status")
            status.raise_for_status()
            info = status.json()
            print("研续示例数据播种 · 全部写入真实 PowerContext")
            _line("PowerContext 版本", info["powercontext_version"])
            _line("内嵌 Server", info["powercontext_base_url"])
            _line("存储后端", info["storage_backend"])
            _line("记忆数据库", info["database_path"])
            _line("自动记忆提取", info["capabilities"]["memory_extraction"])
            _line("可用检索方式", ", ".join(info["capabilities"]["search_modes"]))
            result = await _seed(client)

    report_path = data_dir / "示例周报.md"
    report_path.write_text(result["markdown"], encoding="utf-8")
    print(f"\n周报 Markdown 已写出：{report_path}（{len(result['markdown'])} 字符）")
    print("接下来可以启动服务在浏览器里查看：")
    print(f"    set YANXU_DATA_DIR={data_dir}")
    print(f"    python -m app.main")


def main() -> None:
    # Windows 控制台默认 GBK，中文示例数据会变成乱码；这里只改本进程的输出编码。
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="从空数据目录播种研续示例数据")
    parser.add_argument("--data-dir", default=str(config.QODER_ROOT / "data" / "demo"), help="数据目录，默认 data/demo")
    parser.add_argument("--force", action="store_true", help="目录已存在时先清空（默认拒绝，避免覆盖真实数据）")
    args = parser.parse_args()

    data_dir = Path(args.data_dir).expanduser().resolve()
    if data_dir.exists() and any(data_dir.iterdir()):
        if not args.force:
            raise SystemExit(f"数据目录非空：{data_dir}\n确认要重建请加 --force（会先删除该目录）。")
        print(f"清空既有数据目录：{data_dir}")
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    asyncio.run(_run(data_dir))


if __name__ == "__main__":
    main()
