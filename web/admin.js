// Admin dashboard (loads after common.js). Every call here is also checked server-side by require_admin.
// ---------------------------------------------------------------- admin
async function loadAdmin() {
  try {
    const s = await getJSON("/admin/stats");
    const max = Math.max(1, ...s.most_missing.map((m) => m.n));
    $("#stats").innerHTML = `<div class="kpis">${Object.entries(s.counts).map(([k, v]) => `<div class="kpi"><b>${v}</b><span class="muted">${k}</span></div>`).join("")}</div>
      <h3>Verdicts across all checks</h3><div>${s.verdicts.map((v) => `<span class="badge b-${v._id}">${LABEL[v._id]}: ${v.n}</span>`).join(" ")}</div>
      <h3>Most-missing answers</h3><table>${s.most_missing.map((m) => `<tr><td>${esc(m._id)}</td><td style="width:60%"><div class="bar" style="width:${(m.n / max) * 100}%"></div></td><td>${m.n}</td></tr>`).join("")}</table>
      <h3>Schemes by state</h3><table><tr><th>State</th><th>Published</th><th>Total</th></tr>${s.schemes_by_state.map((r) => `<tr><td>${esc(r._id)}</td><td>${r.published}</td><td>${r.total}</td></tr>`).join("")}</table>`;
    loadGrievanceQueue();
  } catch (err) { toast(err.message, true); }
}
async function loadGrievanceQueue() {
  try {
    const st = $("#gq-status").value;
    const r = await getJSON("/admin/grievances?size=20" + (st ? "&status=" + st : ""));
    $("#gq-list").innerHTML = `<div class="muted">${r.total} grievances</div>` + (r.items.map((g) => grievanceCard(g, true)).join("") || '<div class="muted">Nothing here.</div>');
  } catch (err) { toast(err.message, true); }
}


// ---------------------------------------------------------------- coverage gap analytics
const GAP_COLOR = { high: "#c2410c", medium: "#e8871e", low: "#2e7d5b", none: "#94a3b8" };
let covMap = null;

// Long tables show their top rows; the rest open in place, so the two columns stay balanced.
function moreRows(rest, head, row, noun) {
  return rest.length ? `<details class="more"><summary>Show ${rest.length} more ${noun}</summary><table>${head}${rest.map(row).join("")}</table></details>` : "";
}

function barRow(label, value, max, extra = "") {
  return `<tr><td>${label}</td><td style="width:45%"><div class="bar" style="width:${max ? (value / max) * 100 : 0}%"></div></td><td>${value}</td>${extra}</tr>`;
}

async function loadCoverage() {
  let r;
  try { r = await getJSON("/admin/coverage"); } catch (err) { return toast(err.message, true); }
  const highs = r.regions.filter((x) => x.level === "high");
  const note = $("#cov-note");
  note.innerHTML = `<b>About this data:</b> ${esc(r.note)} Demand covers the last ${r.window_days} days of searches${r.demo_searches ? ` — <b>${r.demo_searches} of ${r.searches}</b> are simulated demo searches (scripts/simulate_searches.py); match counts are computed on the real scheme data` : ""}.`;
  note.classList.remove("hidden");
  $("#cov-kpis").innerHTML = [
    [r.searches, "searches analysed"], [r.central_schemes, "central schemes (all states)"],
    [highs.length, "regions with a high gap"], [r.unmet_searches.length, "unmet search topics"],
  ].map(([v, k]) => `<div class="kpi"><b>${v}</b><span class="muted">${k}</span></div>`).join("");

  const regionRow = (x) => `<tr><td><a href="#" data-near="${esc(x.name)}">${esc(x.name)}</a>${x.uncovered_groups.length ? `<div class="muted">No state scheme for: ${x.uncovered_groups.map((g) => esc(g.label)).join(", ")}</div>` : ""}</td>
      <td>${x.state_schemes}</td><td>${x.searches}</td><td>${Math.round(x.low_match_rate * 100)}%</td>
      <td><span class="badge gap-${x.searches ? x.level : "none"}">${x.gap_index.toFixed(2)}</span></td></tr>`;
  const regHead = "<tr><th>State / UT</th><th>State schemes</th><th>Searches</th><th>Poorly served</th><th>Gap</th></tr>";
  $("#cov-regions").innerHTML = `<table>${regHead}${r.regions.slice(0, 8).map(regionRow).join("")}</table>${moreRows(r.regions.slice(8), regHead, regionRow, "regions")}
    <p class="muted">Gap index = the region's share of all searches ÷ its share of state schemes. 1 is balanced; above 2 means demand far outweighs supply.</p>`;

  const gmax = Math.max(1, ...r.groups.map((g) => g.searches_per_scheme));
  $("#cov-groups").innerHTML = `<table><tr><th>Group</th><th></th><th>Searches / scheme</th><th>Schemes</th><th>Searches</th></tr>${
    r.groups.map((g) => barRow(esc(g.label), g.searches_per_scheme, gmax, `<td>${g.schemes}</td><td>${g.searches}</td>`)).join("")}</table>`;

  const unmetRow = (u) => `<tr><td>“${esc(u.query)}”${u.groups.length ? `<div class="muted">${u.groups.map(esc).join(", ")}</div>` : ""}</td><td>${u.searches}</td><td>${u.avg_results}</td>
      <td class="muted">${u.states.slice(0, 3).map(esc).join(", ")}${u.states.length > 3 ? ` +${u.states.length - 3}` : ""}</td></tr>`;
  const unmetHead = "<tr><th>Search</th><th>Times</th><th>Avg. matches</th><th>Where</th></tr>";
  $("#cov-unmet").innerHTML = r.unmet_searches.length ? `<table>${unmetHead}${r.unmet_searches.slice(0, 8).map(unmetRow).join("")}</table>${moreRows(r.unmet_searches.slice(8), unmetHead, unmetRow, "search topics")}
    <p class="muted">Searches that found ${r.low_match_threshold} or fewer matching schemes, grouped by topic.</p>` : '<div class="muted">No poorly served searches yet.</div>';

  const bandLabel = { 1: "1–4", 5: "5–9", 10: "10–19", 20: "20–39", "40+": "40+" };
  const zero = r.regions.filter((x) => x.state_schemes === 0).map((x) => x.name);
  const bmax = Math.max(1, zero.length, ...r.supply_bands.map((b) => b.states));
  $("#cov-bands").innerHTML = `<table><tr><th>State schemes</th><th></th><th>States</th></tr>${zero.length ? barRow("0", zero.length, bmax) : ""}${
    r.supply_bands.map((b) => barRow(bandLabel[b._id] || b._id, b.states, bmax)).join("")}</table>${zero.length ? `<p class="muted">No state-specific schemes in the dataset: ${zero.map(esc).join(", ")}.</p>` : ""}`;
  const rLabel = { 0: "0 matches", 1: "1–2", 3: "3–5", 6: "6–10", "11+": "11+" };
  const rmax = Math.max(1, ...r.results_bands.map((b) => b.searches));
  $("#cov-rbands").innerHTML = `<table><tr><th>Matching schemes</th><th></th><th>Searches</th></tr>${
    r.results_bands.map((b) => barRow(rLabel[b._id] || b._id, b.searches, rmax)).join("")}</table>`;

  const m = r.matrix, cmax = Math.max(1, ...m.rows.flatMap((row) => Object.values(row.cells)));
  $("#cov-matrix").innerHTML = `<table class="heat"><tr><th>State / UT</th>${m.groups.map((g) => `<th title="${esc(m.labels[g])}">${esc(m.labels[g].split(" ")[0])}</th>`).join("")}</tr>
    <tr class="central-row"><td><b>Central (all states)</b></td>${m.groups.map((g) => `<td>${r.central_by_group[g] || 0}</td>`).join("")}</tr>
    ${m.rows.map((row) => `<tr><td>${esc(row.state)}</td>${m.groups.map((g) => { const v = row.cells[g];
      return `<td class="${v ? "" : "zero"}" style="--h:${v ? (0.15 + 0.85 * (v / cmax)).toFixed(2) : 0}">${v || "·"}</td>`; }).join("")}</tr>`).join("")}</table>`;

  drawMap(r.regions);
}

// Leaflet is loaded in the background so the dashboard never waits on the network.
let leafletReady = null;
function loadLeaflet() {
  if (leafletReady) return leafletReady;
  leafletReady = new Promise((resolve) => {
    const css = document.createElement("link");
    css.rel = "stylesheet"; css.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
    document.head.appendChild(css);
    const js = document.createElement("script");
    js.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"; js.async = true;
    const timer = setTimeout(() => resolve(false), 8000);
    js.onload = () => { clearTimeout(timer); resolve(true); };
    js.onerror = () => { clearTimeout(timer); resolve(false); };
    document.head.appendChild(js);
  });
  return leafletReady;
}

async function drawMap(regions) {
  const el = $("#cov-map");
  if (!(await loadLeaflet()) || typeof L === "undefined") {
    el.innerHTML = '<div class="empty">The map needs an internet connection (map tiles). The tables beside it show the same data.</div>';
    return;
  }
  if (!covMap) {
    covMap = L.map(el, { scrollWheelZoom: false }).setView([22.5, 80.5], 4.4);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 9, attribution: "© OpenStreetMap contributors" }).addTo(covMap);
  }
  covMap.eachLayer((l) => { if (l instanceof L.CircleMarker) covMap.removeLayer(l); });
  const maxS = Math.max(1, ...regions.map((x) => x.searches));
  regions.forEach((x) => {
    const lvl = x.searches ? x.level : "none";
    L.circleMarker([x.lat, x.lon], { radius: 5 + 18 * Math.sqrt(x.searches / maxS), color: "#fff", weight: 1.5,
                                     fillColor: GAP_COLOR[lvl], fillOpacity: 0.85 })
      .addTo(covMap)
      .bindPopup(`<b>${esc(x.name)}</b><br>State schemes: ${x.state_schemes}<br>Searches: ${x.searches} (${Math.round(x.low_match_rate * 100)}% poorly served)<br>Gap index: <b>${x.gap_index.toFixed(2)}</b>${
        x.uncovered_groups.length ? `<br>No state scheme for: ${x.uncovered_groups.map((g) => esc(g.label)).join(", ")}` : ""}`)
      .on("click", () => showNearby(x.name));
  });
}

async function showNearby(state) {
  try {
    const near = await getJSON(`/admin/coverage/nearby?state=${encodeURIComponent(state)}&km=600`);
    $("#cov-nearby").innerHTML = `<b>Within 600 km of ${esc(state)}</b> ($geoNear on the 2dsphere index): ${
      near.map((n) => `${esc(n.name)} <span class="muted">${n.km} km · ${n.state_schemes} schemes</span>`).join(" · ")}`;
  } catch (err) { toast(err.message, true); }
}

document.addEventListener("click", (e) => {
  const a = e.target.closest("[data-near]");
  if (a) { e.preventDefault(); showNearby(a.dataset.near); }
});

// ---------------------------------------------------------------- page scroll helpers + boot
function setupAdminScroll() {
  const bar = $("#scroll-progress"), top = $("#to-top");
  const onScroll = () => {
    const max = document.documentElement.scrollHeight - innerHeight;
    bar.style.transform = `scaleX(${max > 0 ? scrollY / max : 0})`;
    top.classList.toggle("hidden", scrollY < 600);
  };
  addEventListener("scroll", onScroll, { passive: true }); onScroll();
  top.onclick = () => scrollTo({ top: 0, behavior: "smooth" });
  if (!("IntersectionObserver" in window)) return;
  const spy = new IntersectionObserver((es) => es.forEach((e) => {
    if (e.isIntersecting) document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.tab === e.target.dataset.section));
  }), { rootMargin: "-40% 0px -55% 0px" });
  document.querySelectorAll("[data-section]").forEach((e) => spy.observe(e));
}

(function bootAdmin() {
  if (!isAdmin()) { location.replace("/login?role=admin&next=/admin"); return; }  // the API enforces this too
  renderUserArea();
  $("#admin-main").classList.remove("hidden");
  $("#gq-status").onchange = loadGrievanceQueue;
  setupAdminScroll();
  loadAdmin();
  loadCoverage();
})();
