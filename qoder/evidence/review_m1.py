"""Coordinator's independent acceptance probes; no mocked PowerContext calls."""
import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from conftest import yanxu_client, create_project


async def main():
    results = {}
    async with yanxu_client(ROOT / "data" / ("review-" + uuid4().hex[:8])) as (_, client):
        project = await create_project(client, "独立验收：状态与交接版本")
        base = f"/api/projects/{project['project_id']}"
        for kind, title, status in [
            ("open_question", "已经解决的问题", "resolved"),
            ("next_step", "已经完成的步骤", "done"),
            ("next_step", "已经放弃的步骤", "dropped"),
        ]:
            response = await client.post(base + "/entries", json={"kind": kind, "title": title, "status": status})
            response.raise_for_status()
        draft = (await client.get(base + "/handoff/draft")).json()
        restored = (await client.get(base + "/restore")).json()
        results["resolved_state"] = {
            "draft_disposition": draft["disposition"],
            "draft_omissions": draft["omissions"],
            "restore_open_questions": [e["status"] for e in restored["open_questions"]],
            "restore_next_steps": [e["status"] for e in restored["next_steps"]],
        }
        payload = {"objective": "浏览器已查看的旧交接", "state": [{"text": "旧状态"}], "disposition": "continuable"}
        first = await client.post(base + "/handoff", json=payload)
        first.raise_for_status()
        viewed_revision = first.json()["selected_revision"]
        payload["objective"] = "另一个窗口提交、当前用户未查看的新交接"
        second = await client.post(base + "/handoff", json=payload)
        second.raise_for_status()
        ack = await client.post(base + "/handoff/acknowledge", json={
            "status": "accepted", "live_state_checked": True,
            "revision": viewed_revision, "message": "仅核对过旧版本",
        })
        results["ack_revision"] = {
            "viewed": viewed_revision, "latest": second.json()["selected_revision"],
            "http_status": ack.status_code, "acknowledged": ack.json().get("selected_revision"),
        }
        exact = await client.get(base + "/handoff", params={"selection": "exact", "revision": viewed_revision["revision"]})
        results["exact_handoff_read"] = {"http_status": exact.status_code, "response": exact.json()}
        report = await client.post(base + "/report", json={"date_from": "2026-11-30", "date_to": "2026-11-01"})
        results["reversed_report_range_status"] = report.status_code
    target = ROOT / "evidence" / "independent-review-m1.json"
    target.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))


asyncio.run(main())
