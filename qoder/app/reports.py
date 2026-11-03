"""带来源的组会 / 周报 Markdown 生成。

确定性拼装，不依赖任何模型：每一条要点都携带 PowerContext 真实 citation，
读者可以据此回溯到具体记忆条目及其修订版本。

时间口径（写进报告正文，不靠读者猜）：
- 区间过滤只作用于**带日期的工作记录**与**已完成待办**，按条目自己的记录日期；
- 目标 / 决策 / 未解决问题 / 下一步 / 资料出处是**当前有效状态**，不按区间过滤；
- 研续不记录「解决时间」：PowerContext 的变更日志不含时间戳，因此已解决 / 已完成
  只按当前状态列出，绝不把记录日期冒称成解决时间。
"""

from __future__ import annotations

from datetime import datetime

from .memory import safe_href
from .schemas import EntryView, HandoffView, ProjectView, ReportView

_REPORT_TITLES = {"weekly": "周报", "group": "组会汇报"}


def _now() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")


def _cell(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\r\n", "\n").replace("\n", "<br>").strip()


def _bullet_text(entry: EntryView) -> str:
    head = entry.title.strip()
    body = entry.body.strip()
    if head and body:
        return f"**{head}** — {body}"
    return head or body or "（空）"


def _in_range(entry: EntryView, date_from: str, date_to: str) -> bool:
    if not entry.date:
        return True
    if date_from and entry.date < date_from:
        return False
    return bool(not date_to or entry.date <= date_to)


class _Citations:
    """收集真正出现在报告正文里的引用；附录与计数只认这份名单。"""

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self.entries: list[EntryView] = []

    def ref(self, entry: EntryView) -> str:
        key = entry.citation.entry_version_id
        if key not in self._seen:
            self._seen.add(key)
            self.entries.append(entry)
        return f"`{entry.ref_label}`"


def _section(lines: list[str], heading: str, items: list[str], empty: str) -> None:
    lines.append(f"## {heading}")
    lines.append("")
    if items:
        lines.extend(items)
    else:
        lines.append(f"_{empty}_")
    lines.append("")


def build_report(
    *,
    project: ProjectView,
    entries: list[EntryView],
    handoff: HandoffView | None,
    report_type: str,
    date_from: str,
    date_to: str,
    include_done_todos: bool,
) -> ReportView:
    by_kind: dict[str, list[EntryView]] = {}
    for entry in entries:
        by_kind.setdefault(entry.kind, []).append(entry)

    goals = by_kind.get("goal", [])
    decisions = by_kind.get("decision", [])
    questions = by_kind.get("open_question", [])
    steps = by_kind.get("next_step", [])
    sources = by_kind.get("source", [])
    records = [item for item in by_kind.get("record", []) if _in_range(item, date_from, date_to)]
    todos = by_kind.get("todo", [])
    todos_open = [item for item in todos if item.status != "done"]
    todos_done = [item for item in todos if item.status == "done" and _in_range(item, date_from, date_to)]

    unresolved = [item for item in questions if item.status != "resolved"]
    resolved = [item for item in questions if item.status == "resolved"]
    steps_open = [item for item in steps if item.status not in {"done", "dropped"}]
    steps_done = [item for item in steps if item.status == "done"]
    steps_dropped = [item for item in steps if item.status == "dropped"]

    cited = _Citations()

    title = f"{_REPORT_TITLES.get(report_type, report_type)} · {project.name}"
    period = f"{date_from or '起始不限'} ~ {date_to or '至今'}"
    lines: list[str] = [f"# {title}", ""]
    lines.append(f"> 统计区间：{period} ｜ 生成时间：{_now()}")
    lines.append(f"> 数据来源：PowerContext Scope `{project.scope_id}`（记忆条目为唯一真源）")
    lines.append(
        "> 时间口径：区间只过滤带日期的工作记录与已完成待办（按记录日期）；"
        "目标、决策、问题、下一步、资料出处为当前有效状态。"
        "研续不记录解决 / 完成的发生时间（PowerContext 变更日志不含时间戳），故不按区间推断。"
    )
    lines.append("")

    lines.append("## 一、研究目标")
    lines.append("")
    if goals:
        for goal in goals:
            lines.append(f"- {goal.body.strip() or goal.title.strip()} {cited.ref(goal)}")
    else:
        lines.append("- _尚未录入研究目标_")
    lines.append("")

    lines.append("## 二、本期工作记录")
    lines.append("")
    if records:
        for record in records:
            heading = record.title.strip() or "工作记录"
            stamp = f"{record.date} · " if record.date else ""
            lines.append(f"### {stamp}{heading}")
            lines.append("")
            for paragraph in (record.body.strip() or "（无正文）").split("\n"):
                lines.append(paragraph)
            lines.append("")
            lines.append(f"来源：{cited.ref(record)}")
            if record.tags:
                lines.append(f"标签：{'、'.join(record.tags)}")
            lines.append("")
    else:
        lines.append("_本区间没有工作记录。_")
        lines.append("")

    lines.append("## 三、已确认决策")
    lines.append("")
    if decisions:
        lines.append("| 决策 | 依据（PowerContext reason） | 来源 |")
        lines.append("| --- | --- | --- |")
        for decision in decisions:
            lines.append(
                f"| {_cell(_bullet_text(decision))} | {_cell(decision.reason or '未填写')} | {_cell(cited.ref(decision).strip('`'))} |"
            )
        lines.append("")
    else:
        lines.append("_尚无已确认决策。_")
        lines.append("")

    # 已解决的问题不能再挂在「未解决」标题下，否则周报会误导读者以为它仍然悬着。
    lines.append("## 四、未解决问题")
    lines.append("")
    if unresolved:
        for question in unresolved:
            suffix = f"（{question.status_label}）" if question.status else ""
            lines.append(f"- [ ] {_bullet_text(question)}{suffix} {cited.ref(question)}")
        lines.append("")
    else:
        lines.append("_当前没有未解决的问题。_")
        lines.append("")
    if resolved:
        lines.append("### 已解决（当前有效状态，不按区间过滤）")
        lines.append("")
        for question in resolved:
            lines.append(f"- [x] {_bullet_text(question)} {cited.ref(question)}")
        lines.append("")
        lines.append("_说明：研续不记录问题的解决时间，此节按当前状态列出，不代表发生在统计区间内。_")
        lines.append("")

    lines.append("## 五、下一步计划")
    lines.append("")
    step_lines = [f"- [ ] {_bullet_text(item)} {cited.ref(item)}" for item in steps_open]
    step_lines += [f"- [x] {_bullet_text(item)} {cited.ref(item)}" for item in steps_done]
    if step_lines:
        lines.extend(step_lines)
        lines.append("")
    else:
        lines.append("_尚未规划下一步。_")
        lines.append("")
    if steps_dropped:
        lines.append("已放弃（不再计划）：")
        lines.append("")
        for item in steps_dropped:
            lines.append(f"- ~~{_bullet_text(item)}~~ {cited.ref(item)}")
        lines.append("")

    lines.append("## 六、待办")
    lines.append("")
    todo_lines = [f"- [ ] {_bullet_text(item)} {cited.ref(item)}" for item in todos_open]
    if include_done_todos:
        todo_lines += [f"- [x] {_bullet_text(item)} {cited.ref(item)}" for item in todos_done]
    if todo_lines:
        lines.extend(todo_lines)
        lines.append("")
    else:
        lines.append("_没有待办事项。_")
        lines.append("")

    lines.append("## 七、资料出处")
    lines.append("")
    if sources:
        for index, source in enumerate(sources, start=1):
            name = source.title.strip() or "未命名资料"
            href = safe_href(source.url)
            link = f"（<{href}>）" if href else (f"（标识：{source.url}）" if source.url else "")
            lines.append(f"{index}. **{name}**{link} {cited.ref(source)}")
            if source.body.strip():
                lines.append(f"   - 相关性：{source.body.strip()}")
        lines.append("")
    else:
        lines.append("_尚未登记资料出处。_")
        lines.append("")

    if handoff and handoff.status == "resolved":
        lines.append("## 八、上次工作交接")
        lines.append("")
        lines.append(f"- 交接目标：{handoff.objective}")
        lines.append(f"- 交接判定：{handoff.disposition_label}")
        if handoff.state:
            lines.append("- 交接时已确认状态：")
            for statement in handoff.state:
                cited_summary = "、".join(item.summary for item in statement.citations)
                lines.append(f"  - {statement.text}" + (f"（引用：{cited_summary}）" if cited_summary else ""))
        if handoff.next_action:
            lines.append(f"- 交接时下一步：{handoff.next_action.text}")
        if handoff.omissions:
            lines.append("- 交接时明确未覆盖：")
            lines.extend(f"  - {item}" for item in handoff.omissions)
        revision = handoff.selected_revision or handoff.current_revision
        if revision:
            lines.append(f"- 交接工件：`{revision.family}/{revision.artifact_id}@r{revision.revision}`")
        lines.append("")

    cited_entries = cited.entries
    cited_sources = [item for item in cited_entries if item.kind == "source"]

    lines.append("## 附录 · 来源追溯表")
    lines.append("")
    lines.append("_只列本报告正文真正引用到的记忆条目。_")
    lines.append("")
    lines.append("| 引用 | 类型 | entry_id | entry_version_id | 条目版本 | 记忆工件版本 | 状态 | 变更序列 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for entry in cited_entries:
        lines.append(
            f"| {_cell(entry.ref_label)} | {_cell(entry.kind_label)} | {_cell(entry.citation.entry_id)} "
            f"| {_cell(entry.citation.entry_version_id)} | {entry.version} "
            f"| {entry.citation.memory_ref.revision} "
            f"| {_cell(entry.state)} | {_cell(' → '.join(entry.change_ops))} |"
        )
    lines.append("")
    lines.append(
        f"_本报告由「研续 Yanxu」基于 PowerContext 记忆自动生成，"
        f"共引用 {len(cited_entries)} 条记忆、{len(cited_sources)} 条资料出处。_"
    )

    markdown = "\n".join(lines)
    return ReportView(
        markdown=markdown,
        report_type=report_type,
        title=title,
        date_from=date_from,
        date_to=date_to,
        citation_count=len(cited_entries),
        source_count=len(cited_sources),
    )
