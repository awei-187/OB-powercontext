"""端到端验收测试：全部打真实的内嵌 PowerContext Server（SQLite），无 mock。

对应 qoder/PROJECT.md 第 5 节的验收标准 A1–A10。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from conftest import create_project, yanxu_client


def test_full_continuity_loop(tmp_path: Path) -> None:
    """录入 → 保存交接 → 新会话恢复 → 带来源报告（A5 A6 A7）。"""

    async def scenario() -> None:
        async with yanxu_client(tmp_path) as (app, client):
            project = await create_project(client, "跨模态检索", goal="验证图文检索在小样本上的召回提升")
            project_id = project["project_id"]
            assert project["scope_id"].startswith("scp_")
            assert project["counts"]["goal"] == 1

            async def add(kind: str, **fields: object) -> dict:
                response = await client.post(
                    f"/api/projects/{project_id}/entries", json={"kind": kind, **fields}
                )
                assert response.status_code == 201, response.text
                return response.json()

            decision = await add(
                "decision",
                title="检索层改用 FTS",
                body="在配置 embedding 之前，先用 FTS 建立可复现基线。",
                date="2026-11-02",
                status="confirmed",
                reason="无模型密钥也要能跑通闭环",
            )
            question = await add(
                "open_question", title="小样本召回为何偏低", body="nDCG@10 只有 0.31，怀疑是分词问题。",
                date="2026-11-02", status="open",
            )
            step = await add("next_step", title="跑一次分词消融", date="2026-11-03", status="open")
            todo = await add("todo", title="整理实验数据到共享盘", status="open")
            record = await add(
                "record", title="基线复现", body="跑通 baseline，nDCG@10=0.31。", date="2026-11-02",
                tags=["实验", "基线"],
            )
            source = await add(
                "source", title="CLIP 论文", url="https://arxiv.org/abs/2103.00020",
                body="对比学习的图文对齐做法，与本项目的检索目标直接相关。",
            )
            assert decision["reason"] == "无模型密钥也要能跑通闭环"
            assert decision["change_ops"] == ["add"]
            assert record["tags"] == ["实验", "基线"]
            assert source["url"] == "https://arxiv.org/abs/2103.00020"

            listed = (await client.get(f"/api/projects/{project_id}/entries")).json()
            assert len(listed) == 7, [item["kind"] for item in listed]

            # 检索：真实 FTS，只应命中本项目
            hits = (
                await client.post(f"/api/projects/{project_id}/search", json={"query": "baseline", "mode": "fts"})
            ).json()
            assert len(hits) >= 1
            assert hits[0]["entry"]["kind"] in {"record", "decision"}

            # 交接草稿由当前记忆预填，且每条陈述带真实 citation
            draft_response = await client.get(f"/api/projects/{project_id}/handoff/draft")
            assert draft_response.status_code == 200, draft_response.text
            draft = draft_response.json()
            assert draft["objective"].startswith("验证图文检索")
            assert any(claim["citation"] for claim in draft["state"])

            # 保存交接
            payload = {
                "objective": draft["objective"],
                "disposition": "continuable",
                "state": [
                    {"text": "已确认：检索层先走 FTS 基线", "citation": decision["citation"]},
                    {"text": "已完成基线复现，nDCG@10=0.31", "citation": record["citation"]},
                ],
                "next_action": {"text": "下一步：跑分词消融", "citation": step["citation"]},
                "omissions": ["小样本召回偏低的原因尚未定位"],
            }
            saved = await client.post(f"/api/projects/{project_id}/handoff", json=payload)
            assert saved.status_code == 200, saved.text
            handoff = saved.json()
            assert handoff["status"] == "resolved"
            assert handoff["selected_revision"]["revision"] == 1
            assert handoff["boundary_source_id"]
            assert len(handoff["state"]) == 2
            assert handoff["omissions"] == ["小样本召回偏低的原因尚未定位"]

            revision = handoff["selected_revision"]

            # 接手必须绑定「本人核对过的那个 Revision」：不带版本就接手要被拒，
            # 研续不替用户猜版本，也不会悄悄换成最新版。
            no_revision = await client.post(
                f"/api/projects/{project_id}/handoff/acknowledge",
                json={
                    "status": "accepted",
                    "live_state_checked": True,
                    "capability_checked": True,
                    "authorization_checked": True,
                },
            )
            assert no_revision.status_code == 400, no_revision.text
            assert no_revision.json()["error"]["code"] == "acknowledge_revision_required"

            # 未勾选核对就 accepted 必须被拒（PowerContext 的硬约束）
            rejected = await client.post(
                f"/api/projects/{project_id}/handoff/acknowledge",
                json={"status": "accepted", "revision": revision, "live_state_checked": False},
            )
            assert rejected.status_code == 400, rejected.text
            assert "confirmed" in rejected.json()["error"]["message"]

            # 新会话恢复
            restore = await client.get(f"/api/projects/{project_id}/restore")
            assert restore.status_code == 200, restore.text
            brief = restore.json()
            assert brief["handoff"]["status"] == "resolved"
            assert brief["handoff"]["objective"] == payload["objective"]
            assert brief["handoff"]["next_action"]["text"] == "下一步：跑分词消融"
            assert [item["title"] for item in brief["decisions"]] == ["检索层改用 FTS"]
            assert [item["title"] for item in brief["open_questions"]] == ["小样本召回为何偏低"]
            assert [item["title"] for item in brief["next_steps"]] == ["跑一次分词消融"]
            assert [item["title"] for item in brief["todos_open"]] == ["整理实验数据到共享盘"]
            assert brief["entry_total"] == 7
            # 引用的都是真实存在的记忆，PowerContext 自检应为 available
            assert brief["handoff"]["evidence_checks"], "应返回逐条陈述的证据可用性检查"
            assert all(check["status"] == "available" for check in brief["handoff"]["evidence_checks"]), (
                brief["handoff"]["evidence_checks"]
            )
            assert brief["prepared_context"] is not None
            assert brief["prepared_context"]["status"] in {"empty", "ready"}

            # 正式接手：三项核对全部勾选，并回传本人看过的 Revision
            ack = await client.post(
                f"/api/projects/{project_id}/handoff/acknowledge",
                json={
                    "status": "accepted",
                    "revision": revision,
                    "live_state_checked": True,
                    "capability_checked": True,
                    "authorization_checked": True,
                    "message": "已核对，继续推进",
                },
            )
            assert ack.status_code == 200, ack.text
            receipt = ack.json()
            assert receipt["receipt_source_id"].startswith("yanxu-ack-")
            # 回执可验证：读回的 Revision 必须就是本人核对过的那个
            assert receipt["selected_revision"]["revision"] == revision["revision"]

            # 带来源的报告
            report_response = await client.post(
                f"/api/projects/{project_id}/report",
                json={"report_type": "weekly", "date_from": "2026-11-01", "date_to": "2026-11-07"},
            )
            assert report_response.status_code == 200, report_response.text
            report = report_response.json()
            markdown = report["markdown"]
            assert markdown.startswith("# 周报 · 跨模态检索")
            for heading in ("## 一、研究目标", "## 三、已确认决策", "## 四、未解决问题",
                            "## 五、下一步计划", "## 七、资料出处", "## 附录 · 来源追溯表"):
                assert heading in markdown, heading
            assert decision["ref_label"] in markdown
            assert decision["citation"]["entry_id"] in markdown
            assert "https://arxiv.org/abs/2103.00020" in markdown
            assert "无模型密钥也要能跑通闭环" in markdown
            assert report["citation_count"] == 7
            assert report["source_count"] == 1

    asyncio.run(scenario())


def test_project_isolation(tmp_path: Path) -> None:
    """A1：两个项目使用同一关键词，检索互不串味。"""

    async def scenario() -> None:
        async with yanxu_client(tmp_path) as (_app, client):
            left = await create_project(client, "项目甲")
            right = await create_project(client, "项目乙")
            assert left["scope_id"] != right["scope_id"]

            for project, word in ((left, "量子纠错阈值"), (right, "量子纠错阈值")):
                response = await client.post(
                    f"/api/projects/{project['project_id']}/entries",
                    json={"kind": "decision", "title": word, "body": f"{word} 的结论属于 {project['name']}",
                          "reason": "隔离验证"},
                )
                assert response.status_code == 201, response.text

            for project, own, other in ((left, "项目甲", "项目乙"), (right, "项目乙", "项目甲")):
                hits = (
                    await client.post(
                        f"/api/projects/{project['project_id']}/search",
                        json={"query": "量子纠错阈值", "mode": "fts", "limit": 50},
                    )
                ).json()
                bodies = " ".join(hit["entry"]["body"] for hit in hits)
                assert len(hits) == 1, f"{project['name']} 命中数应为 1，实际 {len(hits)}"
                assert own in bodies
                assert other not in bodies, "跨项目记忆泄漏"

                entries = (await client.get(f"/api/projects/{project['project_id']}/entries")).json()
                assert len(entries) == 1

            projects = (await client.get("/api/projects")).json()
            assert len(projects) == 2

    asyncio.run(scenario())


def test_revision_history_and_conflict(tmp_path: Path) -> None:
    """A3 A4：修订保留历史、旧快照可读回、陈旧 citation 触发真实 409。"""

    async def scenario() -> None:
        async with yanxu_client(tmp_path) as (_app, client):
            project = await create_project(client, "修订历史验证")
            project_id = project["project_id"]
            created = (
                await client.post(
                    f"/api/projects/{project_id}/entries",
                    json={"kind": "decision", "title": "批大小 512", "body": "初版结论", "reason": "首次录入"},
                )
            ).json()
            first_citation = created["citation"]

            revised = await client.patch(
                f"/api/projects/{project_id}/entries/{created['citation']['entry_id']}",
                json={
                    "citation": first_citation,
                    "patch": {"kind": "decision", "title": "批大小 256", "body": "压测后修正", "reason": "压测发现显存不足"},
                    "reason": "压测发现显存不足",
                },
            )
            assert revised.status_code == 200, revised.text
            after = revised.json()
            assert after["citation"]["entry_id"] == first_citation["entry_id"]
            assert after["citation"]["entry_version_id"] != first_citation["entry_version_id"]
            assert after["version"] == created["version"] + 1
            assert after["title"] == "批大小 256"

            # 陈旧 citation 再修订 → PowerContext 真实 409
            conflict = await client.patch(
                f"/api/projects/{project_id}/entries/{first_citation['entry_id']}",
                json={
                    "citation": first_citation,
                    "patch": {"kind": "decision", "title": "批大小 128", "body": "第三次修改"},
                    "reason": "应当冲突",
                },
            )
            assert conflict.status_code == 409, conflict.text
            body = conflict.json()["error"]
            assert body["code"] == "powercontext_server_response"
            assert body["status"] == 409
            assert body["request_id"], "必须带上 PowerContext 真实 request_id"

            history = (
                await client.get(f"/api/projects/{project_id}/entries/{first_citation['entry_id']}/history")
            ).json()
            assert history["current"]["title"] == "批大小 256"
            titles = [snapshot["title"] for snapshot in history["snapshots"]]
            assert "批大小 512" in titles and "批大小 256" in titles, titles
            assert [change["op"] for change in history["changes"]] == ["add", "revise"]
            assert any(change["reason"] == "压测发现显存不足" for change in history["changes"])

            # 旧 citation 仍可读回旧快照
            old = await client.get(
                f"/api/projects/{project_id}/entries/{first_citation['entry_id']}/history"
            )
            assert old.status_code == 200

            # retire：PowerContext 无物理删除，退役后默认列表不可见但历史保留
            retired = await client.post(
                f"/api/projects/{project_id}/entries/{after['citation']['entry_id']}/retire",
                json={"citation": after["citation"], "reason": "结论已被新实验推翻"},
            )
            assert retired.status_code == 200, retired.text
            active = (await client.get(f"/api/projects/{project_id}/entries")).json()
            assert active == []
            with_inactive = (
                await client.get(f"/api/projects/{project_id}/entries", params={"include_inactive": "true"})
            ).json()
            assert len(with_inactive) == 1
            assert with_inactive[0]["state"] == "inactive"

            changes = (await client.get(f"/api/projects/{project_id}/changes")).json()["changes"]
            ops = [change["op"] for change in changes]
            assert ops == ["add", "revise", "deactivate"], ops
            assert changes[-1]["reason"] == "结论已被新实验推翻"

    asyncio.run(scenario())


def test_real_error_surfacing(tmp_path: Path) -> None:
    """A8：超长文本 422、需要模型的端点 503，全部原样透传。"""

    async def scenario() -> None:
        from powercontext.client import ServerResponseError
        from powercontext.http import PrepareHandoffRequest

        async with yanxu_client(tmp_path) as (app, client):
            project = await create_project(client, "错误提示验证")
            project_id = project["project_id"]
            scope_id = project["scope_id"]

            oversized = await client.post(
                f"/api/projects/{project_id}/entries",
                json={"kind": "record", "title": "超长记录", "body": "长" * 4000},
            )
            assert oversized.status_code == 422, oversized.text
            error = oversized.json()["error"]
            assert error["code"] == "powercontext_server_response"
            assert error["request_id"], "必须带上 PowerContext 真实 request_id"
            assert error["message"], "必须带上 Server 的真实错误消息"

            missing = await client.get("/api/projects/prj_does_not_exist")
            assert missing.status_code == 404
            assert missing.json()["error"]["code"] == "project_not_found"

            empty_handoff = await client.post(
                f"/api/projects/{project_id}/handoff",
                json={"objective": "目标", "state": [], "disposition": "continuable"},
            )
            assert empty_handoff.status_code == 400
            assert empty_handoff.json()["error"]["code"] == "handoff_state_required"

            # 需要生成模型的端点：真实返回 503，研续不使用它
            entry = (
                await client.post(
                    f"/api/projects/{project_id}/entries",
                    json={"kind": "decision", "title": "用于证据引用的决策"},
                )
            ).json()
            citation = entry["citation"]
            pc_client = app.state.client  # type: ignore[attr-defined]
            with pytest.raises(ServerResponseError) as excinfo:
                await pc_client.prepare_handoff(
                    PrepareHandoffRequest(
                        scope_id=scope_id,
                        objective="需要模型生成的交接",
                        evidence=[
                            {
                                "kind": "memory",
                                "memory_citation": {
                                    "memory_ref": citation["memory_ref"],
                                    "entry_id": citation["entry_id"],
                                    "entry_version_id": citation["entry_version_id"],
                                },
                            }
                        ],
                    )
                )
            assert excinfo.value.status_code == 503, excinfo.value.status_code
            assert excinfo.value.code == "handoff_generation_unavailable"

    asyncio.run(scenario())


def test_transport_error_when_server_stopped(tmp_path: Path) -> None:
    """A8：内嵌 Server 停止后必须报真实的连接层失败，不能假装成功。

    实测本机行为：端口关闭后，有时是连接被拒（TransportError → 502 powercontext_transport），
    有时是本机网络拦截组件在无监听端口上代答一个空响应体的 HTTP 502
    （ServerResponseError → 502 powercontext_server_response）。两者都是真实失败，
    因此这里断言「必须是可归因于 PowerContext 的 5xx 真实错误」，而不是某一个具体分类。
    """

    async def scenario() -> None:
        async with yanxu_client(tmp_path) as (app, client):
            project = await create_project(client, "连接中断验证")
            entries_url = f"/api/projects/{project['project_id']}/entries"
            assert (await client.get(entries_url)).status_code == 200

            await app.state.host.stop()  # type: ignore[attr-defined]
            assert app.state.host.running is False  # type: ignore[attr-defined]

            response = await client.get(entries_url)
            assert response.status_code >= 500, response.text
            error = response.json()["error"]
            assert error["code"].startswith("powercontext_"), response.text
            assert error["code"] in {"powercontext_transport", "powercontext_server_response"}
            assert error["status"] == response.status_code
            assert "PowerContext" in error["message"]
            # 绝不返回伪造的成功数据
            assert not isinstance(response.json(), list), "服务不可用时不得返回空列表冒充成功"

    asyncio.run(scenario())


def test_no_model_keys_required(tmp_path: Path) -> None:
    """A9：零模型密钥下能力如实上报。"""

    async def scenario() -> None:
        async with yanxu_client(tmp_path) as (_app, client):
            status_response = await client.get("/api/system/status")
            assert status_response.status_code == 200, status_response.text
            status = status_response.json()
            assert status["powercontext_running"] is True
            assert status["powercontext_version"] == "1.2.0"
            assert status["storage_backend"] == "sqlite"
            assert status["model_keys_configured"] is False
            assert status["capabilities"]["memory_extraction"] is False
            assert status["capabilities"]["handoff_generation"] is False
            assert "fts" in status["capabilities"]["search_modes"]
            assert status["powercontext_base_url"].startswith("http://127.0.0.1:")
            assert status["notes"], "必须显式告知能力边界"

            meta = (await client.get("/api/system/meta")).json()
            assert {item["value"] for item in meta["kinds"]} == {
                "goal", "record", "decision", "open_question", "next_step", "todo", "source"
            }

    asyncio.run(scenario())


def test_data_survives_full_restart(tmp_path: Path) -> None:
    """A2 A10：应用整体重启后，数据从 PowerContext SQLite 完整读回。"""

    async def scenario() -> None:
        async with yanxu_client(tmp_path) as (_app, client):
            project = await create_project(client, "重启验证", goal="重启后目标必须还在")
            created = (
                await client.post(
                    f"/api/projects/{project['project_id']}/entries",
                    json={"kind": "decision", "title": "重启动作", "body": "重启前后必须一致", "reason": "持久化验证"},
                )
            ).json()
            await client.post(
                f"/api/projects/{project['project_id']}/handoff",
                json={
                    "objective": "重启后继续",
                    "state": [{"text": "已确认：重启动作", "citation": created["citation"]}],
                    "disposition": "continuable",
                    "next_action": {"text": "重启并核对"},
                    "omissions": [],
                },
            )

        # 全新 app 实例（新的内嵌 Server 进程内实例 + 新事件循环），同一数据目录
        async with yanxu_client(tmp_path) as (_app2, client2):
            projects = (await client2.get("/api/projects")).json()
            assert len(projects) == 1
            assert projects[0]["project_id"] == project["project_id"]
            assert projects[0]["scope_id"] == project["scope_id"]
            assert projects[0]["counts"]["decision"] == 1

            entries = (await client2.get(f"/api/projects/{project['project_id']}/entries")).json()
            assert len(entries) == 2
            by_title = {item["title"]: item for item in entries}
            assert by_title["重启动作"]["body"] == "重启前后必须一致"
            assert by_title["重启动作"]["reason"] == "持久化验证"
            assert by_title["重启动作"]["citation"] == created["citation"]

            brief = (await client2.get(f"/api/projects/{project['project_id']}/restore")).json()
            assert brief["handoff"]["status"] == "resolved"
            assert brief["handoff"]["objective"] == "重启后继续"
            assert brief["goals"][0]["body"] == "重启后目标必须还在"

    asyncio.run(scenario())
