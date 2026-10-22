// Scheme Eligibility Assistant: public site (loads after common.js).
let ATTRS = [];
// ---------------------------------------------------------------- one continuous page: smooth scroll, scroll-spy, reveal
const REDUCED = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const goTo = (id) => { const el = document.getElementById(id); if (el) el.scrollIntoView({ behavior: REDUCED ? "auto" : "smooth", block: "start" }); };
function route() {
  const [sec, arg] = location.hash.slice(1).split("/");
  if (sec === "schemes" && arg) openScheme(decodeURIComponent(arg));
  else if (sec) goTo(sec);
}
window.addEventListener("hashchange", route);
function setupScroll() {
  const bar = $("#scroll-progress"), top = $("#to-top");
  const onScroll = () => {
    const max = document.documentElement.scrollHeight - innerHeight;
    bar.style.transform = `scaleX(${max > 0 ? scrollY / max : 0})`;
    top.classList.toggle("hidden", scrollY < 600);
  };
  addEventListener("scroll", onScroll, { passive: true }); onScroll();
  top.onclick = () => scrollTo({ top: 0, behavior: REDUCED ? "auto" : "smooth" });
  if (!("IntersectionObserver" in window)) { document.querySelectorAll(".reveal").forEach((e) => e.classList.add("in")); return; }
  const reveal = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("in"); reveal.unobserve(e.target); } }), { threshold: 0.08 });
  document.querySelectorAll(".reveal").forEach((e) => reveal.observe(e));
  const spy = new IntersectionObserver((es) => es.forEach((e) => {
    if (e.isIntersecting) document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.tab === e.target.dataset.section));
  }), { rootMargin: "-40% 0px -55% 0px" });
  document.querySelectorAll("[data-section]").forEach((e) => spy.observe(e));
}

// ---------------------------------------------------------------- profile wizard (generated from attribute_registry)
function fieldHTML(a) {
  const id = "f-" + a.key;
  if (a.type === "enum") return `<label>${esc(a.question)}<select id="${id}" data-key="${a.key}"><option value="">—</option>${a.options.map((o) => `<option>${esc(o)}</option>`).join("")}</select></label>`;
  if (a.type === "boolean") return `<label>${esc(a.question)}<select id="${id}" data-key="${a.key}" data-bool="1"><option value="">—</option><option value="true">Yes</option><option value="false">No</option></select></label>`;
  return `<label>${esc(a.question)}<input id="${id}" data-key="${a.key}" type="number" step="any" min="${a.min ?? ""}" max="${a.max ?? ""}" placeholder="${esc(a.unit || "")}"></label>`;
}
const GROUPS = [
  ["About you", ["age", "gender", "state", "area_type", "marital_status"]],
  ["Income & work", ["annual_income", "occupation", "is_income_tax_payer", "land_holding_hectares"]],
  ["Education", ["is_student", "education_level", "marks_percent"]],
  ["Household & status", ["category", "is_bpl", "is_minority", "is_citizen", "has_disability", "disability_percent"]],
];
function formHTML(attrs) {
  const by = Object.fromEntries(attrs.map((a) => [a.key, a]));
  const used = new Set(GROUPS.flatMap((g) => g[1]));
  const extra = attrs.filter((a) => !used.has(a.key)).map((a) => a.key);
  return GROUPS.map(([title, keys], i) => {
    const ks = (i === GROUPS.length - 1 ? keys.concat(extra) : keys).filter((k) => by[k]);
    return `<fieldset class="group-block"><legend><span class="step">${i + 1}</span>${esc(title)}</legend><div class="fields">${ks.map((k) => fieldHTML(by[k])).join("")}</div></fieldset>`;
  }).join("");
}
function updateProgress() {
  const els = [...document.querySelectorAll("#fields [data-key]")];
  const n = els.filter((e) => e.value !== "").length;
  $("#prog-label").textContent = `${n} of ${els.length} answered`;
  $("#prog-bar").style.width = (els.length ? (n / els.length) * 100 : 0) + "%";
}
function readProfile() {
  const p = {};
  document.querySelectorAll("#fields [data-key]").forEach((el) => {
    if (el.value === "") return;
    p[el.dataset.key] = el.dataset.bool ? el.value === "true" : el.type === "number" ? Number(el.value) : el.value;
  });
  return p;
}
function writeProfile(p) {
  document.querySelectorAll("#fields [data-key]").forEach((el) => {
    const v = p[el.dataset.key]; el.value = v === undefined || v === null ? "" : String(v);
  });
  updateProgress();
}

async function check(e) {
  e && e.preventDefault();
  const profile = readProfile();
  store.set("profile", profile);
  const btn = $("#profile-form button[type=submit]"); btn.disabled = true;
  try {
    const r = await getJSON("/eligibility/check", { method: "POST", body: { profile } });
    renderResults(r);
    loadRecommendations(profile);
  } catch (err) { toast(err.message, true); } finally { btn.disabled = false; }
}

function resultCard(r) {
  const reasons = r.reasons.map((x) => `<li class="r-${x.result}">${esc(x.detail)}</li>`).join("");
  const unm = r.unmapped_conditions?.length ? `<div class="warn">Also check (not machine-verified): ${r.unmapped_conditions.map(esc).join("; ")}</div>` : "";
  const missing = r.missing_attributes?.length ? `<div class="warn">Tell us: ${r.missing_attributes.map((m) => m.replace(/_/g, " ")).join(", ")}</div>` : "";
  return `<div class="res"><div class="res-head"><a href="#schemes/${encodeURIComponent(r.slug)}">${esc(r.name)}</a>
    <span class="badge b-${r.verdict}">${LABEL[r.verdict]}</span></div>
    <div class="muted">${r.level === "state" ? esc(r.state) : "Central"} · rules v${r.scheme_version} · <a href="${esc(r.source_url)}" target="_blank" rel="noopener">official page</a></div>
    <ul class="reasons">${reasons}</ul>${missing}${unm}${r.verdict !== "INELIGIBLE" ? `<div class="row">${saveBtn(r.slug)}</div>` : ""}</div>`;
}
function renderResults(r) {
  const q = ATTRS.find((a) => a.key === r.next_question);
  const nq = $("#next-q");
  if (q) {
    nq.innerHTML = `<b>Next best question:</b> ${esc(q.question)} <span class="muted">— answering it can settle the most “needs more info” schemes.</span> <button class="ghost" id="goto-q">Answer it</button>`;
    nq.classList.remove("hidden");
    $("#goto-q").onclick = () => { const el = $("#f-" + q.key); el.focus(); el.scrollIntoView({ block: "center" }); };
  } else nq.classList.add("hidden");
  const sec = (title, list, open = true) => `<div class="group"><h3>${title} <span class="badge b-${list[0]?.verdict || ""}">${list.length}</span></h3>
    ${list.length ? (open ? list.map(resultCard).join("") : `<details><summary>Show ${list.length} with reasons</summary>${list.map(resultCard).join("")}</details>`) : '<div class="muted">None</div>'}</div>`;
  $("#results").innerHTML = `<div id="recs"></div><div class="muted" style="margin-bottom:8px">Checked ${r.evaluated} published schemes in ${r.elapsed_ms} ms · run <code>${esc(r.run_id)}</code> saved to the audit log</div>
    ${sec("Eligible", r.eligible)}${sec("Needs more information", r.needs_more_info)}${sec("Not eligible", r.ineligible, false)}`;
  document.querySelectorAll("#results .res").forEach((el, i) => { el.style.animationDelay = Math.min(i, 12) * 45 + "ms"; });
  $("#results-col").scrollIntoView({ behavior: REDUCED ? "auto" : "smooth", block: "start" });
}

// ---------------------------------------------------------------- chat (SSE over fetch)
const EXAMPLES = ["What documents are needed for Atal Pension Yojana?", "Am I eligible for Atal Pension Yojana?",
  "Which schemes help SC entrepreneurs?", "Scholarships for OBC students", "How do I apply for Aam Aadmi Bima Yojana in Assam?", "Who will win the cricket match?"];
function addMsg(cls, html) { const d = document.createElement("div"); d.className = "msg " + cls; d.innerHTML = html; $("#chat-log").appendChild(d); d.scrollIntoView({ block: "end" }); return d; }
async function ask(q) {
  if (!q.trim()) return;
  addMsg("user", esc(q));
  const bot = addMsg("bot", '<span class="muted">Searching sources…</span>');
  const profile = store.get("profile", {});
  try {
    const res = await api("/chat", { method: "POST", body: { question: q, profile, stream: true } });
    const reader = res.body.getReader(), dec = new TextDecoder();
    let buf = "", text = "", done = null;
    for (;;) {
      const { value, done: end } = await reader.read();
      if (end) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const block = buf.slice(0, i); buf = buf.slice(i + 2);
        const ev = (block.match(/^event: (.*)$/m) || [])[1] || "message";
        const data = JSON.parse(block.slice(block.indexOf("data: ") + 6));
        if (ev === "message") { text += data; bot.textContent = text; }
        if (ev === "done") done = data;
      }
    }
    if (done) {
      const chips = (done.citations || []).map((c) => `<a class="chip src" href="${esc(c.source_url)}" target="_blank" rel="noopener">[${c.n}] ${esc(c.scheme_name)} · ${esc(c.section)}</a>`).join("");
      bot.innerHTML = esc(text).replace(/\[(\d+)\]/g, '<sup>[$1]</sup>') + (chips ? `<div class="chips">${chips}</div>` : "");
    }
  } catch (err) { bot.innerHTML = `<span style="color:var(--fail)">${esc(err.message)}</span>`; }
}

// ---------------------------------------------------------------- schemes
let schemePage = 1;
async function loadSchemes(page) {
  schemePage = page;
  const p = new URLSearchParams({ page, size: 15 });
  [["q", "#sf-q"], ["level", "#sf-level"], ["state", "#sf-state"], ["status", "#sf-status"]].forEach(([k, s]) => $(s).value && p.set(k, $(s).value));
  try {
    const r = await getJSON("/schemes?" + p);
    $("#scheme-list").dataset.loaded = 1;
    $("#scheme-list").innerHTML = r.items.length ? `<table><tr><th>Scheme</th><th>Level</th><th>Tags</th><th>Rules</th></tr>${r.items.map((s) => `<tr>
      <td><a href="#schemes/${encodeURIComponent(s.slug)}">${esc(s.name)}</a></td><td>${s.level === "state" ? esc(s.state) : "Central"}</td>
      <td class="muted">${esc((s.tags || []).slice(0, 4).join(", "))}</td><td><span class="badge b-${s.status}">${s.status.replace("_", " ")}${s.current_version ? " v" + s.current_version : ""}</span></td></tr>`).join("")}</table>`
      : '<div class="empty">No schemes match.</div>';
    const pages = Math.ceil(r.total / r.size);
    $("#pager").innerHTML = `<span class="muted">${r.total} schemes · page ${page} of ${pages || 1}</span>
      <button class="ghost" ${page <= 1 ? "disabled" : ""} onclick="loadSchemes(${page - 1})">Prev</button>
      <button class="ghost" ${page >= pages ? "disabled" : ""} onclick="loadSchemes(${page + 1})">Next</button>`;
  } catch (err) { toast(err.message, true); }
}
function treeHTML(n) {
  if (!n) return '<span class="muted">No published rules yet (in review).</span>';
  if (n.attribute) return `<li><b>${esc(n.attribute)}</b> ${esc(n.operator)} <code>${esc(JSON.stringify(n.value))}</code> — ${esc(n.description || "")}${n.source_quote ? `<div class="q">“${esc(n.source_quote)}”</div>` : ""}</li>`;
  return `<li><span class="grp">${n.op}</span><ul>${n.children.map(treeHTML).join("")}</ul></li>`;
}
async function openScheme(slug) {
  try {
    const s = await getJSON("/schemes/" + encodeURIComponent(slug));
    const sec = s.sections || {};
    const part = (k, t) => sec[k] ? `<details ${k === "eligibility" ? "open" : ""}><summary><b>${t}</b></summary><p>${esc(sec[k])}</p></details>` : "";
    $("#scheme-detail").innerHTML = `<div class="res-head"><h2>${esc(s.name)}</h2><span class="row">${s.status !== "retired" ? saveBtn(s.slug) : ""}<span class="badge b-${s.status}">${s.status.replace("_", " ")}</span></span></div>
      <div class="muted">${s.level === "state" ? esc(s.state) : "Central scheme"} · <a href="${esc(s.source_url)}" target="_blank" rel="noopener">official myScheme page</a>
      · last verified: ${s.last_verified_at ? new Date(s.last_verified_at).toLocaleDateString() : "not yet"} ${s.stale ? '<span class="badge b-INELIGIBLE">stale — verify</span>' : ""}</div>
      <h3>Eligibility rules ${s.current_version ? "(version " + s.current_version + ")" : ""}</h3><ul class="tree">${treeHTML(s.eligibility)}</ul>
      ${(s.unmapped_conditions || []).length ? `<div class="warn">Not machine-checkable: ${s.unmapped_conditions.map(esc).join("; ")}</div>` : ""}
      ${s.versions.length ? `<h3>Version history</h3><table><tr><th>v</th><th>Effective</th><th>Reviewed by</th><th>Extracted by</th><th>Note</th></tr>${s.versions.map((v) => `<tr><td>${v.version}</td><td>${new Date(v.effective_from).toLocaleString()}</td><td>${esc(v.reviewed_by)}</td><td>${esc(v.extracted_by)}</td><td>${esc(v.change_note)}</td></tr>`).join("")}</table>` : ""}
      <h3>Scheme text</h3>${part("description", "Details")}${part("benefits", "Benefits")}${part("eligibility", "Eligibility")}${part("exclusions", "Exclusions")}${part("application", "Application process")}${part("documents", "Documents required")}`;
    $("#scheme-detail").classList.remove("hidden");
    $("#scheme-detail").scrollIntoView({ behavior: "smooth" });
  } catch (err) { toast(err.message, true); }
}

// ---------------------------------------------------------------- citizen account (shown only when signed in)
async function renderAccount() {
  const show = !!me && !isAdmin();
  $("#account").classList.toggle("hidden", !show);
  document.querySelectorAll('[data-tab="account"]').forEach((a) => a.classList.toggle("hidden", !show));
  document.querySelectorAll(".user-only").forEach((e) => e.classList.toggle("hidden", !me));
  if (!show) return;
  $("#me-info").innerHTML = `Signed in as <b>${esc(me.name || me.email)}</b> · ${esc(me.email)} · Citizen account`;
  try {
    const h = await getJSON("/eligibility/history");
    $("#history").innerHTML = h.length ? `<table><tr><th>When</th><th>Eligible</th><th>More info</th><th>Not eligible</th></tr>${h.map((r) => `<tr><td>${new Date(r.evaluated_at).toLocaleString()}</td><td>${r.eligible}</td><td>${r.needs_more_info}</td><td>${r.ineligible}</td></tr>`).join("")}</table>` : '<div class="muted">No checks yet.</div>';
  } catch (err) { toast(err.message, true); }
}

// ---------------------------------------------------------------- grievance portal (citizen side)
async function loadGrievances() {
  const logged = !!me;
  $("#grv-login-link").href = "/login?next=" + encodeURIComponent("/#grievances");
  $("#grv-login").classList.toggle("hidden", logged);
  $("#grv-app").classList.toggle("hidden", !logged);
  if (!logged) return;
  try {
    if (!SCHEME_NAMES.length) {
      SCHEME_NAMES = await getJSON("/schemes/names");
      $("#scheme-names").innerHTML = SCHEME_NAMES.map((s) => `<option value="${esc(s.name)}"></option>`).join("");
    }
    const runs = await getJSON("/eligibility/history");
    $("#grv-run").innerHTML = '<option value="">— none —</option>' + runs.map((r) => `<option value="${esc(r._id)}">${fmtDate(r.evaluated_at)} · ${r.eligible} eligible, ${r.needs_more_info} need info</option>`).join("");
    const list = await getJSON("/grievances");
    const counts = list.reduce((a, g) => ((a[g.status] = (a[g.status] || 0) + 1), a), {});
    $("#grv-counts").innerHTML = Object.entries(G_STATUS).map(([k, v]) => `<span class="badge b-${k}">${v}: ${counts[k] || 0}</span>`).join(" ");
    $("#grv-list").innerHTML = list.length ? list.map((g) => grievanceCard(g)).join("") : '<div class="muted">No grievances yet. Use the form to file one.</div>';
  } catch (err) { toast(err.message, true); }
}

async function fileGrievance(e) {
  e.preventDefault();
  const name = $("#grv-scheme").value.trim();
  const scheme = SCHEME_NAMES.find((s) => s.name.toLowerCase() === name.toLowerCase());
  if (!scheme) return toast("Pick a scheme from the suggestions list", true);
  const body = { scheme_slug: scheme.slug, category: $("#grv-category").value, subject: $("#grv-subject").value.trim(),
                 description: $("#grv-desc").value.trim(), run_id: $("#grv-run").value || null };
  const btn = $("#grv-form button"); btn.disabled = true;
  try {
    const r = await getJSON("/grievances", { method: "POST", body });
    toast(`Grievance ${r.ticket} filed`);
    ["#grv-scheme", "#grv-subject", "#grv-desc"].forEach((s) => ($(s).value = ""));
    loadGrievances();
  } catch (err) { toast(err.message, true); } finally { btn.disabled = false; }
}

// ---------------------------------------------------------------- recommendations (ranked by an aggregation pipeline)
const SAVED = new Set();
const isCitizen = () => !!me && !isAdmin();

function saveBtn(slug) {
  if (isAdmin()) return "";
  const done = SAVED.has(slug);
  return `<button class="ghost small save-btn${done ? " saved" : ""}" data-save="${esc(slug)}" ${done ? "disabled" : ""}>${done ? "✓ In tracker" : "＋ Save to tracker"}</button>`;
}

async function loadRecommendations(profile) {
  const box = $("#recs");
  box.innerHTML = '<div class="muted">Ranking schemes for you…</div>';
  try {
    const r = await getJSON("/recommendations", { method: "POST", body: { profile } });
    if (!r.items.length) { box.innerHTML = ""; return; }
    const w = r.weights;
    box.innerHTML = `<div class="rec-head"><h3>Recommended for you</h3>
        <span class="muted">Ranked by a MongoDB aggregation: ${Math.round(w.rule_match * 100)}% conditions met · ${Math.round(w.group_match * 100)}% match with your groups${r.group_labels.length ? ` (${r.group_labels.map(esc).join(", ")})` : ""} · ${Math.round(w.popularity * 100)}% saves by similar users</span></div>
      <ol class="rec-list">${r.items.map((it, i) => `<li class="rec">
        <div class="rec-rank">${i + 1}</div>
        <div class="rec-body"><div class="res-head"><a href="#schemes/${encodeURIComponent(it.slug)}">${esc(it.name)}</a>${it.verified
          ? `<span class="badge b-${it.verdict}">${LABEL[it.verdict]}</span>` : '<span class="badge b-unverified" title="Rules read automatically, not yet checked by a reviewer">Possible match · unverified</span>'}</div>
          <div class="muted">${it.level === "state" ? esc(it.state) : "Central"} scheme</div>
          <div class="score-row"><div class="score-bar" title="Score ${it.score}">
            <span class="sb-rule" style="width:${it.parts.rule_match * 100}%"></span><span class="sb-group" style="width:${it.parts.group_match * 100}%"></span><span class="sb-pop" style="width:${it.parts.popularity * 100}%"></span></div>
            <b>${it.score.toFixed(2)}</b></div>
          <ul class="why">${it.why.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>
        <div class="rec-act">${saveBtn(it.slug)}</div></li>`).join("")}</ol>
      <div class="legend small"><span class="lg-bar sb-rule"></span>Conditions met<span class="lg-bar sb-group"></span>Meant for your groups<span class="lg-bar sb-pop"></span>Similar users
        <span class="muted">· checked ${r.candidates.verified} reviewed and ${r.candidates.unverified} not-yet-reviewed schemes for you</span></div>`;
    document.querySelectorAll("#recs .rec").forEach((el, i) => { el.style.animationDelay = i * 50 + "ms"; });
  } catch (err) { box.innerHTML = `<div class="warn">${esc(err.message)}</div>`; }
}

document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-save]");
  if (!b) return;
  if (!me) { location.href = "/login?next=" + encodeURIComponent("/#tracker"); return; }
  b.disabled = true;
  try {
    await getJSON("/applications", { method: "POST", body: { scheme_slug: b.dataset.save } });
    toast("Saved to your tracker");
  } catch (err) { if (!/Already/.test(err.message)) { toast(err.message, true); b.disabled = false; return; } }
  SAVED.add(b.dataset.save);
  document.querySelectorAll(`[data-save="${CSS.escape(b.dataset.save)}"]`).forEach((x) => { x.outerHTML = saveBtn(b.dataset.save); });
  loadTracker();
});

// ---------------------------------------------------------------- application tracker (citizen's own record)
const A_STATUS = { not_started: "Not started", applied: "Applied", approved: "Approved", rejected: "Rejected" };
const dateInput = (d) => (d ? new Date(d).toISOString().slice(0, 10) : "");

function dueLabel(a) {
  if (a.days_left === null || a.days_left === undefined) return '<span class="muted">No deadline set</span>';
  if (!["not_started", "applied"].includes(a.status)) return `<span class="muted">Deadline ${new Date(a.deadline).toLocaleDateString()}</span>`;
  if (a.days_left < 0) return `<span class="due overdue">Overdue by ${-a.days_left} day${a.days_left === -1 ? "" : "s"}</span>`;
  if (a.days_left <= a.reminder_days) return `<span class="due soon">Due ${a.days_left === 0 ? "today" : `in ${a.days_left} day${a.days_left === 1 ? "" : "s"}`}</span>`;
  return `<span class="due">Due in ${a.days_left} days</span>`;
}

function trackerCard(a) {
  const pct = a.docs_total ? Math.round((a.docs_done / a.docs_total) * 100) : 0;
  return `<div class="res app-card st-${a.status}" data-app="${esc(a.scheme_slug)}">
    <div class="res-head"><a href="#schemes/${encodeURIComponent(a.scheme_slug)}">${esc(a.scheme_name)}</a>${dueLabel(a)}</div>
    <div class="app-controls">
      <label>My status<select data-a-status>${Object.entries(A_STATUS).map(([k, v]) => `<option value="${k}" ${k === a.status ? "selected" : ""}>${v}</option>`).join("")}</select></label>
      <label>My deadline<input type="date" data-a-deadline value="${dateInput(a.deadline)}"></label>
      <label>Remind me<select data-a-remind>${[0, 1, 3, 7, 14].map((d) => `<option value="${d}" ${d === a.reminder_days ? "selected" : ""}>${d ? `${d} day${d > 1 ? "s" : ""} before` : "On the day"}</option>`).join("")}</select></label>
    </div>
    <div class="doc-progress"><span>Documents ${a.docs_done}/${a.docs_total}</span><div class="progress"><div style="width:${pct}%"></div></div></div>
    <ul class="checklist">${a.documents.map((d) => `<li class="${d.done ? "done" : ""}"><label><input type="checkbox" data-doc="${esc(d.id)}" ${d.done ? "checked" : ""}> ${esc(d.name)}</label>
      <button class="link-btn" data-doc-del="${esc(d.id)}" title="Remove">×</button></li>`).join("") || '<li class="muted">No documents listed for this scheme. Add your own below.</li>'}</ul>
    <form class="row add-doc" data-add-doc><input maxlength="160" placeholder="Add a document to the checklist"><button class="ghost small">Add</button></form>
    <details><summary>Notes &amp; status history (${a.history.length})</summary>
      <textarea data-a-notes maxlength="2000" placeholder="Your own notes (application number, office visited, …)">${esc(a.notes || "")}</textarea>
      <ol class="timeline">${a.history.map((h) => `<li class="tl-user"><div class="tl-head"><span class="badge b-st-${h.status}">${A_STATUS[h.status]}</span><span class="muted">${fmtDate(h.at)}</span></div>${h.note ? `<div>${esc(h.note)}</div>` : ""}</li>`).join("")}</ol>
      <div class="row"><button class="ghost small" data-a-save-notes>Save notes</button><button class="danger small" data-a-remove>Remove from tracker</button></div></details>
  </div>`;
}

async function loadTracker() {
  const sec = $("#tracker");
  const show = isCitizen();
  sec.classList.toggle("hidden", !show);
  document.querySelectorAll('[data-tab="tracker"]').forEach((a) => a.classList.toggle("hidden", !show));
  if (!show) return;
  try {
    const [apps, rem] = await Promise.all([getJSON("/applications"), getJSON("/applications/reminders")]);
    SAVED.clear(); apps.forEach((a) => SAVED.add(a.scheme_slug));
    document.querySelectorAll("[data-save]").forEach((x) => { x.outerHTML = saveBtn(x.dataset.save); });
    const counts = apps.reduce((m, a) => ((m[a.status] = (m[a.status] || 0) + 1), m), {});
    $("#tr-summary").innerHTML = Object.entries(A_STATUS).map(([k, v]) => `<span class="badge b-st-${k}">${v}: ${counts[k] || 0}</span>`).join(" ");
    const alerts = [];
    if (rem.overdue.length) alerts.push(`<b>Overdue:</b> ${rem.overdue.map((x) => esc(x.scheme_name)).join(", ")}`);
    if (rem.due_soon.length) alerts.push(`<b>Coming up:</b> ${rem.due_soon.map((x) => `${esc(x.scheme_name)} (${x.days_left === 0 ? "today" : `in ${x.days_left} day${x.days_left === 1 ? "" : "s"}`}, documents ${x.docs_done}/${x.docs_total})`).join("; ")}`);
    $("#tr-reminders").innerHTML = alerts.length ? `🔔 ${alerts.join("<br>")} <span class="muted">· ${rem.this_week} deadline${rem.this_week === 1 ? "" : "s"} in the next 7 days</span>` : "";
    $("#tr-reminders").classList.toggle("hidden", !alerts.length);
    $("#tr-list").innerHTML = apps.length ? apps.map(trackerCard).join("")
      : '<div class="empty">Nothing saved yet. Use <b>＋ Save to tracker</b> on a recommended scheme, a result or a scheme page.</div>';
  } catch (err) { toast(err.message, true); }
}

async function patchApp(slug, body, msg) {
  try { await getJSON(`/applications/${encodeURIComponent(slug)}`, { method: "PATCH", body }); if (msg) toast(msg); loadTracker(); }
  catch (err) { toast(err.message, true); }
}

document.addEventListener("change", async (e) => {
  const card = e.target.closest(".app-card");
  if (!card) return;
  const slug = card.dataset.app;
  if (e.target.matches("[data-a-status]")) {
    const note = e.target.value === "applied" ? "Marked as applied" : "";
    return patchApp(slug, { status: e.target.value, note }, "Status updated");
  }
  if (e.target.matches("[data-a-deadline]")) return patchApp(slug, { deadline: e.target.value }, e.target.value ? "Deadline saved" : "Deadline cleared");
  if (e.target.matches("[data-a-remind]")) return patchApp(slug, { reminder_days: Number(e.target.value) }, "Reminder updated");
  if (e.target.matches("[data-doc]")) {
    try { await getJSON(`/applications/${encodeURIComponent(slug)}/documents/${e.target.dataset.doc}`, { method: "PATCH", body: { done: e.target.checked } }); loadTracker(); }
    catch (err) { toast(err.message, true); }
  }
});

document.addEventListener("click", async (e) => {
  const card = e.target.closest(".app-card");
  if (!card) return;
  const slug = card.dataset.app;
  const del = e.target.closest("[data-doc-del]");
  try {
    if (del) {
      await getJSON(`/applications/${encodeURIComponent(slug)}/documents/${del.dataset.docDel}`, { method: "DELETE" });
      loadTracker();
    } else if (e.target.closest("[data-a-save-notes]")) {
      await patchApp(slug, { notes: card.querySelector("[data-a-notes]").value }, "Notes saved");
    } else if (e.target.closest("[data-a-remove]")) {
      if (!confirm("Remove this scheme and its checklist from your tracker?")) return;
      await getJSON(`/applications/${encodeURIComponent(slug)}`, { method: "DELETE" });
      SAVED.delete(slug); toast("Removed from tracker"); loadTracker();
    }
  } catch (err) { toast(err.message, true); }
});

document.addEventListener("submit", async (e) => {
  const f = e.target.closest("[data-add-doc]");
  if (!f) return;
  e.preventDefault();
  const name = f.querySelector("input").value.trim();
  if (name.length < 2) return;
  try { await getJSON(`/applications/${encodeURIComponent(f.closest(".app-card").dataset.app)}/documents`, { method: "POST", body: { name } }); loadTracker(); }
  catch (err) { toast(err.message, true); }
});

// ---------------------------------------------------------------- boot
(async function boot() {
  renderUserArea();
  try { ATTRS = await getJSON("/attributes"); } catch (err) { toast("API unavailable: " + err.message, true); }
  $("#fields").innerHTML = formHTML(ATTRS);
  $("#fields").addEventListener("input", updateProgress); $("#fields").addEventListener("change", updateProgress);
  const st = ATTRS.find((a) => a.key === "state");
  if (st) $("#sf-state").innerHTML += st.options.map((o) => `<option>${esc(o)}</option>`).join("");
  writeProfile(store.get("profile", {}));
  if (token && !isAdmin()) { try { const p = await getJSON("/profile"); if (p.attributes && Object.keys(p.attributes).length && !Object.keys(store.get("profile", {})).length) writeProfile(p.attributes); } catch { } }
  $("#profile-form").onsubmit = check;
  $("#clear-profile").onclick = () => { writeProfile({}); store.set("profile", {}); };
  document.querySelectorAll('a[href="#top"]').forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); scrollTo({ top: 0, behavior: REDUCED ? "auto" : "smooth" }); }));
  $("#save-profile").onclick = async () => {
    if (!confirm("Store this profile on the server so you don't have to re-enter it? You can delete it any time.")) return;
    try { await api("/profile", { method: "PUT", body: { attributes: readProfile(), consent: true } }); toast("Profile saved"); } catch (err) { toast(err.message, true); }
  };
  $("#chat-form").onsubmit = (e) => { e.preventDefault(); const q = $("#chat-q").value; $("#chat-q").value = ""; ask(q); };
  $("#examples").innerHTML = EXAMPLES.map((q) => `<a class="chip">${esc(q)}</a>`).join("");
  $("#examples").onclick = (e) => { if (e.target.classList.contains("chip")) ask(e.target.textContent); };
  $("#scheme-filter").onsubmit = (e) => { e.preventDefault(); loadSchemes(1); };
  $("#delete-data").onclick = async () => {
    if (!confirm("Delete your saved profile and all your check history?")) return;
    try { const r = await getJSON("/profile", { method: "DELETE" }); toast(`Deleted profile (${r.deleted_profile}) and ${r.deleted_evaluations} evaluations`); renderAccount(); } catch (err) { toast(err.message, true); }
  };
  $("#grv-form").onsubmit = fileGrievance;
  renderAccount();
  setupScroll();
  loadSchemes(1);
  loadGrievances();
  loadTracker();
  getJSON("/schemes?size=1").then((r) => { $("#hero-count").textContent = r.total; }).catch(() => { });
  route();
})();
