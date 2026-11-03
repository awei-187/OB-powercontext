"""内嵌 PowerContext Server。

沿用官方 examples/jupyter/_tutorial.py 的既有模式：create_server_app + 自选空闲回环端口 +
uvicorn.Server 跑在 daemon 线程。不复制、不改写 PowerContext 源码。

InferenceConfig() 全字段为 None ⇒ 不配置任何 generation / embedding / rerank 模型，
显式记忆与 FTS 检索即可工作，符合「零额外模型密钥」的产品定位。
"""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from pathlib import Path

import uvicorn
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime.config import ExternalSkillsConfig, InferenceConfig, RuntimeConfig
from powercontext.server.factory import create_server_app
from powercontext.server.settings import (
    AccessControlConfig,
    BearerAuthConfig,
    HttpConfig,
    McpConfig,
    MetricsConfig,
    ServerSettings,
    TracingConfig,
)


class HostStartError(RuntimeError):
    """内嵌 Server 未能在超时内就绪。"""


class PowerContextHost:
    """在后台线程里持有一个回环 PowerContext Server。"""

    def __init__(
        self,
        *,
        workspace: Path,
        database_path: Path,
        scheduler_path: Path,
        start_timeout: float = 60.0,
    ) -> None:
        self.workspace = Path(workspace)
        self.database_path = Path(database_path)
        self.scheduler_path = Path(scheduler_path)
        self.start_timeout = start_timeout
        self.base_url = ""
        self.database_kind = "sqlite"
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self._listener: socket.socket | None = None

    def _build_app(self) -> object:
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        database = SQLiteConfig(url=f"sqlite+aiosqlite:///{self.database_path.as_posix()}")
        self.database_kind = database.kind
        settings = ServerSettings(
            workspace=self.workspace,
            database=database,
            http=HttpConfig(host="127.0.0.1"),
            auth=BearerAuthConfig(enabled=False),
            access=AccessControlConfig(mode="disabled"),
            inference=InferenceConfig(),
            runtime=RuntimeConfig(schedule_seconds=None, experience_schedule_seconds=None),
            external_skills=ExternalSkillsConfig(),
            mcp=McpConfig(enabled=False),
            metrics=MetricsConfig(enabled=False),
            tracing=TracingConfig(enabled=False),
        )
        return create_server_app(settings=settings, scheduler_path=self.scheduler_path)

    def _start_sync(self) -> None:
        app = self._build_app()
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        self._listener = listener
        self.base_url = f"http://127.0.0.1:{listener.getsockname()[1]}"
        server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False, lifespan="on"))
        self._server = server
        self._thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        self._thread.start()

        deadline = time.monotonic() + self.start_timeout
        while self._thread.is_alive() and not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        if not server.started:
            detail = "" if self._thread.is_alive() else "（后台线程已退出，请查看启动日志）"
            self._stop_sync()
            raise HostStartError(f"内嵌 PowerContext Server 启动失败{detail}")

    def _stop_sync(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=15)
        if self._listener is not None:
            self._listener.close()
        self._server = None
        self._thread = None
        self._listener = None

    async def start(self) -> str:
        if self._thread is not None:
            return self.base_url
        await asyncio.to_thread(self._start_sync)
        return self.base_url

    async def stop(self) -> None:
        await asyncio.to_thread(self._stop_sync)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()
