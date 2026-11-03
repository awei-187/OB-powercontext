"""路由共享依赖。"""

from __future__ import annotations

from fastapi import Request

from .memory import MemoryService
from .registry import ProjectRegistry


def get_registry(request: Request) -> ProjectRegistry:
    return request.app.state.registry


def get_memory(request: Request) -> MemoryService:
    service: MemoryService | None = getattr(request.app.state, "memory", None)
    if service is None:
        from .errors import YanxuError

        raise YanxuError(
            "PowerContext 记忆层尚未就绪，请查看启动日志。",
            code="powercontext_not_ready",
            status=503,
        )
    return service


def get_project(request: Request, project_id: str) -> tuple[dict, str]:
    """返回 (项目注册表记录, scope_id)。"""
    project = get_registry(request).get(project_id)
    return project, project["scope_id"]
