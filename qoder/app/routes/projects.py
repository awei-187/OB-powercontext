"""项目路由：一个项目 = 一个 PowerContext Scope。"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request

from .. import codec, config
from ..deps import get_memory, get_project, get_registry
from ..errors import YanxuError
from ..memory import MemoryService
from ..registry import ProjectRegistry, new_project_id
from ..schemas import EntryInput, EntryView, Kind, ProjectCreate, ProjectUpdate, ProjectView

router = APIRouter(prefix="/api/projects", tags=["projects"])

KIND_ORDER = (
    Kind.GOAL.value,
    Kind.RECORD.value,
    Kind.DECISION.value,
    Kind.OPEN_QUESTION.value,
    Kind.NEXT_STEP.value,
    Kind.TODO.value,
    Kind.SOURCE.value,
)


def _counts(entries: list[EntryView]) -> dict[str, int]:
    result = {kind: 0 for kind in KIND_ORDER}
    for entry in entries:
        if entry.state == "active":
            result[entry.kind] = result.get(entry.kind, 0) + 1
    return result


async def _decorate(memory: MemoryService, row: dict, *, with_state: bool) -> ProjectView:
    view = ProjectView.model_validate({**row, "counts": {}})
    if not with_state:
        return view
    entries, handoff = await asyncio.gather(
        memory.list_entries(row["scope_id"]),
        memory.restore_handoff(row["scope_id"]),
    )
    view.counts = _counts(entries)
    revision = handoff.selected_revision or handoff.current_revision
    view.last_handoff_revision = revision.revision if revision else None
    return view


@router.get("", response_model=list[ProjectView])
async def list_projects(
    request: Request,
    include_archived: bool = True,
    registry: ProjectRegistry = Depends(get_registry),
    memory: MemoryService = Depends(get_memory),
) -> list[ProjectView]:
    rows = registry.list_projects(include_archived=include_archived)
    return list(await asyncio.gather(*[_decorate(memory, row, with_state=True) for row in rows]))


@router.post("", response_model=ProjectView, status_code=201)
async def create_project(
    payload: ProjectCreate,
    request: Request,
    registry: ProjectRegistry = Depends(get_registry),
    memory: MemoryService = Depends(get_memory),
) -> ProjectView:
    name = payload.name.strip()
    if not name:
        raise YanxuError("项目名称不能为空。", code="project_name_required")

    goal_text = payload.goal.strip()
    if goal_text:
        # 先按研续的 YX1 编码算真实 UTF-8 字节数：超限必须在创建 Scope 之前拒掉。
        # 否则 Scope 与注册表记录已建、目标记忆写入被 422 打回，就留下半成品项目。
        encoded = codec.encode(title="研究目标", status="confirmed", body=goal_text)
        byte_length = codec.byte_length(encoded)
        if byte_length > config.MEMORY_TEXT_BYTE_LIMIT:
            raise YanxuError(
                f"研究目标编码后为 {byte_length} UTF-8 字节，超过 PowerContext 单条记忆"
                f" {config.MEMORY_TEXT_BYTE_LIMIT} 字节上限。请精简目标，或先创建项目再分条录入。",
                code="goal_too_long",
                details={"byte_length": byte_length, "limit": config.MEMORY_TEXT_BYTE_LIMIT},
                hint="中文每字约 3 字节；4000 字的目标必然超限。",
            )

    project_id = new_project_id()
    # idempotency_key 绑定本次请求生成的 project_id：它只防止同一次创建在服务端被重复执行
    # 时造出两个 Scope。用户重试是一次全新的 POST（新的 project_id、新的 Scope），
    # 因此这里不提供跨请求幂等——下面的写入顺序才是「不留半成品」的保证。
    scope_id = await memory.create_scope(
        title=name, summary=payload.summary.strip() or name, idempotency_key=f"yanxu:{project_id}"
    )

    if goal_text:
        # 目标写入失败时注册表里不会有这个项目：用户看到的是干净的失败，重试即全新创建。
        # 代价是 PowerContext 里可能留下一个没有注册表记录的孤儿 Scope——它没有 list 入口、
        # 不会出现在任何项目列表里，也不会被误当成可用项目。
        await memory.add_entry(
            scope_id,
            EntryInput(kind=Kind.GOAL, title="研究目标", body=goal_text, status="confirmed", reason="创建项目时录入"),
        )

    row = registry.insert(
        project_id=project_id,
        name=name,
        summary=payload.summary.strip(),
        scope_id=scope_id,
        idempotency_key=f"yanxu:{project_id}",
    )
    return await _decorate(memory, row, with_state=True)


@router.get("/{project_id}", response_model=ProjectView)
async def get_project_detail(
    project_id: str,
    request: Request,
    registry: ProjectRegistry = Depends(get_registry),
    memory: MemoryService = Depends(get_memory),
) -> ProjectView:
    return await _decorate(memory, registry.get(project_id), with_state=True)


@router.patch("/{project_id}", response_model=ProjectView)
async def update_project(
    project_id: str,
    payload: ProjectUpdate,
    registry: ProjectRegistry = Depends(get_registry),
) -> ProjectView:
    name = payload.name.strip() if payload.name is not None else None
    if name is not None and not name:
        raise YanxuError("项目名称不能为空。", code="project_name_required")
    row = registry.update(
        project_id,
        name=name,
        summary=payload.summary.strip() if payload.summary is not None else None,
        archived=payload.archived,
    )
    return ProjectView.model_validate({**row, "counts": {}})


@router.get("/{project_id}/changes")
async def list_changes(
    project_id: str,
    request: Request,
    since_revision: int = 0,
    memory: MemoryService = Depends(get_memory),
) -> dict:
    _, scope_id = get_project(request, project_id)
    changes = await memory.raw_changes(scope_id, since_revision=since_revision)
    return {"project_id": project_id, "scope_id": scope_id, "since_revision": since_revision, "changes": changes}
