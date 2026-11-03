"""交接与恢复路由：PowerContext Work Handoff（本人撰写，不需要生成模型）。"""

from __future__ import annotations

import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request

from ..deps import get_memory, get_project, get_registry
from ..errors import YanxuError
from ..memory import HANDOFF_ARTIFACT_ID, HANDOFF_FAMILY, MemoryService
from ..reports import build_report
from ..schemas import (
    AcknowledgeInput,
    ArtifactRefView,
    EntryView,
    HandoffClaimInput,
    HandoffInput,
    HandoffView,
    ProjectView,
    ReportRequest,
    ReportView,
    RestoreBrief,
)

router = APIRouter(prefix="/api/projects/{project_id}", tags=["handoff"])

RECENT_RECORD_LIMIT = 8


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _group(entries: list[EntryView]) -> dict[str, list[EntryView]]:
    grouped: dict[str, list[EntryView]] = {}
    for entry in entries:
        grouped.setdefault(entry.kind, []).append(entry)
    return grouped


def _split_questions(questions: list[EntryView]) -> tuple[list[EntryView], list[EntryView]]:
    """未解决 / 已解决。

    没有状态标注的问题按未解决处理：不知道它已经解决，就不能当已解决展示。
    """
    unresolved = [item for item in questions if item.status != "resolved"]
    resolved = [item for item in questions if item.status == "resolved"]
    return unresolved, resolved


def _split_steps(steps: list[EntryView]) -> tuple[list[EntryView], list[EntryView]]:
    """仍可行动 / 已关闭（done 或 dropped）。已放弃的下一步绝不是「待完成」。"""
    actionable = [item for item in steps if item.status not in {"done", "dropped"}]
    closed = [item for item in steps if item.status in {"done", "dropped"}]
    return actionable, closed


def _draft_disposition(
    unresolved: list[EntryView],
    actionable: list[EntryView],
    resolved: list[EntryView],
    closed: list[EntryView],
) -> str:
    """交接判定的有效状态语义。

    blocked 只属于「还有悬着的问题、且没有可行动的下一步」；
    全部问题已解决、全部步骤已关闭时是 complete 而不是 blocked——
    旧实现把「存在 open_question 条目（哪怕已 resolved）」当成 blocked，会误导接手人。
    """
    if unresolved and not actionable:
        return "blocked"
    if not unresolved and not actionable and (resolved or closed):
        return "complete"
    return "continuable"


def _project_view(row: dict, entries: list[EntryView], handoff: HandoffView | None) -> ProjectView:
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry.kind] = counts.get(entry.kind, 0) + 1
    revision = (handoff.selected_revision or handoff.current_revision) if handoff else None
    return ProjectView.model_validate(
        {**row, "counts": counts, "last_handoff_revision": revision.revision if revision else None}
    )


@router.get("/restore", response_model=RestoreBrief)
async def restore_brief(
    project_id: str,
    request: Request,
    memory: MemoryService = Depends(get_memory),
) -> RestoreBrief:
    """新会话恢复：一次性取回交接、目标、决策、未解决问题、下一步与 PowerContext 打包上下文。"""
    row, scope_id = get_project(request, project_id)
    entries, handoff = await asyncio.gather(
        memory.list_entries(scope_id), memory.restore_handoff(scope_id)
    )
    grouped = _group(entries)
    goals = grouped.get("goal", [])
    unresolved, resolved = _split_questions(grouped.get("open_question", []))
    actionable_steps, closed_steps = _split_steps(grouped.get("next_step", []))

    query = ""
    if handoff.status == "resolved" and handoff.objective:
        query = handoff.objective
    elif goals and (goals[0].body or goals[0].title):
        query = (goals[0].body or goals[0].title)[:2000]
    else:
        query = row["name"]

    prepared = await memory.prepare_context(scope_id, query)
    return RestoreBrief(
        project=_project_view(row, entries, handoff),
        generated_at=_now(),
        handoff=handoff,
        prepared_context=prepared,
        goals=goals,
        decisions=grouped.get("decision", []),
        open_questions=unresolved,
        next_steps=actionable_steps,
        resolved_questions=resolved,
        closed_next_steps=closed_steps,
        todos_open=[item for item in grouped.get("todo", []) if item.status != "done"],
        recent_records=grouped.get("record", [])[:RECENT_RECORD_LIMIT],
        sources=grouped.get("source", []),
        entry_total=len(entries),
    )


@router.get("/handoff/draft", response_model=HandoffInput)
async def handoff_draft(
    project_id: str,
    request: Request,
    memory: MemoryService = Depends(get_memory),
) -> HandoffInput:
    """按当前记忆预填交接草稿；每条陈述都带上真实 citation，提交后即为 basis=verified。"""
    row, scope_id = get_project(request, project_id)
    entries = await memory.list_entries(scope_id)
    grouped = _group(entries)
    goals = grouped.get("goal", [])

    objective = ""
    if goals:
        objective = (goals[0].body or goals[0].title).strip()
    if not objective:
        objective = f"推进「{row['name']}」"

    state = [
        HandoffClaimInput(text=(item.title or item.body).strip()[:4000], citation=item.citation)
        for item in grouped.get("decision", [])[:20]
        if (item.title or item.body).strip()
    ]
    for item in grouped.get("record", [])[:5]:
        text = (item.title or item.body).strip()
        if text:
            state.append(HandoffClaimInput(text=text[:4000], citation=item.citation))
    if not state:
        state = [HandoffClaimInput(text=f"本期在「{row['name']}」上尚无已确认进展", citation=None)]

    next_steps = [item for item in grouped.get("next_step", []) if item.status not in {"done", "dropped"}]
    next_action = None
    if next_steps:
        first = next_steps[0]
        next_action = HandoffClaimInput(text=(first.title or first.body).strip()[:4000], citation=first.citation)

    questions = grouped.get("open_question", [])
    unresolved = [item for item in questions if item.status != "resolved"]
    resolved = [item for item in questions if item.status == "resolved"]
    closed_steps = [item for item in grouped.get("next_step", []) if item.status in {"done", "dropped"}]

    omissions = [
        (item.title or item.body).strip()[:4000]
        for item in unresolved[:20]
        if (item.title or item.body).strip()
    ]

    return HandoffInput(
        objective=objective[:4000],
        disposition=_draft_disposition(unresolved, next_steps, resolved, closed_steps),
        state=state[:64],
        next_action=next_action,
        omissions=omissions[:64],
    )


@router.post("/handoff", response_model=HandoffView)
async def save_handoff(
    project_id: str,
    payload: HandoffInput,
    request: Request,
    memory: MemoryService = Depends(get_memory),
) -> HandoffView:
    """结束工作：handoff_current_work → commit_handoff，产出不可变的交接 Revision。"""
    _, scope_id = get_project(request, project_id)
    view = await memory.save_handoff(scope_id, payload)
    get_registry(request).touch(project_id)
    return view


@router.post("/handoff/acknowledge", response_model=HandoffView)
async def acknowledge_handoff(
    project_id: str,
    payload: AcknowledgeInput,
    request: Request,
    memory: MemoryService = Depends(get_memory),
) -> HandoffView:
    """新会话正式接手：落一份持久的 handoff-receipt Source。

    请求必须带上调用方**实际核对过**的那个 Revision。旧实现忽略请求里的版本、
    直接对最新版落 receipt——用户核对的是 r1、回执却写着 r2，这是一处会误导人的不诚实。
    现在：先精确读回用户看过的版本证明它存在且属于本项目，再与最新版比对；
    不一致就 409 要求刷新，绝不悄悄换版本。
    """
    _, scope_id = get_project(request, project_id)
    if payload.revision is None:
        raise YanxuError(
            "接手请求必须带上你实际核对过的交接版本（revision）。研续不会替你猜，也不会悄悄换成最新版。",
            code="acknowledge_revision_required",
        )
    viewed = await memory.restore_handoff(scope_id, selection="exact", revision=payload.revision)
    if viewed.status != "resolved":
        raise YanxuError(
            f"Revision {payload.revision.revision} 不存在或不属于本项目。",
            code="handoff_not_found",
            status=404,
        )
    latest = await memory.restore_handoff(scope_id)
    latest_ref = latest.selected_revision or latest.current_revision
    if latest_ref is None:
        raise YanxuError("当前项目还没有可接手的交接记录。", code="handoff_not_found", status=404)
    if latest_ref.revision != payload.revision.revision:
        raise YanxuError(
            f"你核对的是 Revision {payload.revision.revision}，但本项目最新交接已是 Revision {latest_ref.revision}。"
            "请先刷新「当前交接状态」，基于最新版本重新核对后再接手。",
            code="handoff_revision_stale",
            status=409,
            details={
                "viewed": payload.revision.model_dump(mode="json"),
                "latest": latest_ref.model_dump(mode="json"),
            },
        )
    view = await memory.acknowledge_handoff(scope_id, payload, revision=payload.revision)
    get_registry(request).touch(project_id)
    return view


@router.get("/handoff", response_model=HandoffView)
async def current_handoff(
    project_id: str,
    request: Request,
    selection: str = "latest",
    revision: int | None = Query(default=None, ge=1, description="selection=exact 时要读取的交接 Revision"),
    memory: MemoryService = Depends(get_memory),
) -> HandoffView:
    """读取交接：默认最新版；selection=exact + revision 读取指定的历史 Revision。"""
    if selection not in {"latest", "exact"}:
        raise YanxuError("selection 只支持 latest 或 exact。", code="invalid_selection")
    ref: ArtifactRefView | None = None
    if selection == "exact":
        if revision is None:
            raise YanxuError("selection=exact 需要指定 revision。", code="handoff_revision_required")
        ref = ArtifactRefView(family=HANDOFF_FAMILY, artifact_id=HANDOFF_ARTIFACT_ID, revision=revision)
    _, scope_id = get_project(request, project_id)
    return await memory.restore_handoff(scope_id, selection=selection, revision=ref)


@router.post("/report", response_model=ReportView)
async def build_project_report(
    project_id: str,
    payload: ReportRequest,
    request: Request,
    memory: MemoryService = Depends(get_memory),
) -> ReportView:
    row, scope_id = get_project(request, project_id)
    entries = await memory.list_entries(scope_id)
    handoff = await memory.restore_handoff(scope_id)
    project = _project_view(row, entries, handoff)
    return build_report(
        project=project,
        entries=entries,
        handoff=handoff,
        report_type=payload.report_type,
        date_from=payload.date_from,
        date_to=payload.date_to,
        include_done_todos=payload.include_done_todos,
    )
