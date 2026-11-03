"""系统状态路由：真实反映 PowerContext 连接与能力。"""

from __future__ import annotations

import importlib.metadata
from typing import Any

from fastapi import APIRouter, Depends, Request

from .. import config
from ..deps import get_memory
from ..memory import MemoryService
from ..schemas import DISPOSITION_LABELS, KIND_LABELS, STATUS_LABELS, SystemStatus

router = APIRouter(prefix="/api/system", tags=["system"])

APP_NAME = "研续 Yanxu"
APP_VERSION = "0.1.0"


@router.get("/status", response_model=SystemStatus)
async def system_status(request: Request, memory: MemoryService = Depends(get_memory)) -> SystemStatus:
    host = request.app.state.host
    capabilities: dict[str, Any] = await memory.capabilities()
    search_modes = [str(item) for item in capabilities.get("search_modes", [])]
    notes: list[str] = []
    if not capabilities.get("memory_extraction"):
        notes.append("未配置生成模型：自动记忆提取不可用，研续只使用显式记忆（这是预期行为）。")
    if "vector" not in search_modes and "hybrid" not in search_modes:
        notes.append(f"未配置 embedding 模型：可用检索方式为 {', '.join(search_modes) or '无'}，研续固定使用 fts。")
    if not capabilities.get("handoff_generation"):
        notes.append("交接由本人撰写（handoff_current_work + commit_handoff），不依赖生成模型。")

    try:
        pc_version = importlib.metadata.version("powercontext")
    except importlib.metadata.PackageNotFoundError:  # pragma: no cover
        pc_version = "unknown"

    return SystemStatus(
        app=APP_NAME,
        version=APP_VERSION,
        powercontext_base_url=host.base_url,
        powercontext_running=host.running,
        powercontext_version=pc_version,
        storage_backend=host.database_kind,
        database_path=str(request.app.state.paths.powercontext_db),
        registry_path=str(request.app.state.paths.registry_db),
        capabilities=capabilities,
        model_keys_configured=bool(capabilities.get("memory_extraction")),
        notes=notes,
    )


@router.get("/meta")
async def system_meta() -> dict[str, Any]:
    return {
        "app": APP_NAME,
        "version": APP_VERSION,
        "kinds": [{"value": key, "label": label} for key, label in KIND_LABELS.items()],
        "statuses": [{"value": key, "label": label} for key, label in STATUS_LABELS.items()],
        "dispositions": [{"value": key, "label": label} for key, label in DISPOSITION_LABELS.items()],
        "memory_text_byte_limit": config.MEMORY_TEXT_BYTE_LIMIT,
    }
