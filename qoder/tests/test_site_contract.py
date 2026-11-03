"""展示页的结构契约。

只锁真正会坏的东西：HTML 结构、本地资源存在、页内锚点可达、外链只指向已核实的仓库地址、
产品页必备要素（源码入口、五步流程、三张真实截图、本地运行与局限说明）。
文案层面的主张不逐句设断言——那是编辑问题，不是契约。
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent / "site"
REPO = "https://github.com/awei-187/OB-powercontext/"
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.errors: list[str] = []
        self.hrefs: list[str] = []
        self.local_refs: list[str] = []
        self.imgs: list[tuple[str, str]] = []
        self.ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if "id" in attributes:
            if attributes["id"] in self.ids:
                self.errors.append(f"重复 id：{attributes['id']}")
            self.ids.add(attributes["id"] or "")
        for key in ("href", "src", "data-full"):
            value = attributes.get(key)
            if value and not value.startswith(("#", "http://", "https://", "//", "mailto:")):
                self.local_refs.append(value)
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


def _content_imgs(page: _Page) -> list[tuple[str, str]]:
    """只看真正承载内容的图；大图查看器里的空 <img> 是运行时模板，不算。"""
    return [(src, alt) for src, alt in page.imgs if src]


def test_page_is_well_formed_and_responsive() -> None:
    html, page = _parse()
    assert page.errors == [], page.errors
    assert page.stack == [], f"有标签没闭合：{page.stack}"
    assert all(alt.strip() for _src, alt in _content_imgs(page)), "每张图都要有 alt"

    css = (SITE / "styles.css").read_text(encoding="utf-8")
    assert css.count("{") == css.count("}"), "CSS 花括号不平衡"
    assert not re.findall(r"url\(\s*['\"]?https?:", css), "CSS 不得引用外部资源"
    assert "@media" in css, "展示页要有窄屏断点"


def test_every_local_asset_exists() -> None:
    """页面上引用的每个本地文件都必须真的在 site/ 里，发布后不能 404。"""
    _html, page = _parse()
    assert page.local_refs, "展示页应当引用本地截图与样式"
    for ref in sorted(set(page.local_refs)):
        assert (SITE / ref).exists(), f"引用的本地资源不存在：{ref}"


def test_in_page_anchors_resolve() -> None:
    _html, page = _parse()
    anchors = [href for href in page.hrefs if href.startswith("#")]
    assert anchors, "展示页应当有页内导航"
    for href in anchors:
        assert href[1:] in page.ids, f"页内锚点不存在：{href}"


def test_external_links_only_point_at_the_confirmed_repo() -> None:
    """外链只允许已核实为 public 的参赛仓库地址。"""
    _html, page = _parse()
    external = [href for href in page.hrefs if re.match(r"^[a-z]+://", href) or href.startswith("//")]
    assert external, "展示页至少要给出仓库入口"
    stray = [href for href in external if not href.startswith(REPO)]
    assert stray == [], f"出现未核实的外链：{stray}"
    assert f"{REPO}tree/competition/qoder-yanxu/qoder" in external, "缺少源码主入口"


def test_product_page_has_the_required_pieces() -> None:
    """参赛介绍页的必备要素：主 CTA、五步流程、三张真实截图、运行与局限。"""
    html, page = _parse()

    shots = re.findall(r'data-full="([^"]+)"', html)
    assert len(shots) == 3 and len(set(shots)) == 3, f"应有三张可放大的真实截图：{shots}"
    assert len(_content_imgs(page)) == 3, f"三张截图都应内嵌缩略图：{page.imgs}"

    assert html.count('class="step"') == 5, "流程应为五步"
    for anchor in ('id="run"', 'id="limits"', 'id="powercontext"'):
        assert anchor in html, f"缺少章节：{anchor}"

    assert "合成演示" in html, "示例数据必须标明合成"
    assert not re.search(r"\d+\s*[–~-]\s*\d+\s*分钟", html), "不得出现未测量的时间区间"
