"""PowerContext 记忆层：所有业务内容的唯一真源。

只调用官方 powercontext==1.2.0 的公开 SDK / HTTP API，不 mock、不本地兜底、不改写其源码。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from powercontext.client import PowerContextClient, ServerResponseError
from powercontext.http import (
    AcknowledgeHandoffRequest,
    CommitHandoffRequest,
    ContinueHandoffRequest,
    CreateScopeRequest,
    GetMemoryEntryRequest,
    HandoffCitation,
    HandoffCurrentWorkRequest,
    ListMemoryChangesRequest,
    ListMemoryEntriesRequest,
    MemoryCitation,
    PrepareContextRequest,
    ReceiverChecks,
    RememberMemoryRequest,
    RetireMemoryEntryRequest,
    ReviseMemoryEntryRequest,
    SearchMemoryRequest,
    WorkClaim,
)

from . import codec
from .errors import YanxuError
from .schemas import (
    AcknowledgeInput,
    ArtifactRefView,
    ChangeView,
    CitationView,
    EntryHistoryView,
    EntryInput,
    EntryView,
    EvidenceCheckView,
    HandoffClaimInput,
    HandoffCitationView,
    HandoffInput,
    HandoffStatementView,
    HandoffView,
    PreparedContextView,
    SearchHitView,
    UnavailableSnapshot,
    kind_label,
    status_label,
)

CURRENT_WORK_HANDOFF_SCHEMA = "powercontext.current-work-handoff.v1"
DEFAULT_CONTEXT_BYTES = 8000
HANDOFF_FAMILY = "handoff"
HANDOFF_ARTIFACT_ID = "handoff"


def require_handoff_ref(revision: ArtifactRefView) -> ArtifactRefView:
    """精确读取 / 接手交接之前的引用自检。

    PowerContext 客户端对 revision < 1 会直接抛 pydantic ValidationError（在研续侧变成 500），
    族 / 工件名不符则换来一条语焉不详的 422；两者都是调用方的错，应当 400 说清楚。
    """
    if revision.revision < 1:
        raise YanxuError(f"交接版本号必须 ≥ 1，收到 {revision.revision}。", code="invalid_handoff_revision")
    if (revision.family, revision.artifact_id) != (HANDOFF_FAMILY, HANDOFF_ARTIFACT_ID):
        raise YanxuError(
            f"交接工件引用必须是 {HANDOFF_FAMILY}/{HANDOFF_ARTIFACT_ID}，"
            f"收到 {revision.family}/{revision.artifact_id}。",
            code="invalid_handoff_revision",
        )
    return revision


def _short(value: str, size: int = 8) -> str:
    tail = value.rsplit("_", 1)[-1]
    return tail[:size]


def safe_href(url: str) -> str:
    """只有 http/https 才允许成为可点击链接。

    资料出处里常见 DOI 之类的纯标识符（`10.xxxx/xxxx`），它们应当原样展示而不是变成链接；
    而 `javascript:` / `data:` 之类一旦进 href 就是存储型 XSS。前后端共用这一条口径。
    """
    text = (url or "").strip()
    lowered = text.lower()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return text
    return ""


def citation_view(citation: MemoryCitation) -> CitationView:
    return CitationView.model_validate(citation.model_dump(mode="json"))


def ref_label(citation: MemoryCitation, version: int) -> str:
    """稳定的人类可读引用。

    用条目自身的 version 而非 memory_ref.revision：后者是整个记忆工件的全局修订号，
    任何一条记忆写入都会让它前进，拿来标识单个条目会漂移。
    """
    return f"mem_{_short(citation.entry_id, 8)}@v{version}"


def entry_view(entry: Any, *, reason: str = "", ops: list[str] | None = None) -> EntryView:
    """把 PowerContext MemoryEntry 翻译成研续的结构化视图。"""
    fields = codec.decode(entry.text)
    citation = entry.citation
    return EntryView(
        kind=entry.kind,
        kind_label=kind_label(entry.kind),
        title=str(fields.get("title", "")),
        body=str(fields.get("body", "")),
        date=str(fields.get("date", "")),
        status=str(fields.get("status", "")),
        status_label=status_label(str(fields.get("status", ""))),
        tags=[str(tag) for tag in fields.get("tags", [])],
        url=str(fields.get("url", "")),
        url_href=safe_href(str(fields.get("url", ""))),
        refs=[str(ref) for ref in fields.get("refs", [])],
        text=entry.text,
        byte_length=codec.byte_length(entry.text),
        state=str(getattr(entry.state, "value", entry.state)),
        version=entry.version,
        citation=citation_view(citation),
        ref_label=ref_label(citation, entry.version),
        reason=reason,
        change_ops=ops or [],
    )


def _encode(entry: EntryInput) -> str:
    return codec.encode(
        title=entry.title,
        date=entry.date,
        status=entry.status,
        tags=entry.tags,
        url=entry.url,
        refs=entry.refs,
        body=entry.body,
    )


def _citation_from(view: CitationView | dict[str, Any]) -> MemoryCitation:
    raw = view.model_dump(mode="json") if isinstance(view, CitationView) else view
    try:
        return MemoryCitation.model_validate(raw)
    except Exception as exc:  # noqa: BLE001 - 把校验失败翻译成中文业务错误
        raise YanxuError(f"记忆引用（citation）格式非法：{exc}", code="invalid_citation") from exc


class MemoryService:
    def __init__(self, client: PowerContextClient) -> None:
        self.client = client

    # ---------------------------------------------------------------- Scope

    async def create_scope(self, *, title: str, summary: str, idempotency_key: str) -> str:
        scope = await self.client.create_scope(
            CreateScopeRequest(title=title, summary=summary or title, idempotency_key=idempotency_key)
        )
        return scope.scope_id

    async def capabilities(self) -> dict[str, Any]:
        caps = await self.client.get_capabilities()
        return caps.model_dump(mode="json")

    # -------------------------------------------------------------- Memory

    async def add_entry(self, scope_id: str, entry: EntryInput) -> EntryView:
        text = _encode(entry)
        saved = await self.client.remember_memory(
            RememberMemoryRequest(
                scope_id=scope_id,
                kind=entry.kind.value,
                text=text,
                reason=entry.reason.strip() or None,
            )
        )
        if saved.entry is None:
            raise YanxuError(
                "PowerContext 接受了写入但未返回记忆条目，请查看服务端日志。",
                code="powercontext_empty_entry",
                status=502,
            )
        return entry_view(saved.entry, reason=entry.reason.strip(), ops=["add"])

    async def revise_entry(
        self, scope_id: str, citation: CitationView | dict[str, Any], patch: EntryInput, reason: str
    ) -> EntryView:
        text = _encode(patch)
        effective_reason = (reason or patch.reason).strip()
        revised = await self.client.revise_memory_entry(
            ReviseMemoryEntryRequest(
                scope_id=scope_id,
                citation=_citation_from(citation),
                kind=patch.kind.value,
                text=text,
                reason=effective_reason or None,
            )
        )
        if revised.entry is None:
            raise YanxuError(
                "PowerContext 完成了修订但未返回条目快照。",
                code="powercontext_empty_entry",
                status=502,
            )
        return entry_view(revised.entry, reason=effective_reason, ops=["revise"])

    async def retire_entry(
        self, scope_id: str, citation: CitationView | dict[str, Any], reason: str
    ) -> EntryView | None:
        retired = await self.client.retire_memory_entry(
            RetireMemoryEntryRequest(
                scope_id=scope_id, citation=_citation_from(citation), reason=reason.strip() or None
            )
        )
        return entry_view(retired.entry, reason=reason.strip(), ops=["deactivate"]) if retired.entry else None

    async def list_entries(self, scope_id: str, *, include_inactive: bool = False) -> list[EntryView]:
        listed = await self.client.list_memory_entries(
            ListMemoryEntriesRequest(scope_id=scope_id, include_inactive=include_inactive)
        )
        reasons, ops = await self._change_index(scope_id)
        views = [
            entry_view(
                item,
                reason=reasons.get(item.citation.entry_version_id, ""),
                ops=ops.get(item.citation.entry_id, []),
            )
            for item in listed.entries
        ]
        return _sort_entries(views)

    async def get_entry(self, scope_id: str, citation: CitationView | dict[str, Any]) -> EntryView:
        entry = await self.client.get_memory_entry(
            GetMemoryEntryRequest(scope_id=scope_id, citation=_citation_from(citation))
        )
        return entry_view(entry)

    async def search(self, scope_id: str, query: str, *, limit: int = 10, mode: str = "fts") -> list[SearchHitView]:
        found = await self.client.search_memory(
            SearchMemoryRequest(scope_id=scope_id, query=query, limit=limit, mode=mode)
        )
        reasons, ops = await self._change_index(scope_id)
        hits: list[SearchHitView] = []
        for hit in found.hits:
            # SearchMemoryHit 只带 citation/text/score；kind、version、state 需回读条目才是真实值。
            entry = await self.client.get_memory_entry(
                GetMemoryEntryRequest(scope_id=scope_id, citation=hit.citation)
            )
            hits.append(
                SearchHitView(
                    entry=entry_view(
                        entry,
                        reason=reasons.get(entry.citation.entry_version_id, ""),
                        ops=ops.get(entry.citation.entry_id, []),
                    ),
                    score=hit.score,
                    matched_by=[str(_enum_value(item)) for item in hit.matched_by],
                )
            )
        return hits

    async def prepare_context(self, scope_id: str, query: str, *, max_bytes: int = DEFAULT_CONTEXT_BYTES) -> PreparedContextView:
        prepared = await self.client.prepare_context(
            PrepareContextRequest(scope_id=scope_id, query=query, max_bytes=max_bytes)
        )
        return PreparedContextView(
            status=str(_enum_value(prepared.status)),
            content=prepared.content or "",
            content_bytes=int(prepared.content_bytes or 0),
            query=query,
        )

    # ------------------------------------------------------------- History

    async def raw_changes(self, scope_id: str, *, since_revision: int = 0) -> list[ChangeView]:
        changes = await self.client.list_memory_changes(
            ListMemoryChangesRequest(scope_id=scope_id, since_revision=since_revision)
        )
        views: list[ChangeView] = []
        for group in changes.revisions:
            revision = group.memory_ref.revision
            for change in group.changes:
                views.append(
                    ChangeView(
                        revision=revision,
                        op=str(getattr(change.op, "value", change.op)),
                        entry_id=change.entry_id,
                        from_entry_version_id=change.from_entry_version_id or "",
                        to_entry_version_id=change.to_entry_version_id or "",
                        reason=change.reason or "",
                    )
                )
        return views

    async def _change_index(self, scope_id: str) -> tuple[dict[str, str], dict[str, list[str]]]:
        """entry_version_id → 最近一次变更原因；entry_id → 变更操作序列。"""
        reasons: dict[str, str] = {}
        ops: dict[str, list[str]] = {}
        for change in await self.raw_changes(scope_id):
            if change.to_entry_version_id and change.reason:
                reasons[change.to_entry_version_id] = change.reason
            if change.op not in ops.setdefault(change.entry_id, []):
                ops[change.entry_id].append(change.op)
        return reasons, ops

    async def entry_history(self, scope_id: str, entry_id: str) -> EntryHistoryView:
        changes = await self.raw_changes(scope_id)
        related = [change for change in changes if change.entry_id == entry_id]
        if not related:
            raise YanxuError(f"找不到该记忆的变更历史：{entry_id}", code="history_not_found", status=404)

        active = await self.client.list_memory_entries(
            ListMemoryEntriesRequest(scope_id=scope_id, include_inactive=True)
        )
        current = next((item for item in active.entries if item.citation.entry_id == entry_id), None)

        snapshots: list[EntryView] = []
        unavailable: list[UnavailableSnapshot] = []
        seen: set[str] = set()
        memory_ref_by_version: dict[str, dict[str, Any]] = {}
        for change in related:
            memory_ref_by_version[change.to_entry_version_id] = {
                "family": "memory",
                "artifact_id": current.citation.memory_ref.artifact_id if current else "memory",
                "revision": change.revision,
            }

        for change in related:
            version_id = change.to_entry_version_id
            if not version_id or version_id in seen:
                continue
            seen.add(version_id)
            citation = {
                "memory_ref": memory_ref_by_version[version_id],
                "entry_id": entry_id,
                "entry_version_id": version_id,
            }
            try:
                snapshot = await self.get_entry(scope_id, citation)
            except ServerResponseError as exc:
                # 只有「这个版本确实读不回来」才允许降级为一条不可读说明；
                # 超时、网关错误之类会把历史悄悄截短，必须原样抛出去变成 5xx。
                if exc.status_code != 404:
                    raise
                unavailable.append(
                    UnavailableSnapshot(
                        entry_version_id=version_id,
                        revision=change.revision,
                        op=change.op,
                        error=exc.server_message or f"PowerContext 返回 HTTP 404（{exc.code or 'not_found'}）",
                    )
                )
                continue
            snapshot.reason = change.reason
            snapshot.change_ops = [change.op]
            snapshots.append(snapshot)

        return EntryHistoryView(
            entry_id=entry_id,
            kind=current.kind if current else (snapshots[-1].kind if snapshots else ""),
            kind_label=kind_label(current.kind if current else (snapshots[-1].kind if snapshots else "")),
            current=entry_view(current) if current else None,
            snapshots=snapshots,
            unavailable=unavailable,
            changes=related,
        )

    # ------------------------------------------------------------- Handoff

    async def save_handoff(self, scope_id: str, payload: HandoffInput) -> HandoffView:
        if not payload.state:
            raise YanxuError(
                "交接至少需要一条「已确认状态」。PowerContext 的 CurrentWorkHandoff.state 要求非空。",
                code="handoff_state_required",
            )
        source_id = f"yanxu-handoff-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        preview = await self.client.handoff_current_work(
            HandoffCurrentWorkRequest(
                scope_id=scope_id,
                source_id=source_id,
                handoff={
                    "schema": CURRENT_WORK_HANDOFF_SCHEMA,
                    "trust": "untrusted_input",
                    "objective": payload.objective,
                    "state": [_claim(item) for item in payload.state],
                    "disposition": payload.disposition,
                    "next_action": _claim(payload.next_action) if payload.next_action else None,
                    "omissions": [item.strip() for item in payload.omissions if item.strip()],
                },
            )
        )
        committed = await self.client.commit_handoff(
            CommitHandoffRequest(scope_id=scope_id, handoff=preview.handoff)
        )
        return HandoffView(
            status="resolved",
            trust="committed",
            disposition=str(_enum_value(committed.content.disposition)),
            disposition_label=_disposition_label(committed.content.disposition),
            objective=committed.content.objective,
            state=[_statement_view(item) for item in committed.content.state],
            next_action=_statement_view(committed.content.next_action) if committed.content.next_action else None,
            omissions=[item.text for item in committed.content.omissions],
            selected_revision=_artifact_view(committed.reference),
            current_revision=_artifact_view(committed.reference),
            boundary_source_id=preview.boundary.source.source_id,
        )

    async def restore_handoff(
        self, scope_id: str, *, selection: str = "latest", revision: ArtifactRefView | None = None
    ) -> HandoffView:
        request = ContinueHandoffRequest(scope_id=scope_id, selection=selection)
        if selection == "exact":
            if revision is None:
                raise YanxuError("selection=exact 需要指定 revision。", code="handoff_revision_required")
            require_handoff_ref(revision)
            request = ContinueHandoffRequest(
                scope_id=scope_id, selection="exact", revision=revision.model_dump(mode="json")
            )
        resolution = await self.client.continue_handoff(request)
        if resolution.status == "empty" or resolution.content is None:
            return HandoffView(status="empty")

        content = resolution.content
        return HandoffView(
            status=str(_enum_value(resolution.status)),
            trust=str(_enum_value(resolution.trust)),
            disposition=str(_enum_value(content.disposition)),
            disposition_label=_disposition_label(content.disposition),
            objective=content.objective,
            state=[_statement_view(item) for item in content.state],
            next_action=_statement_view(content.next_action) if content.next_action else None,
            omissions=[item.text for item in content.omissions],
            evidence_checks=[
                EvidenceCheckView(
                    claim=str(_enum_value(check.claim)),
                    state_index=check.state_index,
                    status=str(_enum_value(check.status)),
                    unavailable_evidence=[_citation_summary(item) for item in check.unavailable_evidence],
                )
                for check in resolution.evidence_checks
            ],
            selected_revision=_artifact_view(resolution.selected_revision) if resolution.selected_revision else None,
            current_revision=_artifact_view(resolution.current_revision) if resolution.current_revision else None,
        )

    async def acknowledge_handoff(
        self, scope_id: str, payload: AcknowledgeInput, *, revision: ArtifactRefView
    ) -> HandoffView:
        require_handoff_ref(revision)
        missing = [
            label
            for label, checked in (
                ("「我已逐条核对交接中的状态与当前实际情况一致」", payload.live_state_checked),
                ("「我具备继续这项工作所需的环境与工具」", payload.capability_checked),
                ("「我有权接手并继续这项工作」", payload.authorization_checked),
            )
            if not checked
        ]
        if payload.status == "accepted" and missing:
            raise YanxuError(
                "PowerContext 规定：status=accepted 时 receiver_checks 必须全部为 confirmed。"
                f"还差 {'、'.join(missing)}。",
                code="handoff_ack_requires_check",
            )
        checks = ReceiverChecks(
            live_state="confirmed" if payload.live_state_checked else "not_checked",
            capability="confirmed" if payload.capability_checked else "not_checked",
            authorization="confirmed" if payload.authorization_checked else "not_checked",
        )
        source_id = f"yanxu-ack-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        acknowledgement = await self.client.acknowledge_handoff(
            AcknowledgeHandoffRequest(
                scope_id=scope_id,
                source_id=source_id,
                receiver="研续 Yanxu · 新会话",
                status=payload.status,
                selection="exact",
                receiver_checks=checks,
                revision=revision.model_dump(mode="json"),
                message=payload.message.strip() or None,
            )
        )
        view = await self.restore_handoff(scope_id, selection="exact", revision=revision)
        view.receipt_source_id = acknowledgement.receipt.source.source_id
        return view


def _sort_entries(views: list[EntryView]) -> list[EntryView]:
    return sorted(views, key=lambda item: (item.date or "", item.citation.memory_ref.revision), reverse=True)


def _claim(claim: HandoffClaimInput) -> WorkClaim:
    if claim.citation is not None:
        evidence = [
            HandoffCitation.model_validate({"kind": "memory", "memory_citation": claim.citation.model_dump(mode="json")})
        ]
        return WorkClaim(text=claim.text, basis="verified", evidence=evidence)
    return WorkClaim(text=claim.text, basis="declared", evidence=[])


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _disposition_label(value: Any) -> str:
    from .schemas import DISPOSITION_LABELS

    return DISPOSITION_LABELS.get(str(_enum_value(value)), str(_enum_value(value)))


def _artifact_view(reference: Any) -> ArtifactRefView:
    return ArtifactRefView.model_validate(reference.model_dump(mode="json"))


def _statement_view(statement: Any) -> HandoffStatementView:
    return HandoffStatementView(text=statement.text, citations=[_citation_summary(item) for item in statement.citations])


def _citation_summary(citation: Any) -> HandoffCitationView:
    data = citation.model_dump(mode="json")
    root = data.get("root", data)
    kind = str(root.get("kind", "unknown"))
    if kind == "memory":
        memory = root.get("memory_citation", {})
        entry_id = str(memory.get("entry_id", ""))
        revision = memory.get("memory_ref", {}).get("revision", "?")
        return HandoffCitationView(kind=kind, summary=f"记忆 {entry_id[:16]}…@r{revision}")
    if kind == "source":
        source = root.get("source_ref", {})
        return HandoffCitationView(kind=kind, summary=f"来源 {source.get('source_id', '')}")
    if kind == "artifact":
        artifact = root.get("artifact_ref", {})
        return HandoffCitationView(
            kind=kind, summary=f"工件 {artifact.get('family', '')}/{artifact.get('artifact_id', '')}@r{artifact.get('revision', '')}"
        )
    return HandoffCitationView(kind=kind, summary=str(root)[:80])
