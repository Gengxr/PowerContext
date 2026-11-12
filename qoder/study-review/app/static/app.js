"use strict";

const $ = (id) => document.getElementById(id);
const state = {
  learners: [],
  learner: null,
  overview: null,
  kps: [],
  records: [],
  prefs: null,
  editingKp: null,
};

const MASTERY = { 0: "薄弱", 1: "一般", 2: "已掌握" };
const RESULTS = { needs_work: "需要加强", ok: "基本掌握", mastered: "已掌握" };

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

let toastTimer = null;
function toast(msg, isError) {
  const t = $("toast");
  t.textContent = msg;
  t.className = "toast" + (isError ? " error" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("hidden"), 3500);
}

async function api(path, options) {
  const resp = await fetch(path, options);
  let data = null;
  try { data = await resp.json(); } catch (e) { /* ignore */ }
  if (!resp.ok) {
    const msg = (data && data.error) || ("请求失败 HTTP " + resp.status);
    throw new Error(msg);
  }
  return data;
}

function learnerQuery() {
  return "learner=" + encodeURIComponent(state.learner);
}

function fmtDt(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  const pad = (n) => String(n).padStart(2, "0");
  return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) +
    " " + pad(d.getHours()) + ":" + pad(d.getMinutes());
}

// ---- 加载 ----
async function loadHealth() {
  try {
    const h = await api("/api/health");
    const dot = $("pc-status");
    dot.className = "status-dot " + (h.powercontext ? "ok" : "bad");
    dot.title = h.powercontext ? "PowerContext 已连接" : "PowerContext 不可用";
  } catch (e) {
    $("pc-status").className = "status-dot bad";
  }
}

async function loadLearners() {
  const data = await api("/api/learners");
  state.learners = data.learners;
  const sel = $("learner-select");
  sel.innerHTML = "";
  for (const l of state.learners) {
    const opt = el("option", null, l.name);
    opt.value = l.scope_id;
    sel.appendChild(opt);
  }
  const st = await api("/api/state");
  let selected = st.selected_learner_scope_id;
  if (!selected || !state.learners.some((l) => l.scope_id === selected)) {
    selected = state.learners.length ? state.learners[0].scope_id : null;
  }
  state.learner = selected;
  if (selected) sel.value = selected;
}

async function loadLearnerData() {
  if (!state.learner) {
    state.overview = null; state.kps = []; state.records = []; state.prefs = null;
    renderAll();
    return;
  }
  const q = learnerQuery();
  const [overview, kps, records, prefs] = await Promise.all([
    api("/api/overview?" + q),
    api("/api/kps?" + q),
    api("/api/records?" + q),
    api("/api/prefs?" + q),
  ]);
  state.overview = overview;
  state.kps = kps.kps;
  state.records = records.records;
  state.prefs = prefs;
  renderAll();
}

async function loadRules() {
  const r = await api("/api/rules");
  const box = $("rules-box");
  box.innerHTML = "";
  box.appendChild(el("div", null, r.initial));
  for (const key of ["needs_work", "ok", "mastered"]) {
    const item = r.results[key];
    box.appendChild(el("div", null, item.label + "：间隔 " + item.interval + "，掌握程度 " + item.mastery));
  }
  box.appendChild(el("div", null, r.due));
  const ol = el("ol");
  for (const step of r.order) ol.appendChild(el("li", null, step));
  box.appendChild(ol);
  box.appendChild(el("div", null, r.upcoming));
  box.appendChild(el("div", null, r.note));
}

// ---- 渲染 ----
function renderAll() {
  renderProgress();
  renderDue();
  renderUpcoming();
  renderKps();
  renderRecords();
  renderPrefs();
  renderStorage();
}

function renderProgress() {
  const ov = state.overview;
  if (!ov) {
    $("progress-text").textContent = "请先创建学习者";
    $("progress-fill").style.width = "0";
    $("now-label").textContent = "";
    return;
  }
  const p = ov.progress;
  const pct = Math.min(100, Math.round((p.reviewed_today / Math.max(1, p.daily_goal)) * 100));
  $("progress-fill").style.width = pct + "%";
  $("progress-text").textContent = "今日已复习 " + p.reviewed_today + " / 目标 " + p.daily_goal;
  $("now-label").textContent = "服务器时间 " + fmtDt(ov.now);
}

function renderDue() {
  const list = $("due-list");
  list.innerHTML = "";
  const ov = state.overview;
  $("due-count").textContent = ov ? String(ov.due.length) : "0";
  if (!ov || ov.due.length === 0) {
    list.appendChild(el("div", "empty", ov ? "太棒了，当前没有到期知识点。" : "暂无数据。"));
    return;
  }
  for (const item of ov.due) {
    const kp = item.kp;
    const card = el("div", "due-item mastery-" + kp.mastery);
    const head = el("div", "due-head");
    head.appendChild(el("span", "chip", kp.course));
    head.appendChild(el("span", "due-title", kp.title));
    head.appendChild(el("span", "chip mastery", "掌握：" + MASTERY[kp.mastery]));
    if (item.overdue_days > 0) head.appendChild(el("span", "chip overdue", "逾期 " + item.overdue_days + " 天"));
    head.appendChild(el("span", "chip", "已复习 " + kp.review_count + " 次"));
    card.appendChild(head);
    if (kp.notes) card.appendChild(el("div", "notes", kp.notes));
    const reasons = el("ul", "reasons");
    for (const r of item.reasons) reasons.appendChild(el("li", null, r));
    card.appendChild(reasons);
    const actions = el("div", "review-actions");
    const noteInput = el("input");
    noteInput.placeholder = "复习备注（可选）";
    noteInput.maxLength = 500;
    actions.appendChild(noteInput);
    for (const key of ["needs_work", "ok", "mastered"]) {
      const btn = el("button", "btn small " + key.replace("_", "-"), RESULTS[key]);
      btn.addEventListener("click", () => completeReview(kp.kp_id, key, noteInput.value, btn));
      actions.appendChild(btn);
    }
    card.appendChild(actions);
    list.appendChild(card);
  }
}

function renderUpcoming() {
  const card = $("upcoming-card");
  const list = $("upcoming-list");
  list.innerHTML = "";
  const ov = state.overview;
  if (!ov || !ov.prefs.show_upcoming) {
    card.classList.add("hidden");
    return;
  }
  card.classList.remove("hidden");
  if (ov.upcoming.length === 0) {
    list.appendChild(el("div", "empty", "展示窗口内没有未到期知识点。"));
    return;
  }
  for (const item of ov.upcoming) {
    const kp = item.kp;
    const row = el("div", "upcoming-row");
    row.appendChild(el("span", "chip", kp.course));
    row.appendChild(el("span", "grow", kp.title));
    row.appendChild(el("span", "muted small", fmtDt(kp.next_review_at) + " 到期"));
    list.appendChild(row);
  }
}

function renderKps() {
  const list = $("kp-list");
  list.innerHTML = "";
  if (state.kps.length === 0) {
    list.appendChild(el("div", "empty", "还没有知识点，先添加一个吧。"));
    return;
  }
  const sorted = [...state.kps].sort((a, b) => a.course.localeCompare(b.course) || a.title.localeCompare(b.title));
  for (const kp of sorted) {
    const row = el("div", "kp-row");
    row.appendChild(el("span", "chip", kp.course));
    const grow = el("div", "grow");
    grow.appendChild(el("div", null, kp.title));
    grow.appendChild(el("div", "muted small",
      "掌握：" + MASTERY[kp.mastery] + " · 间隔 " + kp.interval_days + " 天 · 下次 " + fmtDt(kp.next_review_at)));
    row.appendChild(grow);
    const edit = el("button", "btn small secondary", "编辑");
    edit.addEventListener("click", () => startEdit(kp));
    const del = el("button", "btn small danger", "删除");
    del.addEventListener("click", () => deleteKp(kp));
    row.appendChild(edit);
    row.appendChild(del);
    list.appendChild(row);
  }
}

function renderRecords() {
  const list = $("record-list");
  list.innerHTML = "";
  if (state.records.length === 0) {
    list.appendChild(el("div", "empty", "暂无复习记录。"));
    return;
  }
  for (const r of state.records.slice(0, 30)) {
    const row = el("div", "record-row");
    row.appendChild(el("span", "record-result " + r.result, RESULTS[r.result] || r.result));
    const grow = el("div", "grow");
    grow.appendChild(el("div", null, r.kp_title));
    grow.appendChild(el("div", "muted small",
      fmtDt(r.reviewed_at) + " · 间隔 " + r.prev_interval_days + "→" + r.new_interval_days +
      " 天 · 下次 " + fmtDt(r.next_review_at) + (r.note ? " · " + r.note : "")));
    row.appendChild(grow);
    list.appendChild(row);
  }
}

function renderPrefs() {
  const p = state.prefs;
  if (!p) return;
  $("pref-goal").value = p.daily_goal;
  $("pref-upcoming").checked = p.show_upcoming;
  $("pref-horizon").value = p.upcoming_horizon_days;
}

function renderStorage() {
  const box = $("storage-box");
  box.innerHTML = "";
  const learner = state.learners.find((l) => l.scope_id === state.learner);
  box.appendChild(el("div", null, "当前学习者 Scope：" + (state.learner || "未选择")));
  if (learner) box.appendChild(el("div", null, "名称：" + learner.name));
  if (state.overview) {
    box.appendChild(el("div", null, "知识点 " + state.overview.totals.knowledge_points +
      " 个 · 复习记录 " + state.overview.totals.review_records + " 条"));
  }
  box.appendChild(el("div", null, "存储：PowerContext Server（SQLite）"));
}

// ---- 操作 ----
async function completeReview(kpId, result, note, btn) {
  btn.disabled = true;
  try {
    await api("/api/review?" + learnerQuery(), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kp_id: kpId, result, note }),
    });
    toast("已记录：" + RESULTS[result]);
    await loadLearnerData();
  } catch (e) {
    toast(e.message, true);
    btn.disabled = false;
  }
}

function startEdit(kp) {
  state.editingKp = kp.kp_id;
  $("kp-course").value = kp.course;
  $("kp-title").value = kp.title;
  $("kp-mastery").value = String(kp.mastery);
  $("kp-notes").value = kp.notes || "";
  $("kp-submit").textContent = "保存修改";
  $("kp-cancel").classList.remove("hidden");
  $("kp-course").focus();
}

function cancelEdit() {
  state.editingKp = null;
  $("kp-form").reset();
  $("kp-submit").textContent = "添加知识点";
  $("kp-cancel").classList.add("hidden");
}

async function deleteKp(kp) {
  if (!confirm("删除知识点「" + kp.title + "」及其复习记录？")) return;
  try {
    await api("/api/kp?" + learnerQuery() + "&kp_id=" + encodeURIComponent(kp.kp_id), { method: "DELETE" });
    toast("已删除");
    if (state.editingKp === kp.kp_id) cancelEdit();
    await loadLearnerData();
  } catch (e) {
    toast(e.message, true);
  }
}

async function switchLearner(scopeId) {
  state.learner = scopeId;
  cancelEdit();
  try {
    await api("/api/state", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ selected_learner_scope_id: scopeId }),
    });
    await loadLearnerData();
  } catch (e) {
    toast(e.message, true);
  }
}

async function createLearner() {
  const name = prompt("新学习者名称（例如：学习者C）：");
  if (!name || !name.trim()) return;
  try {
    const created = await api("/api/learners", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name.trim() }),
    });
    await loadLearners();
    await switchLearner(created.scope_id);
    toast("已创建学习者：" + created.name);
  } catch (e) {
    toast(e.message, true);
  }
}

// ---- 事件绑定 ----
$("learner-select").addEventListener("change", (e) => switchLearner(e.target.value));
$("new-learner-btn").addEventListener("click", createLearner);
$("kp-cancel").addEventListener("click", cancelEdit);

$("kp-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const payload = {
    course: $("kp-course").value,
    title: $("kp-title").value,
    notes: $("kp-notes").value,
    mastery: Number($("kp-mastery").value),
  };
  try {
    if (state.editingKp) {
      await api("/api/kp?" + learnerQuery() + "&kp_id=" + encodeURIComponent(state.editingKp), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      toast("已保存修改");
      cancelEdit();
    } else {
      await api("/api/kps?" + learnerQuery(), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      toast("已添加知识点");
      $("kp-form").reset();
    }
    await loadLearnerData();
  } catch (err) {
    toast(err.message, true);
  }
});

$("prefs-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/api/prefs?" + learnerQuery(), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        daily_goal: Number($("pref-goal").value),
        show_upcoming: $("pref-upcoming").checked,
        upcoming_horizon_days: Number($("pref-horizon").value),
      }),
    });
    toast("偏好已保存到 PowerContext");
    await loadLearnerData();
  } catch (err) {
    toast(err.message, true);
  }
});

// ---- 启动 ----
(async function init() {
  try {
    await loadHealth();
    await loadRules();
    await loadLearners();
    await loadLearnerData();
  } catch (e) {
    toast("初始化失败：" + e.message, true);
  }
})();