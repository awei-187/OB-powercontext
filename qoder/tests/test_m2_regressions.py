"""M2 回归测试：独立验收发现的每一个问题都要有一个能复现旧错误行为的断言。

全部打真实的内嵌 PowerContext Server（SQLite），无 mock。
每个测试的 docstring 里写清「修复前的错误行为」，这样断言失败时能直接看出是哪一处回退。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from conftest import create_project, yanxu_client


async def _add(client: httpx.AsyncClient, project_id: str, kind: str, **fields: object) -> dict:
    response = await client.post(
        f"/api/projects/{project_id}/entries", json={"kind": kind, **fields}
    )
    assert response.status_code == 201, response.text
    return response.json()


def _titles(entries: list[dict]) -> set[str]:
    """按标题集合比较：列表顺序由 PowerContext 的工件版本排序决定，不承载语义。"""
    return {item["title"] for item in entries}


async def _fresh(client: httpx.AsyncClient, project_id: str, entry_id: str) -> dict:
    """重新读回条目的当前 citation。

    MemoryCitation.memory_ref.revision 是工件全局的，Scope 内任何一次写入都会推进它，
    因此拿着旧 citation 去 revise 会被 PowerContext 判为 revision_conflict。
    """
    listed = (
        await client.get(f"/api/projects/{project_id}/entries", params={"include_inactive": "true"})
    ).json()
    matches = [item for item in listed if item["citation"]["entry_id"] == entry_id]
    assert len(matches) == 1, (entry_id, listed)
    return matches[0]


async def _revise(
    client: httpx.AsyncClient, project_id: str, entry: dict, *, change_reason: str, **fields: object
) -> dict:
    entry = await _fresh(client, project_id, entry["citation"]["entry_id"])
    patch = {
        "kind": entry["kind"],
        "title": entry["title"],
        "body": entry["body"],
        "date": entry["date"],
        "status": entry["status"],
        "tags": entry["tags"],
        "url": entry["url"],
        "refs": entry["refs"],
        "reason": entry["reason"],
    }
    patch.update(fields)
    response = await client.patch(
        f"/api/projects/{project_id}/entries/{entry['citation']['entry_id']}",
        json={"citation": entry["citation"], "patch": patch, "reason": change_reason},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _save_handoff(
    client: httpx.AsyncClient, project_id: str, objective: str, *, citation: dict | None = None
) -> dict:
    response = await client.post(
        f"/api/projects/{project_id}/handoff",
        json={
            "objective": objective,
            "disposition": "continuable",
            "state": [{"text": f"已确认：{objective}", "citation": citation}],
            "next_action": {"text": "下一步：继续核对"},
            "omissions": [],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


ALL_CHECKS = {
    "live_state_checked": True,
    "capability_checked": True,
    "authorization_checked": True,
}


def test_effective_state_semantics(tmp_path: Path) -> None:
    """有效状态语义：已解决的问题 / 已关闭的下一步不再冒充「待办」。

    修复前：问题全部 resolved、下一步全部 done/dropped 时，交接草稿判定仍是 blocked，
    恢复简报还把这些已关闭条目塞回「未解决问题」「下一步」，接手人会被直接误导。
    """

    async def scenario() -> None:
        async with yanxu_client(tmp_path) as (_app, client):
            project = await create_project(client, "收尾验证", goal="把问题全部关掉")
            project_id = project["project_id"]

            question = await _add(client, project_id, "open_question", title="召回为何偏低", status="open")
            step = await _add(client, project_id, "next_step", title="跑分词消融", status="open")
            dropped = await _add(client, project_id, "next_step", title="换检索引擎", status="open")

            draft = (await client.get(f"/api/projects/{project_id}/handoff/draft")).json()
            assert draft["disposition"] == "continuable", draft["disposition"]

            # 关掉下一步（一个完成、一个放弃），问题仍悬着 → 真的 blocked
            step = await _revise(client, project_id, step, change_reason="消融已跑完", status="done")
            dropped = await _revise(client, project_id, dropped, change_reason="评估后不再考虑", status="dropped")
            draft = (await client.get(f"/api/projects/{project_id}/handoff/draft")).json()
            assert draft["disposition"] == "blocked", draft["disposition"]

            brief = (await client.get(f"/api/projects/{project_id}/restore")).json()
            assert [item["title"] for item in brief["open_questions"]] == ["召回为何偏低"]
            assert brief["next_steps"] == [], "done / dropped 的下一步不是可行动项"
            assert _titles(brief["closed_next_steps"]) == {"跑分词消融", "换检索引擎"}

            # 问题也解决掉 → complete，而不是继续报 blocked
            await _revise(client, project_id, question, change_reason="定位为分词粒度", status="resolved")
            draft = (await client.get(f"/api/projects/{project_id}/handoff/draft")).json()
            assert draft["disposition"] == "complete", draft["disposition"]

            brief = (await client.get(f"/api/projects/{project_id}/restore")).json()
            assert brief["open_questions"] == [], "已解决的问题不能再出现在「未解决问题」里"
            assert brief["next_steps"] == []
            assert _titles(brief["resolved_questions"]) == {"召回为何偏低"}
            assert _titles(brief["closed_next_steps"]) == {"跑分词消融", "换检索引擎"}

    asyncio.run(scenario())


def test_acknowledge_binds_the_revision_actually_reviewed(tmp_path: Path) -> None:
    """接手必须绑定本人核对过的 Revision。

    修复前：请求里的 revision 被忽略，用户核对的是 r1、回执却落在 r2，服务端还返回 200。
    实测 PowerContext 对陈旧 revision 的 acknowledge 是**静默接受**的，
    所以这道诚实闸门必须由研续自己把住：不一致就 409 要求刷新。
    """

    async def scenario() -> None:
        async with yanxu_client(tmp_path) as (_app, client):
            project = await create_project(client, "版本竞争验证")
            project_id = project["project_id"]

            first = await _save_handoff(client, project_id, "第一版交接目标")
            second = await _save_handoff(client, project_id, "第二版交接目标")
            r1 = first["selected_revision"]
            r2 = second["selected_revision"]
            assert (r1["revision"], r2["revision"]) == (1, 2)

            stale = await client.post(
                f"/api/projects/{project_id}/handoff/acknowledge",
                json={"status": "accepted", "revision": r1, **ALL_CHECKS},
            )
            assert stale.status_code == 409, stale.text
            body = stale.json()["error"]
            assert body["code"] == "handoff_revision_stale"
            assert body["details"]["viewed"]["revision"] == 1
            assert body["details"]["latest"]["revision"] == 2
            assert "刷新" in body["message"]

            # 陈旧版本即使不是 accepted 也不能悄悄接手
            declined = await client.post(
                f"/api/projects/{project_id}/handoff/acknowledge",
                json={"status": "declined", "revision": r1},
            )
            assert declined.status_code == 409, declined.text

            fresh = await client.post(
                f"/api/projects/{project_id}/handoff/acknowledge",
                json={"status": "accepted", "revision": r2, **ALL_CHECKS, "message": "已核对第二版"},
            )
            assert fresh.status_code == 200, fresh.text
            receipt = fresh.json()
            # 回执可验证：读回的 Revision 就是本人核对过的那个
            assert receipt["selected_revision"]["revision"] == 2
            assert receipt["objective"] == "第二版交接目标"
            assert receipt["receipt_source_id"].startswith("yanxu-ack-")

            # 非法引用：revision < 1、工件族不对，都在调用 PowerContext 之前就被拒
            for bad in (
                {**r2, "revision": 0},
                {**r2, "family": "memory"},
                {**r2, "artifact_id": "handoff-other"},
            ):
                response = await client.post(
                    f"/api/projects/{project_id}/handoff/acknowledge",
                    json={"status": "accepted", "revision": bad, **ALL_CHECKS},
                )
                assert response.status_code == 400, (bad, response.text)
                assert response.json()["error"]["code"] == "invalid_handoff_revision"

    asyncio.run(scenario())


def test_acknowledge_receiver_checks_are_all_three(tmp_path: Path) -> None:
    """ReceiverChecks 有三个字段，accepted 时必须全部 confirmed。

    修复前：界面只有一个「我已核对状态」勾选框，capability / authorization 永远是
    not_checked，却照样以 status=accepted 提交——文案与实际含义不一致。
    """

    async def scenario() -> None:
        async with yanxu_client(tmp_path) as (_app, client):
            project = await create_project(client, "核对项验证")
            project_id = project["project_id"]
            saved = await _save_handoff(client, project_id, "核对三项")
            revision = saved["selected_revision"]

            for partial in (
                {"live_state_checked": True},
                {"capability_checked": True},
                {"authorization_checked": True},
                {"live_state_checked": True, "capability_checked": True},
                {},
            ):
                response = await client.post(
                    f"/api/projects/{project_id}/handoff/acknowledge",
                    json={"status": "accepted", "revision": revision, **partial},
                )
                assert response.status_code == 400, (partial, response.text)
                error = response.json()["error"]
                assert error["code"] == "handoff_ack_requires_check"
                assert "confirmed" in error["message"]

            # needs_clarification / declined 不要求三项全勾，这是官方语义，不能一刀切
            for status in ("needs_clarification", "declined"):
                response = await client.post(
                    f"/api/projects/{project_id}/handoff/acknowledge",
                    json={"status": status, "revision": revision, "message": "需要先澄清"},
                )
                assert response.status_code == 200, (status, response.text)
                assert response.json()["selected_revision"]["revision"] == revision["revision"]

    asyncio.run(scenario())


def test_exact_handoff_revision_read(tmp_path: Path) -> None:
    """按精确 Revision 读取历史交接。

    修复前：GET /handoff 路由根本没有 revision 参数，
    `?selection=exact&revision=1` 直接返回 400 handoff_revision_required。
    """

    async def scenario() -> None:
        async with yanxu_client(tmp_path) as (_app, client):
            left = await create_project(client, "精确读取甲")
            right = await create_project(client, "精确读取乙")
            left_id, right_id = left["project_id"], right["project_id"]

            await _save_handoff(client, left_id, "甲的第一版")
            await _save_handoff(client, left_id, "甲的第二版")

            exact = await client.get(f"/api/projects/{left_id}/handoff", params={"selection": "exact", "revision": 1})
            assert exact.status_code == 200, exact.text
            view = exact.json()
            assert view["status"] == "resolved"
            assert view["objective"] == "甲的第一版"
            assert view["selected_revision"]["revision"] == 1

            second = await client.get(f"/api/projects/{left_id}/handoff", params={"selection": "exact", "revision": 2})
            assert second.status_code == 200, second.text
            assert second.json()["objective"] == "甲的第二版"

            latest = await client.get(f"/api/projects/{left_id}/handoff")
            assert latest.status_code == 200, latest.text
            assert latest.json()["selected_revision"]["revision"] == 2

            # 不存在的版本：PowerContext 真实 404，研续原样透传并给出可理解的提示
            missing = await client.get(f"/api/projects/{left_id}/handoff", params={"selection": "exact", "revision": 999})
            assert missing.status_code == 404, missing.text
            error = missing.json()["error"]
            assert error["code"] == "powercontext_server_response"
            assert error["request_id"], "必须带上 PowerContext 真实 request_id"
            assert error["hint"], "必须告诉用户这个版本不存在或不属于本项目"

            # 跨项目读同一个版本号：Scope 隔离必须挡住
            cross = await client.get(f"/api/projects/{right_id}/handoff", params={"selection": "exact", "revision": 1})
            assert cross.status_code == 404, cross.text

            # 参数校验：exact 缺 revision、revision 非法、selection 非法
            no_revision = await client.get(f"/api/projects/{left_id}/handoff", params={"selection": "exact"})
            assert no_revision.status_code == 400, no_revision.text
            assert no_revision.json()["error"]["code"] == "handoff_revision_required"

            zero = await client.get(f"/api/projects/{left_id}/handoff", params={"selection": "exact", "revision": 0})
            assert zero.status_code == 422, zero.text

            bogus = await client.get(f"/api/projects/{left_id}/handoff", params={"selection": "prepared"})
            assert bogus.status_code == 400, bogus.text
            assert bogus.json()["error"]["code"] == "invalid_selection"

    asyncio.run(scenario())


def test_report_time_semantics_and_citation_honesty(tmp_path: Path) -> None:
    """报告的时间口径、区间过滤与引用计数必须诚实。

    修复前：起止倒置的区间返回 200 空报告；已解决的问题被写进「本期已解决」冒充按区间过滤；
    dropped 的下一步被写成待完成；附录与 citation_count 把根本没出现在正文的条目也算进去。
    """

    async def scenario() -> None:
        async with yanxu_client(tmp_path) as (_app, client):
            project = await create_project(client, "报告口径验证", goal="验证报告的诚实性")
            project_id = project["project_id"]

            in_range = await _add(client, project_id, "record", title="本期实验", body="跑通基线", date="2026-11-02")
            out_of_range = await _add(client, project_id, "record", title="上期实验", body="旧数据", date="2026-10-01")
            await _add(client, project_id, "decision", title="先用 FTS", status="confirmed", reason="无密钥也能跑")
            resolved = await _add(
                client,
                project_id,
                "open_question",
                title="分词粒度",
                body="中文该按字还是按词切",
                status="open",
                date="2026-10-02",
            )
            await _revise(client, project_id, resolved, change_reason="已定位", status="resolved")
            dropped = await _add(
                client, project_id, "next_step", title="换检索引擎", body="改成向量检索", status="open"
            )
            await _revise(client, project_id, dropped, change_reason="不再考虑", status="dropped")
            await _add(client, project_id, "todo", title="整理数据", status="open")
            await _add(client, project_id, "source", title="CLIP 论文", url="https://arxiv.org/abs/2103.00020")

            # 起止倒置：这是调用方的错误，不能返回一份看起来正常的空报告
            reversed_range = await client.post(
                f"/api/projects/{project_id}/report",
                json={"report_type": "weekly", "date_from": "2026-11-07", "date_to": "2026-11-01"},
            )
            assert reversed_range.status_code == 422, reversed_range.text
            assert "不能晚于" in reversed_range.json()["error"]["message"]

            # 非法日期：字符串区间比较的前提是格式统一
            for bad in ({"date_from": "2026-1-5"}, {"date_from": "2026-13-45"}, {"date_to": "昨天"}):
                response = await client.post(
                    f"/api/projects/{project_id}/report", json={"report_type": "weekly", **bad}
                )
                assert response.status_code == 422, (bad, response.text)
                assert "ISO 日期" in response.json()["error"]["message"]

            response = await client.post(
                f"/api/projects/{project_id}/report",
                json={
                    "report_type": "weekly",
                    "date_from": "2026-11-01",
                    "date_to": "2026-11-07",
                    "include_done_todos": True,
                },
            )
            assert response.status_code == 200, response.text
            report = response.json()
            markdown = report["markdown"]

            # 时间口径写进正文，不靠读者猜
            assert "时间口径" in markdown
            assert "不记录解决 / 完成的发生时间" in markdown

            # 区间只过滤带日期的工作记录
            assert in_range["ref_label"] in markdown
            assert out_of_range["ref_label"] not in markdown, "区间外的记录不该出现在报告里"
            assert "上期实验" not in markdown

            # 已解决的问题按当前状态列出，且明确说明不按区间过滤
            assert "### 已解决（当前有效状态，不按区间过滤）" in markdown
            assert "本期已解决" not in markdown, "不能把当前状态冒称成发生在统计区间内"
            assert "- [x] **分词粒度** — 中文该按字还是按词切 " in markdown
            assert "- [ ] **分词粒度**" not in markdown

            # 已放弃的下一步绝不是待完成项
            assert "- ~~**换检索引擎** — 改成向量检索~~" in markdown
            assert "- [ ] **换检索引擎**" not in markdown
            assert "已放弃（不再计划）" in markdown

            # 附录与计数只认真正出现在正文里的条目
            appendix = markdown.split("## 附录 · 来源追溯表", 1)[1]
            rows = [line for line in appendix.splitlines() if line.startswith("| ")][2:]
            assert len(rows) == report["citation_count"], (len(rows), report["citation_count"])
            # 目标 + 区间内记录 + 决策 + 已解决问题 + 已放弃下一步 + 待办 + 资料出处 = 7；
            # 区间外的「上期实验」没进正文，所以也不进计数。
            assert report["citation_count"] == 7, report["citation_count"]
            assert report["source_count"] == 1
            assert out_of_range["citation"]["entry_id"] not in appendix

    asyncio.run(scenario())


def test_source_url_only_http_https_is_clickable(tmp_path: Path) -> None:
    """来源链接的可点击性由 scheme 决定，不是靠 HTML 转义。

    修复前：任何 url 都被渲染成 <a href>，只做 HTML 转义挡不住 javascript: 这类 scheme。
    """

    async def scenario() -> None:
        async with yanxu_client(tmp_path) as (_app, client):
            project = await create_project(client, "链接安全验证")
            project_id = project["project_id"]

            cases = {
                "https://example.org/paper": "https://example.org/paper",
                "http://example.org/paper": "http://example.org/paper",
                "HTTPS://EXAMPLE.ORG/PAPER": "HTTPS://EXAMPLE.ORG/PAPER",
                "javascript:alert(1)": "",
                "data:text/html,<script>alert(1)</script>": "",
                "file:///C:/secrets.txt": "",
                "vbscript:msgbox(1)": "",
                "10.1000/zenodo.1234567": "",
                "": "",
            }
            for index, (url, expected_href) in enumerate(cases.items()):
                entry = await _add(client, project_id, "source", title=f"资料 {index}", url=url)
                assert entry["url"] == url, "原始标识必须原样保存，供人阅读与检索"
                assert entry["url_href"] == expected_href, (url, entry["url_href"])

            listed = (await client.get(f"/api/projects/{project_id}/entries")).json()
            for entry in listed:
                if entry["url_href"]:
                    assert entry["url_href"].lower().startswith(("http://", "https://"))

            report = (
                await client.post(f"/api/projects/{project_id}/report", json={"report_type": "weekly"})
            ).json()["markdown"]
            assert "<https://example.org/paper>" in report
            assert "javascript:" in report, "标识仍然要如实展示"
            assert "<javascript:" not in report, "非 http/https 绝不能被写成可点击链接"
            assert "（标识：10.1000/zenodo.1234567）" in report

    asyncio.run(scenario())


def test_oversized_goal_never_leaves_a_half_made_project(tmp_path: Path) -> None:
    """超长研究目标必须在创建 Scope 之前被拒。

    修复前：先建 Scope 与注册表记录、再写目标，4000 个中文字编码后超过 8192 字节被 422 打回，
    留下一个没有目标的半成品项目。
    """

    async def scenario() -> None:
        async with yanxu_client(tmp_path) as (_app, client):
            oversized = await client.post(
                "/api/projects", json={"name": "超长目标项目", "summary": "", "goal": "长" * 4000}
            )
            assert oversized.status_code == 400, oversized.text
            error = oversized.json()["error"]
            assert error["code"] == "goal_too_long"
            assert error["details"]["limit"] == 8192
            assert error["details"]["byte_length"] > 8192
            assert error["hint"]

            # 注册表里不能留下半成品项目
            assert (await client.get("/api/projects")).json() == []

            # 失败之后正常重试可用
            ok = await create_project(client, "超长目标项目", goal="精简后的目标")
            projects = (await client.get("/api/projects")).json()
            assert len(projects) == 1
            assert projects[0]["project_id"] == ok["project_id"]
            assert projects[0]["counts"]["goal"] == 1

            # 刚好在上限内的目标可以通过
            budget = "字" * 2600
            boundary = await client.post("/api/projects", json={"name": "边界项目", "goal": budget})
            assert boundary.status_code == 201, boundary.text

    asyncio.run(scenario())


def test_invalid_entry_date_is_rejected(tmp_path: Path) -> None:
    """条目日期必须是真实存在的日历日期，并统一归一成 YYYY-MM-DD。

    修复前：date 是自由字符串，`2026-13-45` 也能存进去；
    而且 Python 3.11 的 fromisoformat 接受 `20261102` 这种基本格式，
    它与 `2026-11-07` 做字典序比较时结果是错的，区间过滤会悄悄给出错误答案。
    """

    async def scenario() -> None:
        async with yanxu_client(tmp_path) as (_app, client):
            project = await create_project(client, "日期校验验证")
            project_id = project["project_id"]

            for bad in ("2026-13-45", "2026-1-5", "昨天", "2026-02-30", "2026-11-02T00:00:00"):
                response = await client.post(
                    f"/api/projects/{project_id}/entries",
                    json={"kind": "record", "title": "日期非法", "date": bad},
                )
                assert response.status_code == 422, (bad, response.text)
                error = response.json()["error"]
                assert error["code"] == "invalid_request"
                assert "ISO 日期" in error["message"], error["message"]
                assert "date" in error["message"]

            # 空日期与合法日期照常通过
            assert (await _add(client, project_id, "record", title="无日期"))["date"] == ""
            assert (await _add(client, project_id, "record", title="有日期", date="2026-02-28"))["date"] == "2026-02-28"
            assert (await _add(client, project_id, "record", title="闰日", date="2024-02-29"))["date"] == "2024-02-29"

            # ISO 基本格式被归一化，字典序区间比较才成立
            normalized = await _add(client, project_id, "record", title="基本格式", date="20261102")
            assert normalized["date"] == "2026-11-02"
            report = (
                await client.post(
                    f"/api/projects/{project_id}/report",
                    json={"report_type": "weekly", "date_from": "2026-11-01", "date_to": "2026-11-07"},
                )
            ).json()
            assert "基本格式" in report["markdown"], "归一化后的日期必须能被区间正确命中"

            # 报告区间同样归一化并接受非法日期校验
            bad_range = await client.post(
                f"/api/projects/{project_id}/report",
                json={"report_type": "weekly", "date_from": "20261107", "date_to": "20261101"},
            )
            assert bad_range.status_code == 422, bad_range.text
            assert "不能晚于" in bad_range.json()["error"]["message"]

    asyncio.run(scenario())


def test_entry_history_never_silently_truncates(tmp_path: Path) -> None:
    """修订历史读不回某个版本时要如实说明；连接层失败必须报错，不能返回残缺历史。

    修复前：entry_history 捕获任意异常后 continue，PowerContext 挂掉时会返回一份
    「看起来正常但没有快照」的历史，用户完全不知道数据其实没读到。
    """

    async def scenario() -> None:
        async with yanxu_client(tmp_path) as (app, client):
            project = await create_project(client, "历史完整性验证")
            project_id = project["project_id"]
            entry = await _add(client, project_id, "decision", title="批大小 512", reason="首次录入")
            entry = await _revise(client, project_id, entry, change_reason="压测后修正", title="批大小 256")

            history_url = f"/api/projects/{project_id}/entries/{entry['citation']['entry_id']}/history"
            healthy = await client.get(history_url)
            assert healthy.status_code == 200, healthy.text
            body = healthy.json()
            assert body["unavailable"] == [], "正常情况下不该有读不回的版本"
            # snapshots 按时间正序返回（旧 → 新），由界面负责倒序展示
            assert [snapshot["title"] for snapshot in body["snapshots"]] == ["批大小 512", "批大小 256"]
            assert [change["op"] for change in body["changes"]] == ["add", "revise"]

            await app.state.host.stop()  # type: ignore[attr-defined]
            broken = await client.get(history_url)
            assert broken.status_code >= 500, broken.text
            error = broken.json()["error"]
            assert error["code"].startswith("powercontext_"), error
            assert "changes" not in broken.json(), "服务不可用时不得返回残缺历史冒充成功"

    asyncio.run(scenario())
