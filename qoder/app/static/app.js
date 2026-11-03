/* 研续 Yanxu · 前端逻辑。
 *
 * 数据一律来自后端 API（其后端一律来自 PowerContext）。
 * localStorage 只保存「上次选中的项目」这一项 UI 偏好，不承载任何业务数据。
 */
(() => {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  const UI_PREF_KEY = "yanxu.ui.lastProjectId";
  const DEMO_TAG = "【示例】";

  const KIND_ORDER = ["goal", "record", "decision", "open_question", "next_step", "todo", "source"];

  const state = {
    meta: null,
    status: null,
    projects: [],
    currentId: null,
    loadedId: null,
    entries: [],
    hits: null,
    includeInactive: false,
    composerKind: "record",
    editing: null,
    restore: null,
    handoffDraft: null,
    handoffDirty: false,
    nextActionCitation: null,
    ackRevision: null,
    report: null,
  };

  /* ── 工具 ─────────────────────────────────────── */

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;").replaceAll("'", "&#39;");
  }

  function toast(message) {
    const node = $("#toast");
    node.textContent = message;
    node.hidden = false;
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => { node.hidden = true; }, 2800);
  }

  function splitList(value) {
    return String(value || "").split(/[,，]/).map((item) => item.trim()).filter(Boolean);
  }

  function statusPillClass(status) {
    if (status === "done" || status === "resolved" || status === "confirmed") return "pill-done";
    if (status === "blocked") return "pill-blocked";
    if (status === "open") return "pill-open";
    return "";
  }

  function dispositionPillClass(disposition) {
    if (disposition === "blocked") return "pill-blocked";
    if (disposition === "complete") return "pill-done";
    return "pill-open";
  }

  function utf8Bytes(value) {
    return new TextEncoder().encode(String(value ?? "")).length;
  }

  function shortDate(value) {
    return String(value || "").slice(0, 10);
  }

  /* 只有 http / https 才做成可点击链接。javascript:、data: 这类 scheme 即使被 HTML
   * 转义也仍然是可执行的 href，必须由后端 safe_href 判定后前端只认 url_href。 */
  function sourceLinkHtml(entry) {
    const url = String(entry.url || "").trim();
    if (!url) return "";
    if (entry.url_href) {
      return `<a class="entry-link" href="${escapeHtml(entry.url_href)}" target="_blank" rel="noopener noreferrer">${escapeHtml(url)}</a>`;
    }
    return `<span class="entry-url-plain">${escapeHtml(url)}</span>`;
  }

  /* ── 覆盖层：唯一显隐开关是 HTML 的 hidden ─────── */

  const OVERLAYS = {
    history: { nodes: ["#history-backdrop", "#history-drawer"], trap: "#history-drawer", focus: "#history-close" },
    "status-modal": { nodes: ["#status-modal"], trap: "#status-modal", focus: "#status-modal-close" },
    "project-modal": { nodes: ["#project-modal"], trap: "#project-modal", focus: "#project-name-input" },
  };
  const overlayStack = [];

  const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

  function focusableIn(root) {
    if (!root) return [];
    /* 用 getClientRects 而不是 offsetParent 判可见：覆盖层本身是 position:fixed，
     * offsetParent 在固定定位子树里会给出误导结果。 */
    return $$(FOCUSABLE, root).filter((node) => !node.closest("[hidden]") && node.getClientRects().length > 0);
  }

  function openOverlay(name) {
    const spec = OVERLAYS[name];
    if (!spec || overlayStack.includes(name)) return;
    spec.returnFocus = document.activeElement;
    spec.nodes.forEach((selector) => { $(selector).hidden = false; });
    overlayStack.push(name);
    document.body.classList.add("has-overlay");
    const target = $(spec.focus) || $(spec.trap);
    requestAnimationFrame(() => {
      try { target.focus({ preventScroll: true }); } catch { /* 元素可能已被重渲染 */ }
    });
  }

  function closeOverlay(name) {
    const index = overlayStack.indexOf(name);
    if (index === -1) return;
    const spec = OVERLAYS[name];
    spec.nodes.forEach((selector) => { $(selector).hidden = true; });
    overlayStack.splice(index, 1);
    if (!overlayStack.length) document.body.classList.remove("has-overlay");
    const back = spec.returnFocus;
    spec.returnFocus = null;
    if (back && back.isConnected && typeof back.focus === "function") {
      try { back.focus({ preventScroll: true }); } catch { /* 触发元素可能已消失 */ }
    }
  }

  function closeTopOverlay() {
    if (overlayStack.length) closeOverlay(overlayStack[overlayStack.length - 1]);
  }

  /* 初始加载保险：无论 HTML 或缓存里是什么状态，脚本一启动就把全部覆盖层压回隐藏。
   * M1 的阻塞问题是 CSS 的 display 盖掉了 hidden，这里再加一道显式的初始态兜底。 */
  function hideAllOverlays() {
    Object.keys(OVERLAYS).forEach((name) => {
      OVERLAYS[name].nodes.forEach((selector) => { $(selector).hidden = true; });
      OVERLAYS[name].returnFocus = null;
    });
    overlayStack.length = 0;
    document.body.classList.remove("has-overlay");
  }

  function bindOverlayKeys() {
    document.addEventListener("keydown", (event) => {
      if (!overlayStack.length) return;
      if (event.key === "Escape") {
        event.preventDefault();
        closeTopOverlay();
        return;
      }
      if (event.key !== "Tab") return;
      const spec = OVERLAYS[overlayStack[overlayStack.length - 1]];
      const items = focusableIn($(spec.trap));
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });
  }

  /* ── 可见的进行中状态 ─────────────────────────── */

  async function withBusy(button, task) {
    if (!button) return task();
    button.classList.add("is-busy");
    button.setAttribute("aria-busy", "true");
    button.disabled = true;
    try {
      return await task();
    } finally {
      button.classList.remove("is-busy");
      button.removeAttribute("aria-busy");
      button.disabled = false;
    }
  }

  /* ── API 层：真实错误必须浮出水面 ─────────────── */

  class ApiError extends Error {
    constructor(status, body) {
      const error = (body && body.error) || {};
      super(error.message || `请求失败（HTTP ${status}）`);
      this.status = status;
      this.code = error.code || "unknown";
      this.serverCode = error.server_code || "";
      this.requestId = error.request_id || "";
      this.hint = error.hint || "";
      this.details = error.details || null;
    }
  }

  async function api(path, { method = "GET", body } = {}) {
    const init = { method, headers: {} };
    if (body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
    }
    let response;
    try {
      response = await fetch(path, init);
    } catch (networkError) {
      throw new ApiError(0, { error: { code: "network_unreachable", message: `无法连接研续后端：${networkError.message}` } });
    }
    const text = await response.text();
    let payload = null;
    if (text) {
      try { payload = JSON.parse(text); } catch { payload = { error: { code: "non_json_response", message: text.slice(0, 400) } }; }
    }
    if (!response.ok) throw new ApiError(response.status, payload);
    return payload;
  }

  let errorRetry = null;

  function showError(err, title, retry) {
    errorRetry = typeof retry === "function" ? retry : null;
    const banner = $("#error-banner");
    $("#error-title").textContent = title || (err.status === 0 ? "后端不可达" : "调用 PowerContext 失败");
    $("#error-message").textContent = err.message;
    const hintNode = $("#error-hint");
    hintNode.textContent = err.hint || "";
    hintNode.hidden = !err.hint;
    $("#error-retry").hidden = !errorRetry;

    const rows = [
      ["HTTP", err.status || "—"],
      ["错误码", err.code],
      ["服务端码", err.serverCode || "—"],
      ["request_id", err.requestId || "—"],
    ];
    if (err.details) rows.push(["details", JSON.stringify(err.details)]);
    $("#error-meta").innerHTML = rows
      .map(([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`)
      .join("");
    banner.hidden = false;
    banner.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function clearError() {
    errorRetry = null;
    $("#error-retry").hidden = true;
    $("#error-banner").hidden = true;
  }

  /* 抽屉 / 面板内部的错误就地展示，不要求用户先去关覆盖层再回顶部看横幅 */
  function errorBlockHtml(err) {
    const rows = [
      ["HTTP", err.status || "—"],
      ["错误码", err.code],
      ["服务端码", err.serverCode || "—"],
      ["request_id", err.requestId || "—"],
    ];
    return `<div class="banner banner-error" style="margin:0">
      <div class="banner-head"><strong>调用失败</strong></div>
      <p>${escapeHtml(err.message)}</p>
      ${err.hint ? `<p class="banner-hint">${escapeHtml(err.hint)}</p>` : ""}
      <dl class="banner-meta">${rows.map(([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`).join("")}</dl>
    </div>`;
  }

  /* ── 系统状态 ─────────────────────────────────── */

  async function loadStatus() {
    try {
      state.status = await api("/api/system/status");
      const ok = state.status.powercontext_running;
      $("#status-dot").className = `dot ${ok ? "dot-ok" : "dot-bad"}`;
      /* 首屏只说人话：连上了没有、数据在哪。版本 / 后端 / 检索方式属于技术细节，
       * 收进「技术详情」，不常驻顶栏；「不需要模型密钥」是设计前提，不是警告。 */
      $("#status-text").textContent = ok ? "记忆已连接 · 数据全在本机" : "PowerContext 未连接";
      if (!ok) {
        showError(new ApiError(503, { error: { code: "powercontext_down", message: "内嵌 PowerContext Server 没有就绪，请查看启动日志。" } }), "无法连接记忆层");
      }
    } catch (err) {
      state.status = null;
      $("#status-dot").className = "dot dot-bad";
      $("#status-text").textContent = "PowerContext 未连接";
      showError(err, "无法读取 PowerContext 状态", loadStatus);
    }
  }

  function renderStatusModal() {
    const status = state.status;
    const body = $("#status-modal-body");
    if (!status) {
      body.innerHTML = `<p class="muted">状态不可用。</p>`;
      return;
    }
    const caps = status.capabilities || {};
    const rows = [
      ["PowerContext 版本", status.powercontext_version],
      ["内嵌 Server 地址", status.powercontext_base_url],
      ["Server 运行中", String(status.powercontext_running)],
      ["存储后端", status.storage_backend],
      ["记忆数据库", status.database_path],
      ["项目注册表", status.registry_path],
      ["自动记忆提取", String(caps.memory_extraction)],
      ["可用检索方式", (caps.search_modes || []).join(", ")],
      ["交接生成（需模型）", String(caps.handoff_generation)],
      ["已配置模型密钥", String(status.model_keys_configured)],
      ["可用工件族", (caps.artifact_families || []).join(", ")],
    ];
    body.innerHTML =
      `<table class="status-table"><tbody>${rows
        .map(([label, value]) => `<tr><th>${escapeHtml(label)}</th><td>${escapeHtml(value)}</td></tr>`)
        .join("")}</tbody></table>` +
      (status.notes?.length
        ? `<ul class="status-notes">${status.notes.map((note) => `<li>${escapeHtml(note)}</li>`).join("")}</ul>`
        : "");
  }

  /* ── 项目 ─────────────────────────────────────── */

  async function loadProjects() {
    state.projects = await api("/api/projects");
    if (state.currentId && !state.projects.some((item) => item.project_id === state.currentId)) {
      state.currentId = null;
      state.loadedId = null;
    }
    if (!state.currentId && state.projects.length) {
      const preferred = localStorage.getItem(UI_PREF_KEY);
      state.currentId = state.projects.some((item) => item.project_id === preferred)
        ? preferred
        : state.projects[0].project_id;
    }
    renderProjects();
    renderWorkspaceShell();
  }

  function isDemoProject(project) {
    return project.name.includes(DEMO_TAG) || /合成(演示)?数据/.test(project.summary || "");
  }

  function renderProjects() {
    const list = $("#project-list");
    if (!state.projects.length) {
      list.innerHTML = `<li class="muted" style="font-size:12.5px;padding:8px 2px">还没有项目。点右上角「新建项目」开始。</li>`;
      return;
    }
    const labels = Object.fromEntries((state.meta?.kinds || []).map((item) => [item.value, item.label]));
    list.innerHTML = state.projects.map((project) => {
      const counts = KIND_ORDER
        .filter((kind) => project.counts?.[kind])
        .map((kind) => `<span class="mini-tag">${escapeHtml(labels[kind] || kind)} ${project.counts[kind]}</span>`)
        .join("");
      const handoff = project.last_handoff_revision
        ? `<span class="mini-tag">交接 r${project.last_handoff_revision}</span>` : "";
      return `<li class="project-item${project.project_id === state.currentId ? " is-active" : ""}${project.archived ? " is-archived" : ""}"
                  data-id="${escapeHtml(project.project_id)}" tabindex="0" role="button">
        <div class="project-item-name">${escapeHtml(project.name)}</div>
        <div class="project-item-meta"><span>更新于 ${escapeHtml(shortDate(project.updated_at))}</span>${project.archived ? "<span>已归档</span>" : ""}</div>
        <div class="project-item-counts">${counts || `<span class="mini-tag is-zero">暂无记忆</span>`}${handoff}</div>
      </li>`;
    }).join("");

    $$(".project-item", list).forEach((node) => {
      node.addEventListener("click", () => selectProject(node.dataset.id));
      node.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") { event.preventDefault(); selectProject(node.dataset.id); }
      });
    });
  }

  function renderWorkspaceShell() {
    const project = state.projects.find((item) => item.project_id === state.currentId);
    const has = Boolean(project);
    $("#empty-state").hidden = has;
    $("#project-view").hidden = !has;
    if (!has) return;

    $("#project-name").textContent = project.name;
    $("#project-summary").textContent = project.summary || "（未填写简介）";
    $("#archive-project").textContent = project.archived ? "取消归档" : "归档";
    $("#demo-banner").hidden = !isDemoProject(project);

    const techRows = [
      ["Scope ID", project.scope_id],
      ["项目 ID", project.project_id],
      ["创建于", project.created_at],
      ["更新于", project.updated_at],
      ["归档状态", project.archived ? "已归档" : "活跃"],
      ["活跃记忆条数", String(Object.values(project.counts || {}).reduce((sum, value) => sum + value, 0))],
      ["最新交接 Revision", project.last_handoff_revision ? `r${project.last_handoff_revision}` : "尚无交接"],
    ];
    $("#project-tech-body").innerHTML = techRows
      .map(([label, value]) => `<tr><th>${escapeHtml(label)}</th><td>${escapeHtml(value)}</td></tr>`)
      .join("");
  }

  async function selectProject(projectId, { force = false } = {}) {
    if (!force && state.loadedId === projectId) {
      state.currentId = projectId;
      renderProjects();
      return;
    }
    state.currentId = projectId;
    state.loadedId = projectId;
    state.hits = null;
    state.editing = null;
    state.restore = null;
    state.report = null;
    state.handoffDirty = false;
    state.ackRevision = null;
    localStorage.setItem(UI_PREF_KEY, projectId);
    renderProjects();
    renderWorkspaceShell();
    renderContinueHero();
    resetReportPanel();
    resetAckPanel();
    resetEntryForm();
    clearError();
    $("#restore-body").innerHTML = `<p class="busy-line">正在从 PowerContext 读取…</p>`;
    $("#handoff-current-body").innerHTML = `<p class="busy-line">正在读取交接…</p>`;
    $("#entry-groups").innerHTML = `<p class="busy-line">正在读取记忆…</p>`;
    switchTab("ledger");
    await Promise.all([loadEntries(), loadRestore(), loadHandoffPanel()]);
  }

  function switchTab(name) {
    state.activeTab = name;
    $$("#tabs .tab").forEach((tab) => tab.classList.toggle("is-active", tab.dataset.tab === name));
    $$(".panel").forEach((panel) => panel.classList.toggle("is-active", panel.dataset.panel === name));
  }

  /* ── 继续工作（首屏主视图） ───────────────────── */

  function renderContinueHero() {
    const hero = $("#continue-hero");
    const project = state.projects.find((item) => item.project_id === state.currentId);
    const brief = state.restore;
    if (!project || !brief) { hero.hidden = true; return; }

    const handoff = brief.handoff;
    const button = $("#continue-open");
    if (handoff && handoff.status === "resolved") {
      $("#continue-objective").textContent = handoff.objective || "（交接未写目标）";
      const next = handoff.next_action?.text || "";
      $("#continue-next").textContent = next;
      $("#continue-next").hidden = !next;
      const pill = $("#continue-disposition");
      pill.textContent = `上次交接 r${handoff.selected_revision?.revision ?? "?"} · ${handoff.disposition_label || handoff.disposition}`;
      pill.className = `pill ${dispositionPillClass(handoff.disposition)}`;
      button.textContent = "查看恢复简报";
      button.dataset.goto = "restore";
      hero.hidden = false;
      return;
    }

    const goal = (brief.goals || [])[0];
    if (!goal) { hero.hidden = true; return; }
    $("#continue-objective").textContent = goal.body || goal.title || "（目标为空）";
    $("#continue-next").hidden = true;
    const pill = $("#continue-disposition");
    pill.textContent = "尚无交接";
    pill.className = "pill";
    button.textContent = "去保存交接";
    button.dataset.goto = "handoff";
    hero.hidden = false;
  }

  /* ── 台账 ─────────────────────────────────────── */

  function renderKindPicker() {
    const picker = $("#kind-picker");
    picker.innerHTML = (state.meta?.kinds || [])
      .map((kind) => `<button type="button" class="kind-chip${kind.value === state.composerKind ? " is-active" : ""}"
                              data-kind="${escapeHtml(kind.value)}">${escapeHtml(kind.label)}</button>`)
      .join("");
    $$(".kind-chip", picker).forEach((node) => {
      node.addEventListener("click", () => {
        state.composerKind = node.dataset.kind;
        renderKindPicker();
      });
    });
    applyKindDefaults();
  }

  function applyKindDefaults() {
    const kind = state.composerKind;
    $("#field-url").hidden = kind !== "source";
    const statusSelect = $("#entry-status");
    const presets = {
      goal: ["confirmed", "open"],
      record: ["", "open", "done"],
      decision: ["confirmed", "open"],
      open_question: ["open", "resolved", "blocked"],
      next_step: ["open", "done", "dropped"],
      todo: ["open", "done"],
      source: ["", "confirmed"],
    };
    const allowed = presets[kind] || [""];
    const labels = Object.fromEntries((state.meta?.statuses || []).map((item) => [item.value, item.label]));
    const previous = state.editing?.status ?? statusSelect.value;
    statusSelect.innerHTML = allowed
      .map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(labels[value] || value || "未标注")}</option>`)
      .join("");
    if (allowed.includes(previous)) statusSelect.value = previous;
    $("#entry-title").placeholder = {
      goal: "这个项目要回答什么问题",
      record: "这次做了什么实验 / 工作",
      decision: "确认了什么",
      open_question: "还没解决的问题",
      next_step: "下一步动作",
      todo: "待办事项",
      source: "资料 / 文献名称",
    }[kind] || "标题";
  }

  function updateByteCounter() {
    const limit = state.meta?.memory_text_byte_limit ?? 8192;
    const text = ["#entry-title", "#entry-body", "#entry-tags", "#entry-url", "#entry-reason"]
      .map((selector) => $(selector).value).join("");
    const bytes = utf8Bytes(text);
    const node = $("#byte-counter");
    node.textContent = `${bytes} / ${limit} 字节`;
    node.className = `byte-counter${bytes > limit ? " is-over" : bytes > limit * 0.85 ? " is-near" : ""}`;
  }

  function updateGoalByteCounter() {
    const bytes = utf8Bytes($("#project-goal-input").value);
    const node = $("#project-goal-bytes");
    node.textContent = `${bytes} 字节`;
    node.className = `byte-counter${bytes > 8100 ? " is-over" : bytes > 7000 ? " is-near" : ""}`;
  }

  function entryFormPayload() {
    return {
      kind: state.composerKind,
      title: $("#entry-title").value.trim(),
      body: $("#entry-body").value,
      date: $("#entry-date").value,
      status: $("#entry-status").value,
      tags: splitList($("#entry-tags").value),
      url: $("#entry-url").value.trim(),
      refs: [],
      reason: $("#entry-reason").value.trim(),
    };
  }

  function resetEntryForm() {
    $("#entry-form").reset();
    state.editing = null;
    $("#composer-title").textContent = "录入一条记忆";
    $("#entry-submit").textContent = "保存记录";
    $("#entry-date").value = new Date().toISOString().slice(0, 10);
    $("#entry-reason").placeholder = "写入变更历史，日后回溯用";
    applyKindDefaults();
    updateByteCounter();
  }

  function startEdit(entry) {
    state.editing = entry;
    state.composerKind = entry.kind;
    renderKindPicker();
    $("#composer-title").textContent = `修订记忆 · ${entry.ref_label}`;
    $("#entry-title").value = entry.title;
    $("#entry-body").value = entry.body;
    $("#entry-date").value = entry.date;
    $("#entry-status").value = entry.status;
    $("#entry-tags").value = entry.tags.join(", ");
    $("#entry-url").value = entry.url;
    $("#entry-reason").value = "";
    $("#entry-reason").placeholder = "本次修订的依据（必填才好回溯）";
    $("#entry-submit").textContent = "提交修订";
    updateByteCounter();
    switchTab("ledger");
    $("#entry-form").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function entryHtml(entry, extra) {
    const inactive = entry.state === "inactive";
    const tags = entry.tags.map((tag) => `<span class="mini-tag">${escapeHtml(tag)}</span>`).join("");
    const link = sourceLinkHtml(entry);
    const ops = entry.change_ops?.length ? `<span class="entry-ref">${escapeHtml(entry.change_ops.join(" → "))}</span>` : "";
    const score = extra?.score !== undefined
      ? `<span class="pill">FTS ${Number(extra.score).toFixed(3)} · ${escapeHtml((extra.matched_by || []).join("/"))}</span>` : "";
    return `<article class="entry${inactive ? " is-inactive" : ""}" data-kind="${escapeHtml(entry.kind)}"
                     data-entry-id="${escapeHtml(entry.citation.entry_id)}">
      <div class="entry-head">
        <span class="entry-title">${escapeHtml(entry.title || "（无标题）")}</span>
        <span class="entry-date">${escapeHtml(entry.date || "")}</span>
      </div>
      ${entry.body ? `<p class="entry-body">${escapeHtml(entry.body)}</p>` : ""}
      ${link ? `<p style="margin:6px 0 0">${link}</p>` : ""}
      ${entry.reason ? `<p class="entry-reason">${escapeHtml(entry.reason)}</p>` : ""}
      <div class="entry-foot">
        <span class="entry-ref">${escapeHtml(entry.ref_label)}</span>
        ${entry.status ? `<span class="pill ${statusPillClass(entry.status)}">${escapeHtml(entry.status_label)}</span>` : ""}
        ${inactive ? `<span class="pill pill-inactive">已退役</span>` : ""}
        ${score}
        <span class="entry-tags">${tags}</span>
        ${ops}
        <span class="entry-actions">
          <button class="btn btn-ghost btn-sm" data-act="history" type="button">历史</button>
          ${inactive
            ? `<button class="btn btn-ghost btn-sm" data-act="reactivate" type="button">恢复</button>`
            : `<button class="btn btn-ghost btn-sm" data-act="edit" type="button">修订</button>
               <button class="btn btn-danger btn-sm" data-act="retire" type="button">退役</button>`}
        </span>
      </div>
    </article>`;
  }

  function renderEntries() {
    const container = $("#entry-groups");
    const labels = Object.fromEntries((state.meta?.kinds || []).map((item) => [item.value, item.label]));

    if (state.hits) {
      const summary = $("#search-summary");
      summary.hidden = false;
      summary.textContent = `全文检索命中 ${state.hits.length} 条（检索限定在本项目内）。`;
      $("#search-clear").hidden = false;
      if (!state.hits.length) {
        container.innerHTML = `<p class="group-empty">没有命中。未配置 embedding 模型时只有全文检索可用，试试更具体的关键词。</p>`;
        return;
      }
      container.innerHTML = `<div><div class="entry-list">${state.hits
        .map((hit) => entryHtml(hit.entry, hit)).join("")}</div></div>`;
      bindEntryActions(container, (entryId) => state.hits.map((hit) => hit.entry).find((item) => item.citation.entry_id === entryId));
      return;
    }

    $("#search-summary").hidden = true;
    $("#search-clear").hidden = true;

    if (!state.entries.length) {
      container.innerHTML = `<p class="group-empty">这个项目还没有记忆。从左侧录入第一条开始。</p>`;
      return;
    }

    const grouped = new Map();
    for (const entry of state.entries) {
      if (!grouped.has(entry.kind)) grouped.set(entry.kind, []);
      grouped.get(entry.kind).push(entry);
    }
    const order = [...KIND_ORDER.filter((kind) => grouped.has(kind)), ...[...grouped.keys()].filter((kind) => !KIND_ORDER.includes(kind))];
    container.innerHTML = order.map((kind) => {
      const items = grouped.get(kind);
      return `<section>
        <div class="entry-group-head">
          <h4>${escapeHtml(labels[kind] || kind)}</h4>
          <span class="entry-group-count">${items.length} 条</span>
        </div>
        <div class="entry-list">${items.map((entry) => entryHtml(entry)).join("")}</div>
      </section>`;
    }).join("");
    bindEntryActions(container, (entryId) => state.entries.find((item) => item.citation.entry_id === entryId));
  }

  function bindEntryActions(container, findEntry) {
    $$("[data-act]", container).forEach((button) => {
      button.addEventListener("click", async () => {
        const entryId = button.closest(".entry").dataset.entryId;
        const entry = findEntry(entryId);
        if (!entry) return;
        const action = button.dataset.act;
        try {
          if (action === "edit") startEdit(entry);
          else if (action === "history") await openHistory(entry);
          else if (action === "retire") await retireEntry(entry, button);
          else if (action === "reactivate") await reactivateEntry(entry, button);
        } catch (err) { showError(err); }
      });
    });
  }

  async function loadEntries() {
    if (!state.currentId) return;
    const params = new URLSearchParams({ include_inactive: String(state.includeInactive) });
    try {
      state.entries = await api(`/api/projects/${state.currentId}/entries?${params}`);
      renderEntries();
    } catch (err) {
      $("#entry-groups").innerHTML = errorBlockHtml(err);
      showError(err, "读取记忆失败", loadEntries);
    }
  }

  async function retireEntry(entry, button) {
    const reason = window.prompt("退役原因（会写入 PowerContext 变更历史）", "");
    if (reason === null) return;
    await withBusy(button, async () => {
      await api(`/api/projects/${state.currentId}/entries/${entry.citation.entry_id}/retire`, {
        method: "POST", body: { citation: entry.citation, reason: reason.trim() },
      });
    });
    toast("已退役 · 历史完整保留");
    await refreshAfterWrite();
  }

  async function reactivateEntry(entry, button) {
    await withBusy(button, async () => {
      await api(`/api/projects/${state.currentId}/entries/${entry.citation.entry_id}/reactivate`, {
        method: "POST", body: { citation: entry.citation, reason: "在研续中重新激活" },
      });
    });
    toast("已重新激活");
    await refreshAfterWrite();
  }

  /* ── 修订历史抽屉 ─────────────────────────────── */

  async function openHistory(entry) {
    $("#history-body").innerHTML = `<p class="busy-line">正在从 PowerContext 读取修订历史…</p>`;
    openOverlay("history");
    try {
      const history = await api(`/api/projects/${state.currentId}/entries/${entry.citation.entry_id}/history`);
      renderHistory(history);
    } catch (err) {
      $("#history-body").innerHTML = errorBlockHtml(err);
    }
  }

  function renderHistory(history) {
    const snapshots = (history.snapshots || []).slice().reverse();
    const unavailable = history.unavailable || [];

    const unavailableHtml = unavailable.length
      ? `<div class="history-note">
           有 ${unavailable.length} 个历史版本当前读不回来。研续不会把它们悄悄丢掉——下面逐条列出，
           变更日志仍然完整。
         </div>` +
        unavailable.map((item) => `<div class="snapshot is-unavailable">
            <div class="snapshot-head">
              <span>工件 r${item.revision} · ${escapeHtml(item.op)}</span>
              <span>${escapeHtml((item.entry_version_id || "").slice(-12))}</span>
            </div>
            <div class="snapshot-unavailable-note">读不回这个版本：${escapeHtml(item.error)}</div>
          </div>`).join("")
      : "";

    $("#history-body").innerHTML =
      `<p class="muted" style="font-size:12.5px">
         类型 ${escapeHtml(history.kind_label)} · entry_id
         <code>${escapeHtml(history.entry_id)}</code>
       </p>` +
      (snapshots.length
        ? snapshots.map((snapshot, index) => {
            const isCurrent = index === 0;
            return `<div class="snapshot${isCurrent ? " is-current" : ""}">
              <div class="snapshot-head">
                <span>${escapeHtml(snapshot.ref_label)}${isCurrent ? " · 当前" : ""}</span>
                <span>条目版本 v${snapshot.version} · 工件 r${snapshot.citation.memory_ref.revision} · ${escapeHtml(snapshot.state)}</span>
              </div>
              <div class="snapshot-title">${escapeHtml(snapshot.title || "（无标题）")}</div>
              ${snapshot.body ? `<div class="snapshot-body">${escapeHtml(snapshot.body)}</div>` : ""}
              ${snapshot.reason ? `<div class="entry-reason">${escapeHtml(snapshot.reason)}</div>` : ""}
              <details><summary class="muted" style="font-size:11.5px;cursor:pointer;margin-top:8px">PowerContext 原始 memory text</summary>
                <div class="snapshot-text">${escapeHtml(snapshot.text)}</div></details>
            </div>`;
          }).join("")
        : `<p class="brief-empty">没有可读回的历史快照。</p>`) +
      unavailableHtml +
      `<h4 style="margin-top:18px">变更日志（list_memory_changes）</h4>
       <table class="change-table"><thead><tr>
         <th>工件版本</th><th>操作</th><th>原因</th><th>entry_version_id</th>
       </tr></thead><tbody>${(history.changes || []).map((change) => `<tr>
         <td class="mono">r${change.revision}</td>
         <td class="mono">${escapeHtml(change.op)}</td>
         <td>${escapeHtml(change.reason || "—")}</td>
         <td class="mono">${escapeHtml((change.to_entry_version_id || "").slice(-12))}</td>
       </tr>`).join("")}</tbody></table>`;
  }

  /* ── 恢复简报 ─────────────────────────────────── */

  function briefCard(title, items, renderItem, emptyText, options = {}) {
    const body = items?.length
      ? `<ul class="brief-list">${items.map(renderItem).join("")}</ul>`
      : `<p class="brief-empty">${escapeHtml(emptyText)}</p>`;
    const note = options.note ? `<p class="brief-closed-note">${escapeHtml(options.note)}</p>` : "";
    const cls = ["brief-card", options.closed ? "is-closed" : "", options.dropped ? "is-dropped" : ""].filter(Boolean).join(" ");
    return `<div class="${cls}"><h4>${escapeHtml(title)} <span class="count">${items?.length || 0}</span></h4>${body}${note}</div>`;
  }

  function itemLine(entry) {
    return `<li>
      <span class="item-title">${escapeHtml(entry.title || entry.body?.slice(0, 60) || "（空）")}</span>
      ${entry.title && entry.body ? `<span class="item-body">${escapeHtml(entry.body)}</span>` : ""}
      <span class="item-ref">${escapeHtml(entry.ref_label)}${entry.date ? ` · ${escapeHtml(entry.date)}` : ""}${entry.status_label ? ` · ${escapeHtml(entry.status_label)}` : ""}</span>
    </li>`;
  }

  function sourceLine(entry) {
    return `<li>
      <span class="item-title">${escapeHtml(entry.title || "未命名资料")}</span>
      ${sourceLinkHtml(entry)}
      ${entry.body ? `<span class="item-body">${escapeHtml(entry.body)}</span>` : ""}
      <span class="item-ref">${escapeHtml(entry.ref_label)}</span>
    </li>`;
  }

  async function loadRestore() {
    if (!state.currentId) return;
    $("#restore-body").innerHTML = `<p class="busy-line">正在从 PowerContext 读取…</p>`;
    try {
      state.restore = await api(`/api/projects/${state.currentId}/restore`);
      renderRestore(state.restore);
      renderContinueHero();
    } catch (err) {
      state.restore = null;
      renderContinueHero();
      $("#restore-body").innerHTML = errorBlockHtml(err);
      showError(err, "恢复工作失败", loadRestore);
    }
  }

  function renderRestore(brief) {
    const handoff = brief.handoff;
    const resolved = handoff && handoff.status === "resolved";

    const hero = resolved
      ? `<div class="brief-hero">
           <h4>上次交接 · Revision ${handoff.selected_revision?.revision ?? "?"}</h4>
           <p class="brief-objective">${escapeHtml(handoff.objective)}</p>
           <div class="brief-hero-meta">
             <span>判定：${escapeHtml(handoff.disposition_label || handoff.disposition)}</span>
             <span>信任级别：${escapeHtml(handoff.trust)}</span>
             ${handoff.next_action ? `<span>下一步：${escapeHtml(handoff.next_action.text)}</span>` : ""}
           </div>
           ${handoff.evidence_checks?.length ? `<ul class="evidence-list">${handoff.evidence_checks.map((check) => `
             <li class="${check.status === "available" ? "evidence-ok" : "evidence-bad"}">
               <span>${check.status === "available" ? "✓" : "✗"}</span>
               <span>${escapeHtml(check.claim)}${check.state_index !== null ? ` #${check.state_index}` : ""} 所引证据${check.status === "available" ? "仍可回溯" : "已不可用"}</span>
             </li>`).join("")}</ul>` : ""}
           ${handoff.omissions?.length ? `<p style="margin:12px 0 0;font-size:12.5px;color:var(--ink-soft)">
             交接时明确未覆盖：${handoff.omissions.map(escapeHtml).join("；")}</p>` : ""}
         </div>`
      : `<div class="brief-hero">
           <h4>上次交接</h4>
           <p class="brief-objective" style="font-size:15px;color:var(--ink-soft)">这个项目还没有保存过交接。</p>
           <p style="margin:8px 0 0;font-size:12.5px;color:var(--ink-faint)">
             到「保存交接」标签页写下当前状态，下次坐下时就能一屏恢复。</p>
         </div>`;

    const prepared = brief.prepared_context
      ? `<div class="brief-card">
           <h4>PowerContext 打包上下文 <span class="count">${escapeHtml(brief.prepared_context.status)} · ${brief.prepared_context.content_bytes} B</span></h4>
           ${brief.prepared_context.content
             ? `<div class="context-box">${escapeHtml(brief.prepared_context.content)}</div>`
             : `<p class="brief-empty">prepare_context 返回 ${escapeHtml(brief.prepared_context.status)}，暂无可打包内容。</p>`}
         </div>`
      : "";

    $("#restore-body").innerHTML = hero +
      `<div class="brief-grid">` +
      briefCard("研究目标", brief.goals, itemLine, "尚未录入目标") +
      briefCard("已确认决策", brief.decisions, itemLine, "尚无已确认决策") +
      briefCard("未解决问题", brief.open_questions, itemLine, "没有未解决问题") +
      briefCard("下一步（仍可行动）", brief.next_steps, itemLine, "尚未规划下一步") +
      briefCard("未完成待办", brief.todos_open, itemLine, "待办已清空") +
      briefCard("最近工作记录", brief.recent_records, itemLine, "尚无工作记录") +
      briefCard("资料出处", brief.sources, sourceLine, "尚未登记资料出处") +
      briefCard("已解决问题", brief.resolved_questions, itemLine, "尚无已解决的问题", {
        closed: true,
        note: "留档回溯用，不算待办。研续不记录解决发生的时间。",
      }) +
      briefCard("已关闭的下一步", brief.closed_next_steps, itemLine, "尚无已完成 / 已放弃的下一步", {
        closed: true,
        dropped: true,
        note: "含已完成与已放弃；已放弃的下一步不是待完成项。",
      }) +
      prepared +
      `</div>
       <p class="muted" style="font-size:11.5px;margin-top:4px">
         生成于 ${escapeHtml(brief.generated_at)} · 本项目内共 ${brief.entry_total} 条活跃记忆 ·
         全部内容由 PowerContext 实时读回
       </p>`;
  }

  /* ── 交接 ─────────────────────────────────────── */

  function renderDispositionOptions() {
    $("#handoff-disposition").innerHTML = (state.meta?.dispositions || [])
      .map((item) => `<option value="${escapeHtml(item.value)}">${escapeHtml(item.label)}</option>`)
      .join("");
  }

  function claimRow(claim) {
    const cited = Boolean(claim.citation);
    const cite = cited
      ? `<span class="claim-cite" title="已引用真实记忆条目，将以 basis=verified 提交">✓ ${escapeHtml(shortRef(claim.citation))}</span>`
      : `<span class="claim-cite is-declared" title="本人陈述，以 basis=declared 提交">declared</span>`;
    return `<div class="claim-row"${cited ? ` data-citation="${escapeHtml(JSON.stringify(claim.citation))}"` : ""}
         data-cited-text="${escapeHtml((claim.text || "").trim())}">
      <input type="text" class="claim-text" maxlength="4000" value="${escapeHtml(claim.text || "")}" placeholder="一条已确认的状态">
      ${cite}
      <button type="button" class="claim-remove" aria-label="删除">×</button>
    </div>`;
  }

  /* 引用绑定在行上，不靠文本回查：正文一旦被改，所引记忆就不再支撑这句话，
   * 必须当场降级为 declared，否则会把改过的话以 verified 提交给 PowerContext。 */
  function syncClaimCitation(row) {
    const input = row.querySelector("input");
    if (!input) return;
    const chip = $(".claim-cite", row);
    if (!row.dataset.citation) {
      if (chip) {
        chip.className = "claim-cite is-declared";
        chip.textContent = "declared";
        chip.title = "本人陈述，以 basis=declared 提交";
      }
      return;
    }
    if (input.value.trim() === (row.dataset.citedText || "")) {
      if (chip) {
        chip.className = "claim-cite";
        chip.textContent = `✓ ${shortRef(JSON.parse(row.dataset.citation))}`;
        chip.title = "已引用真实记忆条目，将以 basis=verified 提交";
      }
      return;
    }
    delete row.dataset.citation;
    if (input.id === "handoff-next") state.nextActionCitation = null;
    if (chip) {
      chip.className = "claim-cite is-declared";
      chip.textContent = "declared";
      chip.title = "正文已与所引记忆不一致，自动降级为本人陈述（basis=declared）";
    }
  }

  function shortRef(citation) {
    const tail = citation.entry_id.split("_").pop().slice(0, 8);
    return `mem_${tail}`;
  }

  function renderHandoffDraft() {
    const draft = state.handoffDraft;
    if (!draft) return;
    $("#handoff-objective").value = draft.objective || "";
    $("#handoff-disposition").value = draft.disposition || "continuable";
    $("#handoff-state").innerHTML = (draft.state || []).map((claim) => claimRow(claim)).join("");
    $("#handoff-next").value = draft.next_action?.text || "";
    state.nextActionCitation = draft.next_action?.citation || null;
    renderNextActionCite();
    $("#handoff-omissions").innerHTML = (draft.omissions || []).map((text) => omissionRow(text)).join("");
    bindClaimRows();
    state.handoffDirty = false;
  }

  function renderNextActionCite() {
    const row = $("#handoff-next").closest(".claim-row");
    const citation = state.nextActionCitation;
    const text = $("#handoff-next").value.trim();
    let chip = $(".claim-cite", row);
    if (citation) {
      row.dataset.citation = JSON.stringify(citation);
      row.dataset.citedText = text;
      if (!chip) {
        chip = document.createElement("span");
        chip.className = "claim-cite";
        row.appendChild(chip);
      }
      chip.textContent = `✓ ${shortRef(citation)}`;
      chip.title = "已引用真实记忆条目，将以 basis=verified 提交";
      chip.classList.remove("is-declared");
    } else {
      delete row.dataset.citation;
      row.dataset.citedText = "";
      if (chip) {
        chip.className = "claim-cite is-declared";
        chip.textContent = "declared";
        chip.title = "本人陈述，以 basis=declared 提交";
      }
    }
  }

  function omissionRow(text) {
    return `<div class="claim-row">
      <input type="text" class="omission-text" maxlength="4000" value="${escapeHtml(text || "")}" placeholder="明确未覆盖或未解决的问题">
      <button type="button" class="claim-remove" aria-label="删除">×</button>
    </div>`;
  }

  function bindClaimRows() {
    $$("#handoff-state .claim-remove, #handoff-omissions .claim-remove").forEach((button) => {
      button.addEventListener("click", () => button.closest(".claim-row").remove());
    });
  }

  function rowCitation(row) {
    if (!row.dataset.citation) return null;
    try {
      return JSON.parse(row.dataset.citation);
    } catch {
      return null;
    }
  }

  function collectClaims(containerSelector, textClass) {
    return $$(`${containerSelector} .claim-row`).map((row) => ({
      text: $(`.${textClass}`, row).value.trim(),
      citation: rowCitation(row),
    })).filter((item) => item.text);
  }

  async function loadHandoffPanel({ refill = true } = {}) {
    if (!state.currentId) return;
    try {
      const requests = [api(`/api/projects/${state.currentId}/handoff`)];
      if (refill) requests.push(api(`/api/projects/${state.currentId}/handoff/draft`));
      const [current, draft] = await Promise.all(requests);
      renderCurrentHandoff(current);
      if (draft) {
        state.handoffDraft = draft;
        renderHandoffDraft();
      }
    } catch (err) {
      $("#handoff-current-body").innerHTML = errorBlockHtml(err);
      showError(err, "读取交接状态失败", () => loadHandoffPanel({ refill }));
    }
  }

  /* 台账里新写入的记忆必须立刻反映到「继续工作」「恢复工作」和「保存交接」的预填上；
   * 但用户已经在交接表单里动过手就不能覆盖，此时只刷新只读的当前交接状态，
   * 预填留给显式的「按当前记忆重新预填」按钮。 */
  async function refreshActivePanel(name) {
    if (!state.currentId) return;
    if (name === "ledger") await loadEntries();
    else if (name === "restore") await loadRestore();
    else if (name === "handoff") await loadHandoffPanel({ refill: !state.handoffDirty });
  }

  async function refreshAfterWrite() {
    clearError();
    await Promise.all([loadProjects(), loadEntries(), loadRestore()]);
    await loadHandoffPanel({ refill: !state.handoffDirty });
  }

  function renderCurrentHandoff(handoff) {
    const body = $("#handoff-current-body");
    if (!handoff || handoff.status !== "resolved") {
      body.classList.add("muted");
      body.innerHTML = `<p class="brief-empty">当前没有已提交的交接。</p>`;
      setAckRevision(null);
      return;
    }
    body.classList.remove("muted");
    const ref = handoff.selected_revision || handoff.current_revision;
    body.innerHTML = `
      <p style="font-size:12.5px;color:var(--ink-faint);margin-bottom:10px">
        Revision ${ref?.revision ?? "?"} · 判定
        <span class="pill ${dispositionPillClass(handoff.disposition)}">${escapeHtml(handoff.disposition_label)}</span>
      </p>
      <div class="snapshot-title" style="margin-bottom:8px">${escapeHtml(handoff.objective)}</div>
      <ul class="statement-list">${handoff.state.map((item) => `<li>${escapeHtml(item.text)}
        <div class="statement-cites">${item.citations.map((cite) => `<span class="cite-chip">${escapeHtml(cite.kind)} · ${escapeHtml(cite.summary)}</span>`).join("")}</div>
      </li>`).join("")}</ul>
      ${handoff.next_action ? `<p style="margin-top:12px;font-size:13px"><strong>下一步：</strong>${escapeHtml(handoff.next_action.text)}</p>` : ""}
      ${handoff.omissions?.length ? `<p style="margin-top:8px;font-size:12.5px;color:var(--ink-soft)">
        <strong>未覆盖：</strong>${handoff.omissions.map(escapeHtml).join("；")}</p>` : ""}`;
    setAckRevision(ref);
  }

  /* 接手必须绑定「用户真正看到并核对过的那个 Revision」。这里记录它，提交时原样回传；
   * 后端发现它已不是最新版会返回 409，前端据此刷新，绝不悄悄换成最新版。 */
  function setAckRevision(ref) {
    state.ackRevision = ref || null;
    const node = $("#ack-version");
    if (!state.ackRevision) {
      node.textContent = "尚未读取交接版本，无法接手。";
      $("#ack-submit").disabled = true;
      return;
    }
    $("#ack-submit").disabled = false;
    node.innerHTML =
      `你将接手 <code>Revision ${state.ackRevision.revision}</code>` +
      `（<code>${escapeHtml(state.ackRevision.family)}/${escapeHtml(state.ackRevision.artifact_id)}</code>）` +
      ` · 请先核对上方「当前交接状态」再确认。`;
  }

  function resetAckPanel() {
    setAckRevision(null);
    ["#ack-live-state", "#ack-capability", "#ack-authorization"].forEach((selector) => { $(selector).checked = false; });
    $("#ack-message").value = "";
    $("#ack-status").value = "accepted";
    $("#ack-result").hidden = true;
    $("#ack-result").classList.remove("is-warn");
  }

  async function submitAcknowledge(button) {
    clearError();
    if (!state.ackRevision) {
      showError(new ApiError(400, {
        error: {
          code: "acknowledge_revision_required",
          message: "还没有读到你核对过的交接版本，无法接手。请先刷新「当前交接状态」。",
        },
      }), "无法接手");
      return;
    }
    const payload = {
      status: $("#ack-status").value,
      revision: state.ackRevision,
      live_state_checked: $("#ack-live-state").checked,
      capability_checked: $("#ack-capability").checked,
      authorization_checked: $("#ack-authorization").checked,
      message: $("#ack-message").value.trim(),
    };
    const result = await withBusy(button, () =>
      api(`/api/projects/${state.currentId}/handoff/acknowledge`, { method: "POST", body: payload }));

    /* 回执可验证：读回的 Revision 必须等于用户核对过的那个，receipt Source 落库。 */
    const acked = result.selected_revision?.revision;
    const node = $("#ack-result");
    node.classList.remove("is-warn");
    node.hidden = false;
    node.innerHTML =
      `已接手 <code>Revision ${escapeHtml(String(acked ?? "?"))}</code>` +
      `（与你核对的版本${acked === state.ackRevision.revision ? "一致" : `<strong>不一致</strong>，核对的是 r${state.ackRevision.revision}`}）` +
      ` · 状态 ${escapeHtml(result.receipt_source_id ? "已落 receipt Source" : "未返回 receipt")}` +
      `<br><span class="muted" style="font-size:11.5px">receipt_source_id：<code>${escapeHtml(result.receipt_source_id || "—")}</code></span>`;
    toast(`已确认接手 · Revision ${acked ?? "?"}`);
    await Promise.all([loadRestore(), loadHandoffPanel({ refill: false })]);
  }

  /* ── 报告 ─────────────────────────────────────── */

  function resetReportPanel() {
    state.report = null;
    $("#report-output").hidden = true;
    $("#report-empty").hidden = false;
    $("#report-markdown").textContent = "";
    $("#report-summary").textContent = "";
  }

  async function submitReport(event, button) {
    event.preventDefault();
    clearError();
    const payload = {
      report_type: $("#report-type").value,
      date_from: $("#report-from").value,
      date_to: $("#report-to").value,
      include_done_todos: $("#report-include-done").checked,
    };
    if (payload.date_from && payload.date_to && payload.date_from > payload.date_to) {
      showError(new ApiError(422, {
        error: {
          code: "invalid_request",
          message: `起始日期（${payload.date_from}）不能晚于结束日期（${payload.date_to}）。`,
        },
      }), "报告区间不合法");
      return;
    }
    const report = await withBusy(button, () =>
      api(`/api/projects/${state.currentId}/report`, { method: "POST", body: payload }));
    state.report = report;
    $("#report-empty").hidden = true;
    $("#report-output").hidden = false;
    $("#report-markdown").textContent = report.markdown;
    $("#report-summary").textContent =
      `${report.title} · 正文真正引用 ${report.citation_count} 条记忆 · 其中 ${report.source_count} 条资料出处 · 区间 ${report.date_from || "不限"} ~ ${report.date_to || "至今"}`;
  }

  async function copyReport() {
    if (!state.report) return;
    try {
      await navigator.clipboard.writeText(state.report.markdown);
      toast("Markdown 已复制到剪贴板");
    } catch {
      const area = document.createElement("textarea");
      area.value = state.report.markdown;
      document.body.appendChild(area);
      area.select();
      document.execCommand("copy");
      area.remove();
      toast("Markdown 已复制");
    }
  }

  function downloadReport() {
    if (!state.report) return;
    const stamp = new Date().toISOString().slice(0, 10);
    const blob = new Blob([state.report.markdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${state.report.title}-${stamp}.md`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  /* ── 事件绑定 ─────────────────────────────────── */

  function bindEvents() {
    $("#error-close").addEventListener("click", clearError);
    $("#error-retry").addEventListener("click", async () => {
      const retry = errorRetry;
      clearError();
      if (retry) {
        try { await retry(); } catch (err) { showError(err); }
      }
    });

    $("#status-detail").addEventListener("click", () => { renderStatusModal(); openOverlay("status-modal"); });
    $("#status-modal-close").addEventListener("click", () => closeOverlay("status-modal"));
    $("#status-modal").addEventListener("click", (event) => { if (event.target.id === "status-modal") closeOverlay("status-modal"); });

    const openProjectModal = () => { updateGoalByteCounter(); openOverlay("project-modal"); };
    $("#new-project").addEventListener("click", openProjectModal);
    $("#empty-new-project").addEventListener("click", openProjectModal);
    $("#project-modal-close").addEventListener("click", () => closeOverlay("project-modal"));
    $("#project-cancel").addEventListener("click", () => closeOverlay("project-modal"));
    $("#project-modal").addEventListener("click", (event) => { if (event.target.id === "project-modal") closeOverlay("project-modal"); });
    $("#project-goal-input").addEventListener("input", updateGoalByteCounter);

    $("#project-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      clearError();
      const button = $("#project-submit");
      try {
        const project = await withBusy(button, () => api("/api/projects", {
          method: "POST",
          body: {
            name: $("#project-name-input").value.trim(),
            summary: $("#project-summary-input").value.trim(),
            goal: $("#project-goal-input").value.trim(),
          },
        }));
        closeOverlay("project-modal");
        $("#project-form").reset();
        updateGoalByteCounter();
        toast(`项目「${project.name}」已创建`);
        await loadProjects();
        await selectProject(project.project_id, { force: true });
      } catch (err) { showError(err, "创建项目失败"); }
    });

    $("#archive-project").addEventListener("click", async (event) => {
      const project = state.projects.find((item) => item.project_id === state.currentId);
      if (!project) return;
      try {
        await withBusy(event.currentTarget, () =>
          api(`/api/projects/${project.project_id}`, { method: "PATCH", body: { archived: !project.archived } }));
        toast(project.archived ? "已取消归档" : "已归档（记忆保留在 PowerContext 中）");
        await loadProjects();
      } catch (err) { showError(err); }
    });

    $("#continue-open").addEventListener("click", () => {
      const target = $("#continue-open").dataset.goto || "restore";
      switchTab(target);
      refreshActivePanel(target);
    });

    $$("#tabs .tab").forEach((tab) => {
      tab.addEventListener("click", () => {
        switchTab(tab.dataset.tab);
        refreshActivePanel(tab.dataset.tab).catch((err) => showError(err));
      });
    });

    $("#entry-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      clearError();
      const payload = entryFormPayload();
      if (!payload.title && !payload.body.trim()) {
        showError(new ApiError(400, { error: { code: "entry_empty", message: "标题和正文不能同时为空。" } }), "无法保存");
        return;
      }
      const editing = state.editing;
      const button = $("#entry-submit");
      try {
        await withBusy(button, async () => {
          if (editing) {
            if (!payload.reason) {
              throw new ApiError(400, { error: { code: "reason_required", message: "修订必须填写依据，这是日后回溯的关键。" } });
            }
            await api(`/api/projects/${state.currentId}/entries/${editing.citation.entry_id}`, {
              method: "PATCH",
              body: { citation: editing.citation, patch: payload, reason: payload.reason },
            });
          } else {
            await api(`/api/projects/${state.currentId}/entries`, { method: "POST", body: payload });
          }
        });
        toast(editing ? "修订已提交 · 旧版本保留在历史中" : "记录已保存");
        resetEntryForm();
        await refreshAfterWrite();
      } catch (err) { showError(err, editing ? "修订失败" : "保存失败"); }
    });

    $("#entry-reset").addEventListener("click", resetEntryForm);
    ["#entry-title", "#entry-body", "#entry-tags", "#entry-url", "#entry-reason"].forEach((selector) => {
      $(selector).addEventListener("input", updateByteCounter);
    });

    $("#search-button").addEventListener("click", () => runSearch($("#search-button")));
    $("#search-input").addEventListener("keydown", (event) => { if (event.key === "Enter") runSearch(); });
    $("#search-clear").addEventListener("click", () => {
      $("#search-input").value = "";
      state.hits = null;
      renderEntries();
    });
    $("#include-inactive").addEventListener("change", async (event) => {
      state.includeInactive = event.target.checked;
      state.hits = null;
      await loadEntries();
    });

    $("#restore-refresh").addEventListener("click", async (event) => {
      clearError();
      await withBusy(event.currentTarget, loadRestore);
    });

    $("#handoff-refill").addEventListener("click", async (event) => {
      clearError();
      state.handoffDirty = false;
      await withBusy(event.currentTarget, async () => {
        await loadHandoffPanel();
        toast("已按当前记忆重新预填");
      });
    });
    $("#handoff-form").addEventListener("input", (event) => {
      state.handoffDirty = true;
      const row = event.target.closest(".claim-row");
      if (row) syncClaimCitation(row);
    });
    $("#handoff-form").addEventListener("change", () => { state.handoffDirty = true; });
    $("#handoff-form").addEventListener("submit", async (event) => {
      try { await submitHandoff(event, $("#handoff-submit")); } catch (err) { showError(err, "保存交接失败"); }
    });
    $("#handoff-add-state").addEventListener("click", () => {
      $("#handoff-state").insertAdjacentHTML("beforeend", claimRow({ text: "", citation: null }));
      bindClaimRows();
      $("#handoff-state .claim-row:last-child input").focus();
    });
    $("#handoff-add-omission").addEventListener("click", () => {
      $("#handoff-omissions").insertAdjacentHTML("beforeend", omissionRow(""));
      bindClaimRows();
      $("#handoff-omissions .claim-row:last-child input").focus();
    });
    $("#ack-submit").addEventListener("click", async (event) => {
      try { await submitAcknowledge(event.currentTarget); } catch (err) { onAcknowledgeError(err); }
    });

    $("#report-form").addEventListener("submit", async (event) => {
      try { await submitReport(event, $("#report-submit")); } catch (err) { showError(err, "生成报告失败"); }
    });
    $("#report-copy").addEventListener("click", copyReport);
    $("#report-download").addEventListener("click", downloadReport);

    $("#history-close").addEventListener("click", () => closeOverlay("history"));
    $("#history-backdrop").addEventListener("click", () => closeOverlay("history"));

    bindOverlayKeys();
  }

  /* 409 handoff_revision_stale 不是失败终点，而是一次「你看的版本旧了」的提示：
   * 就地说明、自动刷新到最新版、清空核对勾选，要求用户基于新版本重新核对。 */
  function onAcknowledgeError(err) {
    const node = $("#ack-result");
    if (err.code === "handoff_revision_stale") {
      const latest = err.details?.latest?.revision ?? "?";
      node.classList.add("is-warn");
      node.hidden = false;
      node.innerHTML =
        `没有接手。你核对的是 <code>Revision ${err.details?.viewed?.revision ?? "?"}</code>，` +
        `但本项目最新交接已是 <code>Revision ${escapeHtml(String(latest))}</code>。<br>` +
        `正在刷新到最新版本，请重新核对上面三项后再次确认接手。`;
      ["#ack-live-state", "#ack-capability", "#ack-authorization"].forEach((selector) => { $(selector).checked = false; });
      showError(err, "接手版本已过期", () => loadHandoffPanel({ refill: false }));
      loadHandoffPanel({ refill: false }).catch((refreshError) => showError(refreshError));
      return;
    }
    node.hidden = true;
    showError(err, "接手失败");
  }

  async function runSearch(button) {
    const query = $("#search-input").value.trim();
    clearError();
    if (!query) { state.hits = null; renderEntries(); return; }
    try {
      state.hits = await withBusy(button, () => api(`/api/projects/${state.currentId}/search`, {
        method: "POST", body: { query, limit: 20, mode: "fts" },
      }));
      renderEntries();
    } catch (err) { showError(err, "检索失败", () => runSearch()); }
  }

  async function submitHandoff(event, button) {
    event.preventDefault();
    clearError();
    const stateClaims = collectClaims("#handoff-state", "claim-text");
    if (!stateClaims.length) {
      showError(new ApiError(400, { error: { code: "handoff_state_required", message: "交接至少需要一条「已确认状态」——PowerContext 的 CurrentWorkHandoff.state 要求非空。" } }), "无法保存交接");
      return;
    }
    const nextRow = $("#handoff-next").closest(".claim-row");
    const nextText = $("#handoff-next").value.trim();
    const payload = {
      objective: $("#handoff-objective").value.trim(),
      disposition: $("#handoff-disposition").value,
      state: stateClaims.map((claim) => ({ text: claim.text, citation: claim.citation })),
      next_action: nextText ? { text: nextText, citation: rowCitation(nextRow) } : null,
      omissions: $$("#handoff-omissions .omission-text").map((node) => node.value.trim()).filter(Boolean),
    };
    if (!payload.objective) {
      showError(new ApiError(400, { error: { code: "objective_required", message: "交接目标不能为空。" } }), "无法保存交接");
      return;
    }
    const saved = await withBusy(button, () =>
      api(`/api/projects/${state.currentId}/handoff`, { method: "POST", body: payload }));
    toast(`交接已提交 · Revision ${saved.selected_revision?.revision ?? "?"}`);
    renderCurrentHandoff(saved);
    state.handoffDirty = false;
    resetAckPanel();
    setAckRevision(saved.selected_revision || saved.current_revision);
    await Promise.all([loadProjects(), loadRestore()]);
  }

  /* ── 启动 ─────────────────────────────────────── */

  async function boot() {
    hideAllOverlays();
    bindEvents();
    try {
      state.meta = await api("/api/system/meta");
    } catch (err) {
      showError(err, "无法读取研续元数据", boot);
      return;
    }
    renderKindPicker();
    renderDispositionOptions();
    $("#entry-date").value = new Date().toISOString().slice(0, 10);
    updateByteCounter();
    updateGoalByteCounter();
    await loadStatus();
    try {
      await loadProjects();
      if (state.currentId) await selectProject(state.currentId, { force: true });
    } catch (err) {
      showError(err, "无法加载项目列表", loadProjects);
    }
  }

  boot();
})();
