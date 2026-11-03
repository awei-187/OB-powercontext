"""研续 Yanxu · FastAPI 入口。

启动时在同一进程内拉起一个回环 PowerContext Server（官方 _tutorial.py 模式），
退出时干净关闭。所有业务数据只存在于 PowerContext 的 SQLite 中。
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from powercontext.client import PowerContextClient
from powercontext.errors import PowerContextError

from . import config
from .errors import (
    YanxuError,
    client_error_handler,
    validation_error_handler,
    yanxu_error_handler,
)
from .memory import MemoryService
from .pc_host import PowerContextHost
from .registry import ProjectRegistry
from .routes import api_router

STATIC_DIR = Path(__file__).resolve().parent / "static"
logger = logging.getLogger("yanxu")

APP_TITLE = "研续 Yanxu · 科研与项目工作连续性助手"
APP_VERSION = "0.1.0"


def create_app(*, data_dir: Path | str | None = None) -> FastAPI:
    paths = config.resolve_paths(data_dir)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        paths.ensure()
        host = PowerContextHost(
            workspace=paths.powercontext_workspace,
            database_path=paths.powercontext_db,
            scheduler_path=paths.powercontext_scheduler,
            start_timeout=config.POWERCONTEXT_START_TIMEOUT,
        )
        base_url = await host.start()
        logger.info("内嵌 PowerContext Server 已就绪: %s", base_url)

        client = PowerContextClient(base_url, timeout=config.POWERCONTEXT_CLIENT_TIMEOUT)
        registry = ProjectRegistry(paths.registry_db)

        app.state.paths = paths
        app.state.host = host
        app.state.client = client
        app.state.memory = MemoryService(client)
        app.state.registry = registry
        try:
            yield
        finally:
            await client.aclose()
            await host.stop()
            registry.close()
            logger.info("PowerContext Server 已停止")

    app = FastAPI(
        title=APP_TITLE,
        version=APP_VERSION,
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.add_exception_handler(YanxuError, yanxu_error_handler)
    app.add_exception_handler(PowerContextError, client_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.include_router(api_router)
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


app = create_app()


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    print(f"研续 Yanxu → http://{config.APP_HOST}:{config.APP_PORT}")
    print(f"数据目录   → {config.resolve_paths().data}")
    print("PowerContext 记忆为唯一数据真源；本工具不需要任何模型密钥。")
    uvicorn.run(app, host=config.APP_HOST, port=config.APP_PORT, log_level="info")


if __name__ == "__main__":
    main()
