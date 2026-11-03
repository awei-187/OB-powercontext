"""界面契约回归测试：把 M1 的 P0 阻塞与 M2 的界面精修要求钉成断言。

这些测试不开浏览器，只检查静态资源本身的结构。它们要挡住的是**具体的回退**：
CSS 的 display 重新盖掉 hidden、覆盖层在初始 HTML 里就是展开的、
链接的 href 又直接取自用户输入的 url、技术细节重新占回首屏。
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"
OVERLAY_IDS = ("history-backdrop", "history-drawer", "status-modal", "project-modal")


class _Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.elements: list[dict] = []
        self.button_texts: dict[str, str] = {}
        self._open_button: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        parsed = dict(attrs)
        self.elements.append({"tag": tag, "attrs": parsed, "hidden": "hidden" in parsed})
        if tag == "button" and parsed.get("id"):
            self._open_button = parsed["id"]
            self.button_texts.setdefault(self._open_button, "")

    def handle_endtag(self, tag: str) -> None:
        if tag == "button":
            self._open_button = None

    def handle_data(self, data: str) -> None:
        if self._open_button:
            self.button_texts[self._open_button] += data


def _parse() -> tuple[str, str, _Collector]:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    collector = _Collector()
    collector.feed(html)
    return html, css, collector


def _script() -> str:
    return (STATIC / "app.js").read_text(encoding="utf-8")


def _by_id(elements: list[dict], element_id: str) -> dict:
    matches = [item for item in elements if item["attrs"].get("id") == element_id]
    assert len(matches) == 1, f"index.html 里 #{element_id} 应恰好出现一次，实际 {len(matches)} 次"
    return matches[0]


def _classes(element: dict) -> set[str]:
    return set((element["attrs"].get("class") or "").split())


def test_css_hidden_beats_author_display() -> None:
    """P0 根因：作者样式的 display 会盖掉浏览器默认的 [hidden]{display:none}。

    这与选择器优先级无关，只有 !important 能把 hidden 抬回唯一显隐开关。
    """
    _html, css, _collector = _parse()
    assert re.search(r"\[hidden\]\s*\{\s*display:\s*none\s*!important;\s*\}", css), (
        "app.css 必须保留 [hidden]{display:none !important}，否则抽屉与弹窗会重新常驻"
    )

    # 这两条正是 M1 里把界面挡住的规则：display 可以保留，但必须被上面的 !important 压住
    assert re.search(r"\.drawer\s*\{[^}]*display:\s*flex", css, re.S)
    assert re.search(r"\.modal-backdrop\s*\{[^}]*display:\s*grid", css, re.S)


def test_every_overlay_starts_hidden() -> None:
    """初始加载：所有覆盖层与非首屏区块在 HTML 里就必须是 hidden。"""
    _html, _css, collector = _parse()
    for element_id in (
        *OVERLAY_IDS,
        "toast",
        "project-view",
        "continue-hero",
        "demo-banner",
        "error-banner",
        "error-retry",
        "report-output",
        "ack-result",
    ):
        assert _by_id(collector.elements, element_id)["hidden"], f"#{element_id} 在初始 HTML 里必须是 hidden"

    assert not _by_id(collector.elements, "empty-state")["hidden"], "空状态是首屏默认视图"


def test_overlays_are_accessible_dialogs() -> None:
    """键盘焦点：覆盖层要能被读屏软件识别为对话框，并且都有关闭按钮。"""
    _html, _css, collector = _parse()
    for element_id, close_id in (
        ("history-drawer", "history-close"),
        ("status-modal", "status-modal-close"),
        ("project-modal", "project-modal-close"),
    ):
        element = _by_id(collector.elements, element_id)
        assert element["attrs"].get("role") == "dialog", element_id
        assert element["attrs"].get("aria-modal") == "true", element_id
        assert element["attrs"].get("aria-label"), f"#{element_id} 需要可访问名称"
        close_button = _by_id(collector.elements, close_id)
        assert close_button["tag"] == "button"
        assert close_button["attrs"].get("type") == "button"


def test_js_forces_overlays_hidden_on_boot() -> None:
    """脚本启动时的兜底：boot() 第一件事就是把全部覆盖层压回隐藏。"""
    script = _script()
    assert "function hideAllOverlays()" in script
    boot_body = script.split("async function boot() {", 1)[1]
    first_call = next(line.strip() for line in boot_body.splitlines() if line.strip())
    assert first_call == "hideAllOverlays();", f"boot() 的第一步应是 hideAllOverlays()，实际是 {first_call}"


def test_js_manages_focus_and_escape() -> None:
    """键盘焦点：Escape 只关最上层，Tab 在覆盖层内循环，关闭后焦点回到触发元素。"""
    script = _script()
    for required in (
        "function openOverlay(",
        "function closeOverlay(",
        "function closeTopOverlay()",
        "function bindOverlayKeys()",
        "returnFocus",
        'event.key === "Escape"',
        'event.key !== "Tab"',
    ):
        assert required in script, f"app.js 缺少覆盖层管理逻辑：{required}"

    # 覆盖层的显隐只能走 openOverlay / closeOverlay，散装的 .hidden 赋值会漏掉焦点与层级管理
    for element_id in OVERLAY_IDS:
        assert f'$("#{element_id}").hidden' not in script, f"#{element_id} 的显隐必须走覆盖层管理器"


def test_links_only_from_backend_validated_href() -> None:
    """来源链接：href 只能取后端 safe_href 判定过的 url_href，不能直接取用户输入。"""
    script = _script()
    assert 'href="${escapeHtml(entry.url)}"' not in script, "href 不能直接来自用户输入的 url"
    link_block = script.split("function sourceLinkHtml(", 1)[1].split("\n  }", 1)[0]
    assert "entry.url_href" in link_block, "只有后端判定过的 url_href 才能成为链接"
    assert "entry-url-plain" in link_block, "其余 scheme 必须降级为纯文本"


def test_first_screen_is_research_not_infrastructure() -> None:
    """技术细节（Scope ID / SDK 函数 / SQLite / 检索方式）收进「技术详情」，不占首屏。"""
    html, _css, collector = _parse()

    details = [item for item in collector.elements if _classes(item) >= {"tech-details"}]
    assert len(details) >= 2, "项目头与交接面板都应有可折叠的「技术详情」"
    for item in details:
        assert item["tag"] == "details"

    topbar = html.split("</header>", 1)[0]
    for jargon in ("scp_", "Scope", "sqlite", "SQLite", "embedding", "handoff_current_work", "memory_ref"):
        assert jargon not in topbar, f"顶栏不该常驻技术术语：{jargon}"
    assert "技术详情" in topbar, "顶栏应提供技术详情入口"

    # SDK 函数名只允许出现在折叠的技术详情里
    outside = re.sub(r'<details class="tech-details">.*?</details>', "", html, flags=re.S)
    for function_name in ("handoff_current_work", "commit_handoff", "acknowledge_handoff"):
        assert function_name in html, f"{function_name} 应在技术详情中如实说明"
        assert function_name not in outside, f"{function_name} 只应出现在折叠的「技术详情」里"


def test_buttons_use_plain_language() -> None:
    """按钮文案改成用户看得懂的动作，不是 SDK 术语。"""
    _html, _css, collector = _parse()
    expected = {
        "entry-submit": "保存记录",
        "project-submit": "创建项目",
        "new-project": "新建项目",
        "handoff-submit": "保存交接",
        "report-submit": "生成 Markdown",
        "ack-submit": "确认接手",
    }
    for element_id, label in expected.items():
        assert collector.button_texts.get(element_id, "").strip() == label, (
            f"#{element_id} 的文案应是「{label}」，实际是「{collector.button_texts.get(element_id)}」"
        )

    for jargon in ("写入 PowerContext", "提交 revise", "remember(", "revise("):
        for element_id, text in collector.button_texts.items():
            assert jargon not in text, f"按钮 #{element_id} 的文案不该出现 SDK 术语：{jargon}"


def test_acknowledge_exposes_all_three_receiver_checks() -> None:
    """接手面板必须暴露 ReceiverChecks 的全部三项，文案与官方字段含义一致。"""
    html, _css, collector = _parse()
    ids = [item["attrs"].get("id") for item in collector.elements]
    for element_id in ("ack-live-state", "ack-capability", "ack-authorization", "ack-version"):
        assert element_id in ids, element_id

    for wording in (
        "我已逐条核对交接中的状态与当前实际情况一致",
        "我具备继续这项工作所需的环境与工具",
        "我有权接手并继续这项工作",
        "receiver_checks",
    ):
        assert wording in html, f"接手面板缺少必要说明：{wording}"

    script = _script()
    for field in ("live_state_checked", "capability_checked", "authorization_checked", "revision: state.ackRevision"):
        assert field in script, f"提交时必须带上 {field}"
    assert "handoff_revision_stale" in script, "版本过期必须就地提示并刷新"


def test_visible_loading_error_and_empty_states_exist() -> None:
    """可见 loading、错误恢复、空状态三样都要在。"""
    _html, css, collector = _parse()
    script = _script()

    assert ".btn.is-busy" in css and "@keyframes spin" in css, "缺少可见的进行中状态"
    assert ".busy-line" in css and "busy-line" in script
    assert "function withBusy(" in script

    assert _by_id(collector.elements, "error-retry")["tag"] == "button", "错误横幅必须提供重试"
    assert "errorRetry" in script

    ids = [item["attrs"].get("id") for item in collector.elements]
    for empty_id in ("empty-state", "report-empty"):
        assert empty_id in ids, empty_id
    assert "group-empty" in script, "台账需要空状态文案"


def test_narrow_screen_is_supported() -> None:
    """窄屏可用：必须有针对手机宽度的断点。"""
    html, css, _collector = _parse()
    for breakpoint in ("max-width: 1080px", "max-width: 820px", "max-width: 520px"):
        assert breakpoint in css, f"缺少断点 {breakpoint}"
    assert "viewport" in html


def test_demo_data_is_clearly_synthetic() -> None:
    """示例数据必须醒目标注合成，其中的数字不能被当成实测。"""
    html, _css, collector = _parse()
    assert _by_id(collector.elements, "demo-banner")["hidden"]
    assert "合成演示数据" in html
    assert "不是实测" in html

    script = _script()
    assert "isDemoProject" in script and "【示例】" in script

    seed = (STATIC.parent.parent / "scripts" / "seed_demo.py").read_text(encoding="utf-8")
    assert "合成演示数据" in seed
    assert "非实测" in seed
