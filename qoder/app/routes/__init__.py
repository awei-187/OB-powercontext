"""路由包。"""

from __future__ import annotations

from fastapi import APIRouter

from . import entries, handoff, projects, system

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(projects.router)
api_router.include_router(entries.router)
api_router.include_router(handoff.router)

__all__ = ["api_router", "entries", "handoff", "projects", "system"]
