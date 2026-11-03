"""研续 Yanxu · 配置。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

QODER_ROOT = Path(__file__).resolve().parent.parent

APP_HOST = os.environ.get("YANXU_HOST", "127.0.0.1")
APP_PORT = int(os.environ.get("YANXU_PORT", "8000"))

POWERCONTEXT_CLIENT_TIMEOUT = float(os.environ.get("YANXU_PC_TIMEOUT", "120"))
POWERCONTEXT_START_TIMEOUT = float(os.environ.get("YANXU_PC_START_TIMEOUT", "60"))

# PowerContext 对 memory text 的硬限制：NFC 归一化后不超过 8192 UTF-8 字节。
# 研续不提前拒绝，真实限制由 Server 校验并返回 422；此常量仅用于前端提示。
MEMORY_TEXT_BYTE_LIMIT = 8192


@dataclass(frozen=True)
class Paths:
    data: Path
    powercontext_db: Path
    powercontext_workspace: Path
    powercontext_scheduler: Path
    registry_db: Path

    def ensure(self) -> None:
        for path in (self.data, self.powercontext_workspace, self.powercontext_db.parent):
            Path(path).mkdir(parents=True, exist_ok=True)


def resolve_paths(data_dir: Path | str | None = None) -> Paths:
    root = Path(data_dir) if data_dir else Path(os.environ.get("YANXU_DATA_DIR") or QODER_ROOT / "data")
    powercontext_dir = root / "powercontext"
    return Paths(
        data=root,
        powercontext_db=powercontext_dir / "powercontext.db",
        powercontext_workspace=powercontext_dir / "workspace",
        powercontext_scheduler=powercontext_dir / "scheduler.db",
        registry_db=root / "registry.db",
    )


DEFAULT_PATHS = resolve_paths()
