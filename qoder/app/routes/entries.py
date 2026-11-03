"""记忆条目路由：录入、修订、退役、历史、检索。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from ..deps import get_memory, get_project, get_registry
from ..errors import YanxuError
from ..memory import MemoryService
from ..schemas import (
    CitationView,
    EntryHistoryView,
    EntryInput,
    EntryRevision,
    EntryView,
    SearchHitView,
    SearchRequest,
)

router = APIRouter(prefix="/api/projects/{project_id}", tags=["entries"])


class RetireRequest(BaseModel):
    citation: CitationView
    reason: str = Field(default="", max_length=500)


def _require_match(path_entry_id: str, citation: CitationView) -> None:
    if citation.entry_id != path_entry_id:
        raise YanxuError(
            f"路径中的 entry_id（{path_entry_id}）与提交的 citation（{citation.entry_id}）不一致。",
            code="citation_mismatch",
        )


@router.get("/entries", response_model=list[EntryView])
async def list_entries(
    project_id: str,
    request: Request,
    kind: str = "",
    include_inactive: bool = False,
    date_from: str = "",
    date_to: str = "",
    memory: MemoryService = Depends(get_memory),
) -> list[EntryView]:
    _, scope_id = get_project(request, project_id)
    entries = await memory.list_entries(scope_id, include_inactive=include_inactive)
    if kind:
        entries = [entry for entry in entries if entry.kind == kind]
    if date_from:
        entries = [entry for entry in entries if not entry.date or entry.date >= date_from]
    if date_to:
        entries = [entry for entry in entries if not entry.date or entry.date <= date_to]
    return entries


@router.post("/entries", response_model=EntryView, status_code=201)
async def add_entry(
    project_id: str,
    payload: EntryInput,
    request: Request,
    memory: MemoryService = Depends(get_memory),
) -> EntryView:
    _, scope_id = get_project(request, project_id)
    entry = await memory.add_entry(scope_id, payload)
    get_registry(request).touch(project_id)
    return entry


@router.patch("/entries/{entry_id}", response_model=EntryView)
async def revise_entry(
    project_id: str,
    entry_id: str,
    payload: EntryRevision,
    request: Request,
    memory: MemoryService = Depends(get_memory),
) -> EntryView:
    _, scope_id = get_project(request, project_id)
    _require_match(entry_id, payload.citation)
    entry = await memory.revise_entry(scope_id, payload.citation, payload.patch, payload.reason)
    get_registry(request).touch(project_id)
    return entry


@router.post("/entries/{entry_id}/retire", response_model=EntryView | None)
async def retire_entry(
    project_id: str,
    entry_id: str,
    payload: RetireRequest,
    request: Request,
    memory: MemoryService = Depends(get_memory),
) -> EntryView | None:
    """PowerContext 没有物理删除；retire 后条目变为 inactive，历史完整保留。"""
    _, scope_id = get_project(request, project_id)
    _require_match(entry_id, payload.citation)
    entry = await memory.retire_entry(scope_id, payload.citation, payload.reason)
    get_registry(request).touch(project_id)
    return entry


@router.post("/entries/{entry_id}/reactivate", response_model=EntryView)
async def reactivate_entry(
    project_id: str,
    entry_id: str,
    payload: RetireRequest,
    request: Request,
    memory: MemoryService = Depends(get_memory),
) -> EntryView:
    """重新激活 = 以当前 inactive 快照的 citation 修订一次，内容不变。"""
    _, scope_id = get_project(request, project_id)
    _require_match(entry_id, payload.citation)
    current = await memory.get_entry(scope_id, payload.citation)
    patch = EntryInput(
        kind=current.kind,
        title=current.title,
        body=current.body,
        date=current.date,
        status=current.status,
        tags=current.tags,
        url=current.url,
        refs=current.refs,
    )
    entry = await memory.revise_entry(scope_id, payload.citation, patch, payload.reason or "恢复该记忆")
    get_registry(request).touch(project_id)
    return entry


@router.get("/entries/{entry_id}/history", response_model=EntryHistoryView)
async def entry_history(
    project_id: str,
    entry_id: str,
    request: Request,
    memory: MemoryService = Depends(get_memory),
) -> EntryHistoryView:
    _, scope_id = get_project(request, project_id)
    return await memory.entry_history(scope_id, entry_id)


@router.post("/search", response_model=list[SearchHitView])
async def search_entries(
    project_id: str,
    payload: SearchRequest,
    request: Request,
    memory: MemoryService = Depends(get_memory),
) -> list[SearchHitView]:
    _, scope_id = get_project(request, project_id)
    return await memory.search(scope_id, payload.query, limit=payload.limit, mode=payload.mode)
