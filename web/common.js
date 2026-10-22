// Shared by every page: API client, session, header user area, grievance cards.
const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const store = {
  get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode */ } },
};
let token = store.get("token", null), me = store.get("me", null);
const LABEL = { ELIGIBLE: "Eligible", INELIGIBLE: "Not eligible", NEEDS_MORE_INFO: "Needs more info" };

function toast(msg, err = false) {
  const t = $("#toast"); t.textContent = msg; t.className = "toast" + (err ? " err" : "");
  clearTimeout(t._h); t._h = setTimeout(() => t.classList.add("hidden"), 3500);
}

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json", ...(token ? { Authorization: "Bearer " + token } : {}) };
  const res = await fetch("/api" + path, { ...opts, headers, body: opts.body ? JSON.stringify(opts.body) : undefined });
  if (!res.ok) {
    let msg = res.statusText;
    try { const j = await res.json(); msg = typeof j.detail === "string" ? j.detail : j.detail.map((d) => `${d.loc.slice(-1)[0]}: ${d.msg}`).join("; "); } catch { }
    if (res.status === 401 && token) { clearSession(); }
    throw new Error(msg);
  }
  return res;
}
const getJSON = async (p, o) => (await api(p, o)).json();

const isAdmin = () => !!(me && me.role === "admin");
function saveSession(t, u) { token = t; me = u; store.set("token", t); store.set("me", u); }
function clearSession() { saveSession(null, null); renderUserArea(); }
function logout() { clearSession(); location.href = "/"; }

// Header: a Login button when signed out; name, role, dashboard link and Logout when signed in.
function renderUserArea() {
  const box = $("#user-area");
  if (!box) return;
  if (!me) {
    const next = encodeURIComponent(location.pathname + location.hash);
    box.innerHTML = `<a class="btn primary small" href="/login?next=${next}">Login</a>`;
    return;
  }
  const name = me.name || me.email.split("@")[0];
  const onAdmin = location.pathname === "/admin";
  box.innerHTML = `${isAdmin() && !onAdmin ? '<a class="nav-link" href="/admin">Admin dashboard</a>' : ""}${onAdmin ? '<a class="nav-link" href="/">Public site</a>' : ""}
    <span class="user-chip" title="${esc(me.email)}"><span class="avatar">${esc(name[0].toUpperCase())}</span>${esc(name)}<span class="role role-${esc(me.role)}">${isAdmin() ? "Admin" : "Citizen"}</span></span>
    <button class="ghost small" id="logout-btn">Logout</button>`;
  $("#logout-btn").onclick = logout;
}

// ---------------------------------------------------------------- grievance cards (citizen + officer views)
const G_STATUS = { open: "Open", in_progress: "In progress", resolved: "Resolved", closed: "Closed" };
const G_CAT = {
  application_status: "Application status / delay", eligibility_result: "Eligibility result", benefit_not_received: "Benefit not received",
  documents: "Documents", wrong_information: "Wrong information", portal_issue: "Portal / technical", other: "Other",
};
let SCHEME_NAMES = [];
const fmtDate = (d) => new Date(d).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

function timelineHTML(g, admin = false) {
  return `<ol class="timeline">${g.timeline.map((t) => `<li class="tl-${t.by}">
    <div class="tl-head"><b>${t.by === "admin" ? "Officer" : admin ? "Citizen" : "You"}</b> · ${esc(t.action.replace("_", " "))}${t.status ? ` → <span class="badge b-${t.status}">${G_STATUS[t.status]}</span>` : ""}
    <span class="muted">${fmtDate(t.at)}</span></div>${t.note ? `<div>${esc(t.note)}</div>` : ""}</li>`).join("")}</ol>`;
}

function grievanceCard(g, admin = false) {
  const closed = ["resolved", "closed"].includes(g.status);
  const actions = admin
    ? `<div class="row wrap gq-actions"><select data-gq-status>${Object.entries(G_STATUS).map(([k, v]) => `<option value="${k}" ${k === g.status ? "selected" : ""}>${v}</option>`).join("")}</select>
        <select data-gq-priority>${["low", "normal", "high"].map((p) => `<option ${p === g.priority ? "selected" : ""}>${p}</option>`).join("")}</select>
        <input data-gq-note maxlength="2000" placeholder="Note to the citizen (required)"><button class="primary" data-gq-save="${esc(g.ticket)}">Update</button></div>`
    : `<div class="row wrap"><input data-g-note maxlength="2000" placeholder="${closed ? "Add a comment (tick reopen if not solved)" : "Add a comment or more details"}">
        ${closed ? '<label class="inline"><input type="checkbox" data-g-reopen> Reopen</label>' : ""}<button class="ghost" data-g-comment="${esc(g.ticket)}">Send</button></div>`;
  return `<div class="res grv" data-ticket="${esc(g.ticket)}">
    <div class="res-head"><div><b>${esc(g.subject)}</b><div class="muted">${esc(g.ticket)} · ${esc(g.scheme_name || g.scheme_slug)} · ${G_CAT[g.category] || esc(g.category)}${admin && g.filer ? ` · ${esc(g.filer.email)}` : ""}</div></div>
      <span class="badge b-${g.status}">${G_STATUS[g.status]}</span></div>
    <details><summary>Details &amp; timeline (${g.timeline.length})</summary>
      <p>${esc(g.description)}</p>${g.run_id ? `<div class="muted">Linked eligibility check: <code>${esc(g.run_id)}</code></div>` : ""}
      ${timelineHTML(g, admin)}${actions}</details></div>`;
}

document.addEventListener("click", async (e) => {
  const c = e.target.closest("[data-g-comment]"), s = e.target.closest("[data-gq-save]");
  if (!c && !s) return;
  const card = e.target.closest(".grv");
  try {
    if (c) {
      const note = card.querySelector("[data-g-note]").value.trim();
      if (note.length < 2) return toast("Write a comment first", true);
      const reopen = !!card.querySelector("[data-g-reopen]")?.checked;
      await getJSON(`/grievances/${encodeURIComponent(c.dataset.gComment)}/comments`, { method: "POST", body: { note, reopen } });
      toast(reopen ? "Grievance reopened" : "Comment added"); if (typeof loadGrievances === "function") loadGrievances();
    } else {
      const note = card.querySelector("[data-gq-note]").value.trim();
      if (note.length < 2) return toast("Add a note for the citizen", true);
      await getJSON(`/admin/grievances/${encodeURIComponent(s.dataset.gqSave)}/status`, { method: "POST",
        body: { status: card.querySelector("[data-gq-status]").value, priority: card.querySelector("[data-gq-priority]").value, note } });
      toast("Grievance updated"); if (typeof loadGrievanceQueue === "function") loadGrievanceQueue();
    }
  } catch (err) { toast(err.message, true); }
});

