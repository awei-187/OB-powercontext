"""项目注册表：本地 SQLite 薄索引。

PowerContext 的 OpenAPI 没有「列出全部 Scope」接口，因此本地只保留
「项目 ↔ scope_id」的名册用于 UI 列表与解析。所有实质内容只存在于 PowerContext。
"""

from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .errors import YanxuError

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    project_id      TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    summary         TEXT NOT NULL DEFAULT '',
    scope_id        TEXT NOT NULL UNIQUE,
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    archived        INTEGER NOT NULL DEFAULT 0,
    sort_order      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_projects_updated ON projects(updated_at DESC);
"""

_COLUMNS = (
    "project_id",
    "name",
    "summary",
    "scope_id",
    "idempotency_key",
    "created_at",
    "updated_at",
    "archived",
    "sort_order",
)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def new_project_id() -> str:
    return f"prj_{uuid.uuid4().hex[:16]}"


class ProjectRegistry:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._connection = sqlite3.connect(str(self.path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        with self._lock, self._connection:
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA foreign_keys=ON")
            self._connection.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["archived"] = bool(item["archived"])
        return item

    def list_projects(self, *, include_archived: bool = True) -> list[dict[str, Any]]:
        sql = f"SELECT {', '.join(_COLUMNS)} FROM projects"
        if not include_archived:
            sql += " WHERE archived = 0"
        sql += " ORDER BY archived ASC, updated_at DESC, sort_order ASC"
        with self._lock:
            rows = self._connection.execute(sql).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get(self, project_id: str) -> dict[str, Any]:
        sql = f"SELECT {', '.join(_COLUMNS)} FROM projects WHERE project_id = ?"
        with self._lock:
            row = self._connection.execute(sql, (project_id,)).fetchone()
        if row is None:
            raise YanxuError(f"项目不存在：{project_id}", code="project_not_found", status=404)
        return self._row_to_dict(row)

    def insert(
        self,
        *,
        project_id: str,
        name: str,
        summary: str,
        scope_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        stamp = _now()
        with self._lock, self._connection:
            order = self._connection.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 FROM projects").fetchone()[0]
            self._connection.execute(
                "INSERT INTO projects (project_id, name, summary, scope_id, idempotency_key,"
                " created_at, updated_at, archived, sort_order) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)",
                (project_id, name, summary, scope_id, idempotency_key, stamp, stamp, order),
            )
        return self.get(project_id)

    def update(
        self,
        project_id: str,
        *,
        name: str | None = None,
        summary: str | None = None,
        archived: bool | None = None,
    ) -> dict[str, Any]:
        current = self.get(project_id)
        fields: dict[str, Any] = {}
        if name is not None:
            fields["name"] = name
        if summary is not None:
            fields["summary"] = summary
        if archived is not None:
            fields["archived"] = int(archived)
        if not fields:
            return current
        fields["updated_at"] = _now()
        assignment = ", ".join(f"{key} = ?" for key in fields)
        with self._lock, self._connection:
            self._connection.execute(
                f"UPDATE projects SET {assignment} WHERE project_id = ?",
                (*fields.values(), project_id),
            )
        return self.get(project_id)

    def touch(self, project_id: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE projects SET updated_at = ? WHERE project_id = ?", (_now(), project_id)
            )
