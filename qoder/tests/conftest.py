"""pytest 共享夹具。所有测试都打真实的内嵌 PowerContext Server，不做任何 mock。"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from app.main import create_app  # noqa: E402


@asynccontextmanager
async def yanxu_client(data_dir: Path) -> AsyncIterator[tuple[object, httpx.AsyncClient]]:
    """在临时数据目录里启动研续（含真实内嵌 PowerContext Server），返回 (app, client)。"""
    app = create_app(data_dir=data_dir)
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://yanxu.test", timeout=180.0
        ) as client:
            yield app, client


async def create_project(client: httpx.AsyncClient, name: str, goal: str = "") -> dict:
    response = await client.post(
        "/api/projects", json={"name": name, "summary": f"{name} 的测试项目", "goal": goal}
    )
    assert response.status_code == 201, response.text
    return response.json()
