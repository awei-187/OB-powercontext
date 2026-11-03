# qoder/site/ · 参赛展示页

**已发布：** <https://yanxu-research-022wcl7311d.qoder.zone> （Qoder Sites，访问策略 public）
发布事实（站点 ID、操作 ID、产物 sha256、线上核验记录）见
[evidence/publication.json](../evidence/publication.json)。

## 这是什么

参赛的**产品介绍页**：一句话价值主张、痛点、五步流程、三张真实截图（可点开大图）、
PowerContext 承担的真实功能、本地安装运行、简短局限。
它**不运行研续**——研续是只监听 `127.0.0.1` 的本地工具，线上只有这一份静态介绍。

## 内容

| 文件 | 说明 |
|---|---|
| `index.html` | 页面正文。末尾约 30 行内联脚本只做大图查看器（开 / 关 / Esc / 焦点返回） |
| `styles.css` | 样式，与产品本体同一组设计令牌（纸 / 墨 / 靛 / 玉），含 900px 与 620px 两个窄屏断点 |
| `assets/restore.png` | 真实截图：新会话恢复页（协调人在可见浏览器中拍摄） |
| `assets/history.png` | 真实截图：记忆修订历史抽屉，决策 v1 → v2 |
| `assets/report.png` | 真实截图：组会 / 周报页与来源追溯 |
| `assets/sample-weekly-report.md` | 一份真实导出的周报（合成示例数据），供线上直接阅读 |
| `dist/` | 发布包：上面公开文件的副本，`prepare_site` 的 `webDirectory`。已 gitignore |

三张截图的原件在 `evidence/ui/`（`m2-restore-desktop.png` / `m2-history.png` / `m2-report.png`），
是协调人独立验收时的真实页面 capture；其中的示例项目为合成演示数据。
截图摄于本轮两处小修正（日期输入框默认值、合成演示横幅文案）之前。

## 本地预览

```powershell
cd "E:\Ocean Base\qoder-competition\qoder\site"
```

```powershell
python -m http.server 8125 --bind 127.0.0.1
```

浏览器打开 `http://127.0.0.1:8125/`。

## 重新发布

发布包是源码的副本，改完页面先重建再发布（只创建目录并覆盖已知的静态文件，不递归删除）：

```powershell
cd "E:\Ocean Base\qoder-competition\qoder\site"
```

```powershell
New-Item -ItemType Directory -Force -Path dist\assets | Out-Null
```

```powershell
Copy-Item index.html, styles.css dist\ -Force
```

```powershell
Copy-Item assets\restore.png, assets\history.png, assets\report.png, assets\sample-weekly-report.md dist\assets\ -Force
```

然后用 Qoder Sites 的 `prepare_site`（`projectRoot` 指向 `qoder/site`、`webDirectory` 为 `dist`、
**新的 actionId**、沿用现有 `projectId`）→ `get_publish_status` → `publish_site`，
并把新的发布事实补进 `evidence/publication.json`。内容变了必须用新 actionId，不要复用旧的。

## 写作约定（改文案前请读）

1. **不伪造线上体验**：页面不暗示研续可以在线试用；「本地复现体验」指向安装步骤。
2. **不主张量化收益**：不写节省了多少时间、多少用户——没有测量支撑。
3. **截图只用真 capture**：`assets/` 里三张图来自 `evidence/ui/` 的真实验收截图，
   不得用生成图、示意图或渲染图顶替，也不得裁剪掉界面里的合成数据标注。
4. **合成数据要标注**：页面已说明示例为合成演示；示例周报里的数字是虚构的。
5. **外链只指向已核实地址**：目前只有参赛仓库（已核实 public）与页内锚点、本地资源。
   加新外链前先确认它真实存在且可公开引用。
6. **内部验收细节不上页**：红线清单、未验证状态板、工具错误码等留在
   `DEVELOPMENT.md` 与 `evidence/`，页面只保留读者需要的产品信息与简短局限。
