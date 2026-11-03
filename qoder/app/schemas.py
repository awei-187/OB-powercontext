"""研续 API 的 Pydantic 模型。"""

from __future__ import annotations

from datetime import date as date_type
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


def parse_iso_date(value: str, field_name: str) -> str:
    """只接受真实存在的 ISO 日历日期，并统一归一成 YYYY-MM-DD。

    区间过滤靠字符串字典序比较，前提是格式统一。Python 3.11 的 fromisoformat
    也接受 `20261102` 这种基本格式，可它与 `2026-11-07` 比较时字典序是错的
    （`20261102` > `2026-11-07`），会悄悄给出错误的区间结果，所以这里必须归一化。
    """
    text = (value or "").strip()
    if not text:
        return ""
    try:
        parsed = date_type.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field_name} 必须是 ISO 日期（YYYY-MM-DD），收到：{value!r}") from exc
    return parsed.isoformat()


class Kind(str, Enum):
    GOAL = "goal"
    RECORD = "record"
    DECISION = "decision"
    OPEN_QUESTION = "open_question"
    NEXT_STEP = "next_step"
    TODO = "todo"
    SOURCE = "source"


KIND_LABELS: dict[str, str] = {
    Kind.GOAL.value: "研究目标",
    Kind.RECORD.value: "工作记录",
    Kind.DECISION.value: "已确认决策",
    Kind.OPEN_QUESTION.value: "未解决问题",
    Kind.NEXT_STEP.value: "下一步",
    Kind.TODO.value: "待办",
    Kind.SOURCE.value: "资料出处",
}

STATUS_LABELS: dict[str, str] = {
    "": "未标注",
    "open": "进行中",
    "done": "已完成",
    "resolved": "已解决",
    "dropped": "已放弃",
    "blocked": "受阻",
    "confirmed": "已确认",
}

DISPOSITION_LABELS: dict[str, str] = {
    "continuable": "可继续",
    "blocked": "受阻",
    "complete": "已完成",
}


def kind_label(kind: str) -> str:
    return KIND_LABELS.get(kind, kind)


def status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)


class EntryInput(BaseModel):
    """一条记忆的录入表单。reason 映射到 PowerContext 的变更原因。"""

    kind: Kind
    title: str = Field(default="", max_length=300)
    body: str = Field(default="", max_length=20000)
    date: str = Field(default="", max_length=32)
    status: str = Field(default="", max_length=32)
    tags: list[str] = Field(default_factory=list, max_length=32)
    url: str = Field(default="", max_length=2000)
    refs: list[str] = Field(default_factory=list, max_length=32)
    reason: str = Field(default="", max_length=500)

    @field_validator("date")
    @classmethod
    def _date_is_iso(cls, value: str) -> str:
        return parse_iso_date(value, "date")


class ArtifactRefView(BaseModel):
    """对应 PowerContext ArtifactReference。"""

    family: str
    artifact_id: str
    revision: int


class CitationView(BaseModel):
    """对应 PowerContext MemoryCitation，字段结构与官方模型一致，可直接回传。"""

    memory_ref: ArtifactRefView
    entry_id: str
    entry_version_id: str


class EntryRevision(BaseModel):
    """修订一条记忆：必须带上当前 citation，冲突时 PowerContext 会返回 409。"""

    citation: CitationView
    patch: EntryInput
    reason: str = Field(default="", max_length=500)


class EntryView(BaseModel):
    kind: str
    kind_label: str
    title: str
    body: str
    date: str
    status: str
    status_label: str
    tags: list[str]
    url: str
    url_href: str = ""
    refs: list[str]
    text: str
    byte_length: int
    state: str
    version: int
    citation: CitationView
    ref_label: str = ""
    reason: str = ""
    change_ops: list[str] = Field(default_factory=list)


class SearchHitView(BaseModel):
    entry: EntryView
    score: float
    matched_by: list[str]


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    summary: str = Field(default="", max_length=1000)
    goal: str = Field(default="", max_length=4000)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    summary: str | None = Field(default=None, max_length=1000)
    archived: bool | None = None


class ProjectView(BaseModel):
    project_id: str
    name: str
    summary: str
    scope_id: str
    created_at: str
    updated_at: str
    archived: bool
    counts: dict[str, int] = Field(default_factory=dict)
    last_handoff_revision: int | None = None


class HandoffClaimInput(BaseModel):
    """交接里的一条陈述。带上 citation 即以 basis=verified 提交真实记忆引用。"""

    text: str = Field(min_length=1, max_length=4000)
    citation: CitationView | None = None


class HandoffInput(BaseModel):
    objective: str = Field(min_length=1, max_length=4000)
    disposition: Literal["continuable", "blocked", "complete"] = "continuable"
    state: list[HandoffClaimInput] = Field(default_factory=list, max_length=64)
    next_action: HandoffClaimInput | None = None
    omissions: list[str] = Field(default_factory=list, max_length=64)


class AcknowledgeInput(BaseModel):
    """新会话接手。

    revision 必须是调用方**真正看到并核对过**的那个交接 Revision：后端据此精确接手，
    并在它已经不是最新版时返回 409 要求刷新，绝不悄悄换成最新版。
    三个 checked 字段与 PowerContext ReceiverChecks 的三个字段一一对应。
    """

    status: Literal["accepted", "needs_clarification", "declined"] = "accepted"
    revision: ArtifactRefView | None = None
    live_state_checked: bool = False
    capability_checked: bool = False
    authorization_checked: bool = False
    message: str = Field(default="", max_length=1000)


class HandoffCitationView(BaseModel):
    kind: str
    summary: str


class HandoffStatementView(BaseModel):
    text: str
    citations: list[HandoffCitationView] = Field(default_factory=list)


class EvidenceCheckView(BaseModel):
    claim: str
    state_index: int | None
    status: str
    unavailable_evidence: list[HandoffCitationView] = Field(default_factory=list)


class HandoffView(BaseModel):
    status: str
    trust: str = ""
    disposition: str = ""
    disposition_label: str = ""
    objective: str = ""
    state: list[HandoffStatementView] = Field(default_factory=list)
    next_action: HandoffStatementView | None = None
    omissions: list[str] = Field(default_factory=list)
    evidence_checks: list[EvidenceCheckView] = Field(default_factory=list)
    selected_revision: ArtifactRefView | None = None
    current_revision: ArtifactRefView | None = None
    boundary_source_id: str = ""
    receipt_source_id: str = ""


class PreparedContextView(BaseModel):
    status: str
    content: str = ""
    content_bytes: int = 0
    query: str = ""


class RestoreBrief(BaseModel):
    project: ProjectView
    generated_at: str
    handoff: HandoffView | None
    prepared_context: PreparedContextView | None
    goals: list[EntryView] = Field(default_factory=list)
    decisions: list[EntryView] = Field(default_factory=list)
    open_questions: list[EntryView] = Field(default_factory=list)
    next_steps: list[EntryView] = Field(default_factory=list)
    resolved_questions: list[EntryView] = Field(default_factory=list)
    closed_next_steps: list[EntryView] = Field(default_factory=list)
    todos_open: list[EntryView] = Field(default_factory=list)
    recent_records: list[EntryView] = Field(default_factory=list)
    sources: list[EntryView] = Field(default_factory=list)
    entry_total: int = 0


class ChangeView(BaseModel):
    revision: int
    op: str
    entry_id: str
    from_entry_version_id: str = ""
    to_entry_version_id: str = ""
    reason: str = ""
    kind: str = ""
    title: str = ""
    text: str = ""


class UnavailableSnapshot(BaseModel):
    """某个历史版本当前读不回来。如实列出，绝不静默丢掉。"""

    entry_version_id: str
    revision: int
    op: str
    error: str


class EntryHistoryView(BaseModel):
    entry_id: str
    kind: str
    kind_label: str
    current: EntryView | None
    snapshots: list[EntryView] = Field(default_factory=list)
    unavailable: list[UnavailableSnapshot] = Field(default_factory=list)
    changes: list[ChangeView] = Field(default_factory=list)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=10, ge=1, le=50)
    mode: Literal["fts", "auto"] = "fts"


class ReportRequest(BaseModel):
    report_type: Literal["weekly", "group"] = "weekly"
    date_from: str = ""
    date_to: str = ""
    include_done_todos: bool = True

    @field_validator("date_from")
    @classmethod
    def _from_is_iso(cls, value: str) -> str:
        return parse_iso_date(value, "date_from")

    @field_validator("date_to")
    @classmethod
    def _to_is_iso(cls, value: str) -> str:
        return parse_iso_date(value, "date_to")

    @model_validator(mode="after")
    def _range_not_reversed(self) -> "ReportRequest":
        # 起止倒置的区间不会命中任何记录，却会产出一份看起来正常的空报告；
        # 这是调用方的错误，必须当场拒掉而不是悄悄返回 200。
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError(f"date_from（{self.date_from}）不能晚于 date_to（{self.date_to}）。")
        return self


class ReportView(BaseModel):
    markdown: str
    report_type: str
    title: str
    date_from: str
    date_to: str
    citation_count: int
    source_count: int


class SystemStatus(BaseModel):
    app: str
    version: str
    powercontext_base_url: str
    powercontext_running: bool
    powercontext_version: str
    storage_backend: str
    database_path: str
    registry_path: str
    capabilities: dict[str, Any] = Field(default_factory=dict)
    model_keys_configured: bool
    notes: list[str] = Field(default_factory=list)
