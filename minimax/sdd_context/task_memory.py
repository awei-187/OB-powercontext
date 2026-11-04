"""Task progress persisted through official PowerContext Memory APIs."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator
from powercontext.builtin.artifacts.memory.models import MemoryEntryInput
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime.composition import open_builtin_runtime
from powercontext.builtin.runtime.config import BuiltinConfig
from powercontext.builtin.scope.models import ScopeDraft
from powercontext.builtin.runtime.models import (
    GetMemoryEntryRequest, RememberMemoryRequest, ReviseMemoryEntryRequest,
)

POWERCONTEXT_COMMIT = "9db1753434162c0aa7c9f1189a1722e617880a52"


class ValidationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    command: list[str] = Field(min_length=1)
    exit_code: int
    log_path: str = Field(min_length=1)
    log_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class TaskState(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    task_id: str = Field(min_length=1, max_length=128)
    objective: str = Field(min_length=1)
    completed: list[str] = Field(default_factory=list)
    pending: list[str] = Field(default_factory=list)
    validations: list[ValidationRecord] = Field(default_factory=list)

    @field_validator("task_id", "objective")
    @classmethod
    def nonblank(cls, value):
        if value.strip() != value or not value:
            raise ValueError("Task identity and objective must not be blank or padded")
        return value


def scope_key(project: str, task_id: str) -> str:
    identity = json.dumps([project, task_id], separators=(",", ":"), ensure_ascii=False)
    return "minimax-task-" + hashlib.sha256(identity.encode()).hexdigest()


@asynccontextmanager
async def task_runtime(directory: Path):
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    config = BuiltinConfig(database=SQLiteConfig(
        url="sqlite+aiosqlite:///" + str(directory / "memory.db")))
    async with open_builtin_runtime(config, scheduler_path=directory / "scheduler.db") as runtime:
        yield runtime


def decode_record(record, project, task_id, registered_scope):
    payload = json.loads(record.entry.text)
    if (payload.get("schema") != "minimax.task-state.v1"
            or payload.get("project_id") != project
            or payload.get("state", {}).get("task_id") != task_id):
        raise ValueError("PowerContext task state identity/schema mismatch")
    state = TaskState.model_validate(payload["state"])
    return {
        "backend": "powercontext-memory-sqlite",
        "powercontext_commit": POWERCONTEXT_COMMIT,
        "scope_id": registered_scope,
        "citation": record.citation.model_dump(mode="json"),
        "saved_at_utc": payload["saved_at_utc"],
        "state": state.model_dump(mode="json"),
        "trust": "Historical progress; verify against current specifications, code and test results.",
    }


async def current_record(memory):
    page = await memory.list()
    if len(page.entries) > 1:
        raise ValueError("Task scope contains multiple active state entries")
    return page.entries[0] if page.entries else None


async def memory_for_task(runtime, project, task_id):
    # PowerContext owns scope IDs; a stable creation key resolves the same scope on restart.
    scope = await runtime.scopes.create(ScopeDraft(
        title="MiniMax task progress", summary="Explicit application task checkpoint",
        idempotency_key=scope_key(project, task_id)))
    return runtime.memory.for_scope(scope.scope_id)


async def save_state(directory: Path, project: str, state: TaskState):
    payload = {"schema": "minimax.task-state.v1", "project_id": project,
               "saved_at_utc": datetime.now(timezone.utc).isoformat(),
               "state": state.model_dump(mode="json")}
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(text.encode()) > 8192:
        raise ValueError("Task state exceeds PowerContext's 8192-byte Memory entry limit")
    async with task_runtime(directory) as runtime:
        memory = await memory_for_task(runtime, project, state.task_id)
        existing = await current_record(memory)
        if existing:
            decode_record(existing, project, state.task_id, memory.scope_id)
            result = await memory.revise(ReviseMemoryEntryRequest(
                citation=existing.citation, kind="working_note", text=text,
                reason="Explicit task progress checkpoint"))
        else:
            result = await memory.remember(RememberMemoryRequest(entries=(MemoryEntryInput(
                kind="working_note", text=text, reason="Explicit task progress checkpoint"),)))
        if result.entry is None:
            raise ValueError("PowerContext returned no saved state entry")
        # Read through the exact public citation before reporting success.
        record = await memory.get(GetMemoryEntryRequest(citation=result.entry.citation))
        return decode_record(record, project, state.task_id, memory.scope_id)


async def load_state(directory: Path, project: str, task_id: str):
    if not task_id or task_id.strip() != task_id or len(task_id) > 128:
        raise ValueError("Invalid task_id")
    async with task_runtime(directory) as runtime:
        memory = await memory_for_task(runtime, project, task_id)
        record = await current_record(memory)
        if record is None:
            return None
        exact = await memory.get(GetMemoryEntryRequest(citation=record.citation))
        return decode_record(exact, project, task_id, memory.scope_id)
