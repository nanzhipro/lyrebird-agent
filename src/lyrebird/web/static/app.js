// Lyrebird front-end controller.
//
// i18n contract:
//   - On boot we hit /api/i18n/<locale> and stash the flat key→string map.
//   - HTML elements opt-in via data-i18n / data-i18n-placeholder / data-i18n-html.
//   - JS code that synthesizes strings uses t("key", {var}).
//   - Switching language reloads the locale + replays applyI18n() over the DOM.
//
// All UI strings live in src/lyrebird/i18n/locales/<lang>.json. To add another
// language, drop locales/xx.json with the same key set as zh.json; CI catches
// drift via test_project_locales_have_matching_keys.

// ---------- stage list: ids match Pipeline.run() in orchestrator.py ----------
const STAGE_IDS = [
  "pii_scan", "intake", "interview",
  "evidence_mapping", "mechanism_naming", "skeptic_review", "publish",
];

const $ = (sel) => document.querySelector(sel);

const els = {
  form: $("#form-card"),
  targetRole: $("#f-target-role"),
  resume: $("#f-resume"),
  turns: $("#f-turns"),
  minInc: $("#f-min-incidents"),
  candidate: $("#f-candidate"),
  startBtn: $("#btn-start"),
  loadSample: $("#btn-load-sample"),
  formHint: $("#form-hint"),

  obs: $("#observability"),
  runId: $("#run-id-display"),
  runStatus: $("#run-status-pill"),
  stageStrip: $("#stage-strip"),
  stageCounter: $("#stage-counter"),
  agentFeed: $("#agent-feed"),
  agentCounter: $("#agent-counter"),
  tokIn: $("#tok-in"),
  tokOut: $("#tok-out"),
  llmCalls: $("#llm-calls"),
  eventLog: $("#event-log"),
  eventCounter: $("#event-counter"),

  report: $("#report"),
  reportSummary: $("#report-summary"),
  reportMechanisms: $("#report-mechanisms"),
  reportPii: $("#report-pii"),

  langSwitcher: $("#lang-switcher"),
  langTrigger: $("#lang-trigger"),
  langTriggerLabel: $("#lang-trigger-label"),
  langMenu: $("#lang-menu"),
};

// ---------- runtime state ----------

let stageState = {};
let agentRows = new Map();
let tokensIn = 0;
let tokensOut = 0;
let llmCalls = 0;
let eventCount = 0;
let currentStream = null;
let seenSeq = 0;
let terminalSeen = false;

// i18n state
let i18nStrings = {};
let currentLocale = "zh";

// ---------- i18n primitives ----------

function t(key, vars = {}) {
  let v = i18nStrings[key];
  if (v === undefined || v === null) return key;
  if (vars) {
    for (const [k, val] of Object.entries(vars)) {
      v = v.replace(new RegExp("\\{" + k + "\\}", "g"), String(val));
    }
  }
  return v;
}

function applyI18nToDom(root = document) {
  root.querySelectorAll("[data-i18n]").forEach((el) => {
    const key = el.dataset.i18n;
    const v = t(key);
    if (v !== key) el.textContent = v;
  });
  root.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
    const key = el.dataset.i18nPlaceholder;
    const v = t(key);
    if (v !== key) el.placeholder = v;
  });
  root.querySelectorAll("[data-i18n-html]").forEach((el) => {
    const key = el.dataset.i18nHtml;
    const v = t(key);
    if (v !== key) el.innerHTML = v;
  });
}

function applyHtmlLangAttr() {
  const code = i18nStrings["meta.html_lang"] || currentLocale;
  document.documentElement.setAttribute("lang", code);
  const titleEl = document.querySelector("title[data-i18n]");
  if (titleEl) titleEl.textContent = t(titleEl.dataset.i18n);
}

async function loadLocale(locale) {
  const r = await fetch(`/api/i18n/${encodeURIComponent(locale)}`);
  if (!r.ok) throw new Error(`i18n ${locale}: ${r.status}`);
  const body = await r.json();
  currentLocale = body.locale;
  i18nStrings = body.strings || {};
  applyI18nToDom();
  applyHtmlLangAttr();
}

let availableLocales = []; // [{code, name, native, html_lang}, ...]

async function buildLanguageSwitcher() {
  if (!els.langTrigger || !els.langMenu) return;
  let body;
  try {
    body = await (await fetch("/api/i18n/locales")).json();
  } catch (e) {
    console.warn("language list failed", e);
    return;
  }
  availableLocales = body.locales;

  // Update trigger label
  const active = availableLocales.find((l) => l.code === currentLocale) || availableLocales[0];
  if (active) {
    els.langTriggerLabel.textContent = active.native;
    els.langTrigger.setAttribute("aria-label", `${t("nav.language")} — ${active.native}`);
  }

  // Build the listbox items
  els.langMenu.innerHTML = "";
  availableLocales.forEach((loc) => {
    const item = document.createElement("li");
    item.className = "lang-item";
    item.role = "option";
    item.dataset.lang = loc.code;
    item.setAttribute("role", "option");
    item.setAttribute("aria-selected", loc.code === currentLocale ? "true" : "false");
    item.setAttribute("tabindex", "0");
    item.innerHTML = `
      <span class="lang-item-main">
        <span class="lang-item-native">${escapeHtml(loc.native)}</span>
        <span class="lang-item-tag">${escapeHtml(loc.code)}</span>
      </span>
      <svg class="lang-item-check" viewBox="0 0 12 12" aria-hidden="true">
        <path d="M2 6.5l2.5 2.5L10 3.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    `;
    item.addEventListener("click", () => {
      switchLocale(loc.code);
      closeLangMenu();
    });
    item.addEventListener("keydown", (e) => handleLangItemKey(e, loc.code));
    els.langMenu.appendChild(item);
  });
}

function openLangMenu() {
  els.langMenu.hidden = false;
  els.langTrigger.setAttribute("aria-expanded", "true");
  // Focus the currently-selected item for keyboard users
  const selected = els.langMenu.querySelector('[aria-selected="true"]') || els.langMenu.firstElementChild;
  if (selected) selected.focus();
}

function closeLangMenu() {
  els.langMenu.hidden = true;
  els.langTrigger.setAttribute("aria-expanded", "false");
}

function toggleLangMenu() {
  if (els.langMenu.hidden) openLangMenu(); else closeLangMenu();
}

function handleLangItemKey(e, code) {
  const items = Array.from(els.langMenu.querySelectorAll(".lang-item"));
  const i = items.findIndex((el) => el === document.activeElement);
  switch (e.key) {
    case "Enter":
    case " ":
      e.preventDefault();
      switchLocale(code);
      closeLangMenu();
      els.langTrigger.focus();
      break;
    case "ArrowDown":
      e.preventDefault();
      items[(i + 1) % items.length]?.focus();
      break;
    case "ArrowUp":
      e.preventDefault();
      items[(i - 1 + items.length) % items.length]?.focus();
      break;
    case "Home":
      e.preventDefault();
      items[0]?.focus();
      break;
    case "End":
      e.preventDefault();
      items[items.length - 1]?.focus();
      break;
    case "Escape":
      e.preventDefault();
      closeLangMenu();
      els.langTrigger.focus();
      break;
  }
}

function wireLangSwitcherEvents() {
  if (!els.langTrigger) return;
  els.langTrigger.addEventListener("click", (e) => {
    e.stopPropagation();
    toggleLangMenu();
  });
  els.langTrigger.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      openLangMenu();
    } else if (e.key === "Escape") {
      closeLangMenu();
    }
  });
  // Click outside closes
  document.addEventListener("click", (e) => {
    if (!els.langSwitcher.contains(e.target)) closeLangMenu();
  });
  // Esc anywhere closes
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !els.langMenu.hidden) {
      closeLangMenu();
      els.langTrigger.focus();
    }
  });
}

async function switchLocale(locale) {
  if (locale === currentLocale) return;
  await loadLocale(locale);
  renderStageStrip();
  refreshDynamicStrings();
  await buildLanguageSwitcher();
}

// Refresh strings that JS owns (not data-i18n attrs).
function refreshDynamicStrings() {
  // Run status pill — preserve class but re-translate
  const statusKey = els.runStatus.dataset.statusKey;
  if (statusKey) els.runStatus.textContent = t(statusKey);
  // Start button text
  const startKey = els.startBtn.dataset.stateKey || "form.start";
  els.startBtn.textContent = t(startKey);
  // Sample button label (might be in "loading" state)
  const sampleKey = els.loadSample.dataset.stateKey || "form.resume.load_sample";
  els.loadSample.textContent = t(sampleKey);
  // Agent counter
  if (els.agentCounter.dataset.count !== undefined) {
    const n = parseInt(els.agentCounter.dataset.count, 10) || 0;
    els.agentCounter.textContent = t(n === 1 ? "obs.agent.calls_one" : "obs.agent.calls_other", { n });
  }
  // Agent rows: dur "running…" and status badges
  els.agentFeed.querySelectorAll(".agent-row.running .dur").forEach((d) => {
    d.textContent = t("obs.agent.running");
  });
  els.agentFeed.querySelectorAll(".agent-row.failed .dur").forEach((d) => {
    d.textContent = t("obs.agent.failed");
  });
}

// ---------- boot ----------

async function boot() {
  // Determine starting locale from cookie or default to zh
  const cookieLang = readCookie("lyrebird_lang");
  const queryLang = new URLSearchParams(location.search).get("lang");
  const start = queryLang || cookieLang || "zh";
  try {
    await loadLocale(start);
  } catch (e) {
    console.error("locale load failed; UI will show keys", e);
  }
  renderStageStrip();
  await buildLanguageSwitcher();
  wireLangSwitcherEvents();
  els.loadSample.addEventListener("click", loadSample);
  els.startBtn.addEventListener("click", startRun);
  els.resume.addEventListener("input", validateForm);
  validateForm();
}

function readCookie(name) {
  const m = document.cookie.match(
    new RegExp("(?:^|;\\s*)" + name + "=([^;]*)"),
  );
  return m ? decodeURIComponent(m[1]) : null;
}

// ---------- pipeline stage strip ----------

function renderStageStrip() {
  els.stageStrip.innerHTML = "";
  STAGE_IDS.forEach((id, idx) => {
    const chip = document.createElement("div");
    chip.className = "stage-chip pending";
    chip.dataset.stage = id;
    chip.innerHTML = `
      <span class="stage-label">${String(idx + 1).padStart(2, "0")}</span>
      <span class="stage-name">${escapeHtml(t("obs.stage." + id))}</span>
      <span class="stage-meta"></span>
    `;
    els.stageStrip.appendChild(chip);
    stageState[id] = { state: "pending", t0: null };
  });
  els.stageCounter.textContent = "0 / 7";
}

function validateForm() {
  const resume = els.resume.value || "";
  els.startBtn.disabled = resume.trim().length < 80;
}

// ---------- sample resume ----------

async function loadSample() {
  els.loadSample.dataset.stateKey = "form.resume.loading";
  els.loadSample.textContent = t("form.resume.loading");
  try {
    const r = await fetch("/api/sample-resume");
    if (!r.ok) throw new Error(r.statusText);
    const body = await r.json();
    els.resume.value = body.resume_text;
    if (!els.targetRole.value) {
      // Use whichever target hint feels right per locale
      els.targetRole.value = currentLocale === "zh"
        ? "macOS 终端安全架构师"
        : "macOS endpoint-security architect";
    }
    validateForm();
  } catch (e) {
    alert(t("errors.sample_failed", { message: e.message }));
  } finally {
    els.loadSample.dataset.stateKey = "form.resume.load_sample";
    els.loadSample.textContent = t("form.resume.load_sample");
  }
}

// ---------- start a run ----------

async function startRun() {
  resetState();

  const payload = {
    resume_text: els.resume.value.trim(),
    target_role: els.targetRole.value.trim() || null,
    candidate_id: (els.candidate.value || "cand_user").trim(),
    turns: parseInt(els.turns.value, 10) || 6,
    min_incidents: parseInt(els.minInc.value, 10) || 3,
  };

  els.startBtn.disabled = true;
  els.startBtn.dataset.stateKey = "form.starting";
  els.startBtn.textContent = t("form.starting");

  let r;
  try {
    r = await fetch("/api/runs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (e) {
    alert(t("errors.network", { message: e.message }));
    enableStartButton("form.start");
    return;
  }

  if (!r.ok) {
    const detail = await r.text();
    alert(t("errors.server_rejected", { detail }));
    enableStartButton("form.start");
    return;
  }

  const body = await r.json();
  enterRunView(body.run_id);
  openStream(body.run_id);
}

function enableStartButton(stateKey) {
  els.startBtn.disabled = false;
  els.startBtn.dataset.stateKey = stateKey;
  els.startBtn.textContent = t(stateKey);
}

function resetState() {
  stageState = {};
  agentRows.clear();
  tokensIn = 0;
  tokensOut = 0;
  llmCalls = 0;
  eventCount = 0;
  els.agentFeed.innerHTML = `<div class="agent-feed-empty muted small" data-i18n="obs.agent.waiting">${escapeHtml(t("obs.agent.waiting"))}</div>`;
  setAgentCount(0);
  els.eventLog.innerHTML = "";
  els.eventCounter.textContent = "0";
  els.tokIn.textContent = "0";
  els.tokOut.textContent = "0";
  els.llmCalls.textContent = "0";
  els.reportSummary.innerHTML = "";
  els.reportMechanisms.innerHTML = "";
  els.report.hidden = true;
  renderStageStrip();
}

function setStatus(statusKey, className) {
  els.runStatus.dataset.statusKey = statusKey;
  els.runStatus.textContent = t(statusKey);
  els.runStatus.classList.remove("running", "completed", "failed");
  if (className) els.runStatus.classList.add(className);
}

function setAgentCount(n) {
  els.agentCounter.dataset.count = String(n);
  els.agentCounter.textContent = t(n === 1 ? "obs.agent.calls_one" : "obs.agent.calls_other", { n });
}

function enterRunView(runId) {
  els.runId.textContent = runId;
  setStatus("obs.status.running", "running");
  els.obs.hidden = false;
  els.obs.scrollIntoView({ behavior: "smooth", block: "start" });
}

// ---------- SSE stream ----------

function openStream(runId) {
  if (currentStream) {
    try { currentStream.close(); } catch (_) {}
    currentStream = null;
  }
  seenSeq = 0;
  terminalSeen = false;

  const src = new EventSource(`/api/runs/${runId}/events`);
  currentStream = src;

  const handler = (ev) => {
    try {
      const data = JSON.parse(ev.data);
      if (typeof data.seq === "number") {
        if (data.seq <= seenSeq) return;
        seenSeq = data.seq;
      }
      handleEvent(data);
      if (data.type === "run.completed" || data.type === "run.failed") {
        terminalSeen = true;
        try { src.close(); } catch (_) {}
        currentStream = null;
      }
    } catch (e) {
      console.warn("bad SSE payload", ev.data, e);
    }
  };

  [
    "run.started", "run.completed", "run.failed",
    "stage.started", "stage.completed",
    "agent.started", "agent.completed", "agent.failed",
    "gate.evaluated", "artifact.written", "log",
  ].forEach((t) => src.addEventListener(t, handler));

  src.onerror = () => {
    if (terminalSeen) {
      try { src.close(); } catch (_) {}
      currentStream = null;
      return;
    }
    console.warn("SSE transport error; browser will auto-reconnect");
  };
}

function handleEvent(ev) {
  appendLog(ev);
  eventCount += 1;
  els.eventCounter.textContent = String(eventCount);

  switch (ev.type) {
    case "stage.started":
      markStage(ev.payload.stage, "running");
      break;
    case "stage.completed":
      markStage(ev.payload.stage, "done", { duration_ms: ev.payload.duration_ms });
      break;
    case "agent.started":
      addAgentRow(ev);
      break;
    case "agent.completed":
      completeAgentRow(ev);
      break;
    case "agent.failed":
      failAgentRow(ev);
      break;
    case "run.completed":
      setStatus("obs.status.completed", "completed");
      fetchAndRenderReport(els.runId.textContent);
      enableStartButton("form.another");
      break;
    case "run.failed":
      setStatus("obs.status.failed", "failed");
      enableStartButton("form.try_again");
      break;
  }
}

function markStage(stageId, state, extra = {}) {
  const chip = els.stageStrip.querySelector(`[data-stage="${stageId}"]`);
  if (!chip) return;
  chip.classList.remove("pending", "running", "done", "failed");
  chip.classList.add(state);
  const meta = chip.querySelector(".stage-meta");
  if (state === "done") {
    const ms = extra.duration_ms || 0;
    meta.textContent = `${Math.round(ms / 100) / 10}s`;
  } else if (state === "running") {
    meta.textContent = "…";
  }
  stageState[stageId] = { state };
  const done = Object.values(stageState).filter((s) => s.state === "done").length;
  els.stageCounter.textContent = `${done} / 7`;
}

// ---------- agent rows ----------

function addAgentRow(ev) {
  const empty = els.agentFeed.querySelector(".agent-feed-empty");
  if (empty) empty.remove();

  const row = document.createElement("div");
  row.className = "agent-row running";
  row.dataset.seq = String(ev.seq);
  row.innerHTML = `
    <div>
      <div class="agent-name">${escapeHtml(ev.payload.agent)}</div>
      <div class="agent-stage">${escapeHtml(ev.payload.stage || "")}</div>
    </div>
    <div class="agent-meta">
      <span class="dur">${escapeHtml(t("obs.agent.running"))}</span>
      <span class="tokens"></span>
      <span class="agent-model">${escapeHtml(ev.payload.model || ev.payload.role || "")}</span>
    </div>
  `;
  els.agentFeed.prepend(row);

  const total = els.agentFeed.querySelectorAll(".agent-row").length;
  setAgentCount(total);
}

function completeAgentRow(ev) {
  const row = findLastRunningRow(makeAgentKey(ev));
  if (!row) return;
  row.classList.remove("running");
  row.querySelector(".dur").textContent = `${Math.round((ev.payload.duration_ms || 0) / 100) / 10}s`;
  const tin = ev.payload.tokens_in || 0;
  const tout = ev.payload.tokens_out || 0;
  row.querySelector(".tokens").textContent = `in ${tin} · out ${tout}`;
  tokensIn += tin;
  tokensOut += tout;
  llmCalls += 1;
  els.tokIn.textContent = String(tokensIn);
  els.tokOut.textContent = String(tokensOut);
  els.llmCalls.textContent = String(llmCalls);
}

function failAgentRow(ev) {
  const row = findLastRunningRow(makeAgentKey(ev));
  if (!row) return;
  row.classList.remove("running");
  row.classList.add("failed");
  row.querySelector(".dur").textContent = t("obs.agent.failed");
}

function makeAgentKey(ev) {
  return `${ev.payload.agent}::${ev.payload.stage || ""}`;
}

function findLastRunningRow(key) {
  for (const r of els.agentFeed.querySelectorAll(".agent-row.running")) {
    const name = r.querySelector(".agent-name").textContent;
    const stage = r.querySelector(".agent-stage").textContent;
    if (`${name}::${stage}` === key) return r;
  }
  const fallbackName = key.split("::")[0];
  for (const r of els.agentFeed.querySelectorAll(".agent-row")) {
    if (r.querySelector(".agent-name").textContent === fallbackName
        && r.classList.contains("running")) {
      return r;
    }
  }
  return null;
}

// ---------- event log ----------

function appendLog(ev) {
  const row = document.createElement("div");
  row.className = "event-row";
  const time = (ev.timestamp || "").slice(11, 19);
  const typeClass = ev.type.replace(/\./g, "-");
  row.innerHTML = `
    <span class="ev-time">${time}</span>
    <span class="ev-type ${typeClass}">${ev.type}</span>
    <span class="ev-payload">${formatPayload(ev.payload)}</span>
  `;
  els.eventLog.appendChild(row);
  els.eventLog.scrollTop = els.eventLog.scrollHeight;
}

function formatPayload(p) {
  if (!p) return "";
  const keys = Object.keys(p);
  if (keys.length === 0) return "";
  return escapeHtml(
    keys
      .filter((k) => p[k] !== null && p[k] !== undefined && p[k] !== "")
      .map((k) => {
        const v = p[k];
        if (typeof v === "object") return `${k}=${JSON.stringify(v)}`;
        const s = String(v);
        return `${k}=${s.length > 80 ? s.slice(0, 77) + "…" : s}`;
      })
      .join("  "),
  );
}

// ---------- report ----------

async function fetchAndRenderReport(runId) {
  await new Promise((r) => setTimeout(r, 300));
  try {
    const r = await fetch(`/api/runs/${runId}/report`);
    if (!r.ok) {
      console.warn("report fetch failed", r.status);
      return;
    }
    const rep = await r.json();
    renderReport(rep);
  } catch (e) {
    console.warn("report error", e);
  }
}

function renderReport(rep) {
  els.report.hidden = false;

  els.reportSummary.innerHTML = `
    <div class="summary-stat validated">
      <div class="stat-value">${rep.summary.validated_mechanisms}</div>
      <div class="stat-label">${escapeHtml(t("report.stat.validated"))}</div>
    </div>
    <div class="summary-stat probable">
      <div class="stat-value">${rep.summary.probable_mechanisms}</div>
      <div class="stat-label">${escapeHtml(t("report.stat.probable"))}</div>
    </div>
    <div class="summary-stat needs">
      <div class="stat-value">${rep.summary.needs_more_evidence}</div>
      <div class="stat-label">${escapeHtml(t("report.stat.needs"))}</div>
    </div>
  `;

  const mechs = [
    ...rep.validated_mechanisms.map((m) => ({ ...m, status: "validated" })),
    ...rep.probable_mechanisms.map((m) => ({ ...m, status: "probable" })),
  ];

  els.reportMechanisms.innerHTML = mechs.length
    ? mechs.map(renderMechanism).join("")
    : `<p class="muted">${escapeHtml(t("report.empty"))}</p>`;

  els.reportPii.textContent = (rep.privacy_notes || []).join(" · ");
  els.report.scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderMechanism(m) {
  const statusLabel = m.status === "validated"
    ? t("report.stat.validated") : t("report.stat.probable");
  return `
    <div class="mechanism-card ${m.status}">
      <div class="mech-header">
        <h3 class="mech-name">${escapeHtml(m.name)}</h3>
        <span class="mech-status ${m.status}">${escapeHtml(statusLabel)} · ${m.confidence.toFixed(2)}</span>
      </div>
      <div class="mech-section">
        <div class="mech-section-label">${escapeHtml(t("report.mech.why"))}</div>
        <div class="mech-section-body">${escapeHtml(m.why_it_matters)}</div>
      </div>
      <div class="mech-section">
        <div class="mech-section-label">${escapeHtml(t("report.mech.resume_rewrite"))}</div>
        <div class="mech-section-body">${escapeHtml(m.resume_rewrite)}</div>
      </div>
      <div class="mech-section">
        <div class="mech-section-label">${escapeHtml(t("report.mech.interview_narrative"))}</div>
        <div class="mech-section-body">${escapeHtml(m.interview_narrative)}</div>
      </div>
      <div class="mech-section">
        <div class="mech-section-label">${escapeHtml(t("report.mech.evidence"))}</div>
        <div class="mech-evidence-row">
          ${(m.evidence_ids || []).map(
            (eid) => `<span class="evidence-pill">${escapeHtml(eid)}</span>`,
          ).join("")}
        </div>
      </div>
    </div>
  `;
}

// ---------- utils ----------

function escapeHtml(s) {
  if (s === null || s === undefined) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ---------- go ----------

boot();
