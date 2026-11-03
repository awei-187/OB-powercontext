"""展示页源码的诚实性契约。

qoder/site/ 是要拿去参赛的静态展示页，它最容易出的问题不是排版，而是**说过头**：
编一个线上地址、把没测过的时间收益写成实测、用生成图顶替真实截图。
这些红线各锁一条断言，改文案时会立刻撞上。
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent / "site"
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.errors: list[str] = []
        self.hrefs: list[str] = []
        self.imgs: list[tuple[str, str]] = []
        self.scripts = 0
        self.ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if "id" in attributes:
            if attributes["id"] in self.ids:
                self.errors.append(f"重复 id：{attributes['id']}")
            self.ids.add(attributes["id"] or "")
        if tag == "script":
            self.scripts += 1
        if tag == "a" and attributes.get("href"):
            self.hrefs.append(attributes["href"] or "")
        if tag == "img":
            self.imgs.append((attributes.get("src", ""), attributes.get("alt", "")))
        if tag not in VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"标签不匹配：期望 </{self.stack[-1] if self.stack else '?'}>，实得 </{tag}>")
            while self.stack and self.stack.pop() != tag:
                pass
        else:
            self.stack.pop()


def _parse() -> tuple[str, _Page]:
    html = (SITE / "index.html").read_text(encoding="utf-8")
    page = _Page()
    page.feed(html)
    return html, page


def test_site_page_is_well_formed_static_html() -> None:
    html, page = _parse()
    assert page.errors == [], page.errors
    assert page.stack == [], f"有标签没闭合：{page.stack}"
    assert page.scripts == 0, "展示页必须是纯静态：无脚本、无构建步骤"
    assert all(alt.strip() for _src, alt in page.imgs), "每张图都要有 alt"

    css = (SITE / "styles.css").read_text(encoding="utf-8")
    assert css.count("{") == css.count("}"), "CSS 花括号不平衡"
    assert not re.findall(r"url\(\s*['\"]?https?:", css), "CSS 不得引用外部资源"
    assert "@media" in css, "展示页要有窄屏断点"


def test_site_only_links_to_confirmed_targets() -> None:
    """链接只用已确认的：外链一个都不许有，本地资源必须真的存在。

    仓库相对路径（../PROJECT.md 这类）发布到线上会 404，所以证据清单一律用纯文本路径，
    这里断言连一个仓库相对链接都没有。
    """
    _html, page = _parse()
    external = [href for href in page.hrefs if re.match(r"^[a-z]+://", href) or href.startswith("//")]
    assert external == [], f"展示页不得出现未确认的外部链接：{external}"

    relative = [href for href in page.hrefs if not href.startswith("#")]
    assert relative == [], f"仓库相对路径发布后会 404，请改成纯文本：{relative}"

    for href in page.hrefs:
        if href.startswith("#"):
            assert href[1:] in page.ids, f"页内锚点不存在：{href}"

    for src, _alt in page.imgs:
        assert (SITE / src).exists(), f"图片不存在：{src}"


def test_site_does_not_claim_a_live_url() -> None:
    """不伪造线上体验：发布前必须写清「尚未发布，没有线上地址」。"""
    html, _page = _parse()
    assert "尚未发布" in html
    assert "没有线上地址" in html
    assert not re.search(r"qoder\.site", html), "不得出现虚构的 Qoder Sites 地址"
    assert "源码预览" in html


def test_site_claims_no_quantified_time_saving() -> None:
    """不伪造节省时间：那个「20–60 分钟」没有测量支撑，已删，不许在展示页里回来。"""
    html, _page = _parse()
    assert not re.search(r"\d+\s*[–~-]\s*\d+\s*分钟", html), "不得出现未测量的时间区间"
    assert "不主张任何量化的时间节省" in html
    assert "未验证假设" in html


def test_site_screenshots_are_honest() -> None:
    """只有真截图能当截图：其余必须是明确标注的占位框，不许用生成图顶替。"""
    html, page = _parse()
    assert "截图待补" in html
    placeholders = html.count("截图待补")
    assert placeholders >= 5, f"占位框数量异常：{placeholders}"

    # 唯一一张真图是协调人在可见 Edge 里拍的 M1 P0 现场，且必须说明它是缺陷现场而不是产品美图。
    assert len(page.imgs) == 1, f"展示页当前只应有一张真实截图：{page.imgs}"
    src, alt = page.imgs[0]
    assert src == "assets/m1-p0-overlays.png"
    assert "P0" in alt or "缺陷" in alt or "弹窗" in alt
    assert (SITE / "assets" / "m1-p0-overlays.png").exists()
    assert "真实截图" in html and "P0 现场" in html


def test_site_separates_verified_from_unverified() -> None:
    """验收状态板必须把「未验证」如实写出来，不能整页都是绿灯。"""
    html, _page = _parse()
    assert "已验证 / 未验证" in html
    assert html.count("pill-no") >= 3, "未验证 / 未执行项必须可见"
    assert "未验证" in html and "未执行" in html
    assert "NATIVE_BROWSER_VIEWPORT_UNAVAILABLE" in html, "要写清截图为什么拿不到，而不是含糊带过"
    assert "DOM 事件跑得通 ≠ 人能用" in html, "M1 那条教训必须留在展示页上"


def test_site_marks_synthetic_demo_data() -> None:
    html, _page = _parse()
    assert "合成演示数据" in html
    assert "非实测" in html
