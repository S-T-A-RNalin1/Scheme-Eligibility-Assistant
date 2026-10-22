// Builds docs/Scheme_Eligibility_Assistant.pptx  (node build_deck.js)
// Numbers come from stats.json (dataset, written by build_report.py) and results.json (test/eval run).
const fs = require("fs");
const path = require("path");
const pptxgen = require("pptxgenjs");

const S = JSON.parse(fs.readFileSync(path.join(__dirname, "stats.json"), "utf8"));
const R = fs.existsSync(path.join(__dirname, "results.json"))
  ? JSON.parse(fs.readFileSync(path.join(__dirname, "results.json"), "utf8")) : {};
const IMG = (f) => path.join(__dirname, "img", f);

const THEME = {
  name: "Scheme Assistant", headFontFace: "Cambria", bodyFontFace: "Calibri",
  colors: { dk1: "13241C", lt1: "FFFFFF", dk2: "0F4C3A", lt2: "EEF5F1", accent1: "0F4C3A", accent2: "E8871E",
            accent3: "2E7D5B", accent4: "C2410C", accent5: "64748B", accent6: "94C9A9", hlink: "0F4C3A", folHlink: "2E7D5B" },
};
const H = THEME.colors; // hex for options that need hex
const pres = new pptxgen();
pres.layout = "LAYOUT_16x9";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = "Scheme Eligibility Assistant";

// ---------------------------------------------------------------- layouts
pres.defineSlideMaster({
  title: "DARK", background: { color: "F3F7F5" },
  objects: [{ placeholder: { options: { name: "title", type: "title", x: 0.7, y: 1.5, w: 8.6, h: 1.3, fontFace: "Cambria",
    fontSize: 40, bold: true, color: H.dk2, valign: "bottom" }, text: "" } },
  { placeholder: { options: { name: "body", type: "body", x: 0.7, y: 2.95, w: 8.6, h: 1.4, fontSize: 18, color: "334155",
    valign: "top" }, text: "" } }],
});
pres.defineSlideMaster({
  title: "CONTENT", background: { color: "F3F7F5" },
  objects: [{ placeholder: { options: { name: "title", type: "title", x: 0.5, y: 0.3, w: 9.0, h: 0.75, fontFace: "Cambria",
    fontSize: 30, bold: true, color: H.dk2, valign: "middle", margin: 0 }, text: "" } },
  { text: { text: "Scheme Eligibility Assistant · NoSQL project", options: { x: 0.5, y: 5.25, w: 6, h: 0.25, fontSize: 9, color: "64748B", margin: 0 } } }],
  slideNumber: { x: 9.0, y: 5.22, w: 0.5, h: 0.3, fontSize: 9, color: "64748B", align: "right" },
});

let section = "";
const add = (master, sec) => { if (sec && sec !== section) { pres.addSection({ title: sec }); section = sec; } return pres.addSlide({ masterName: master, sectionTitle: section }); };

function card(slide, x, y, w, h, title, body, n, fill = "FFFFFF") {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, fill: { color: fill }, line: { color: "D6E4DC", width: 0.75 }, rectRadius: 0.1, objectName: "card " + title });
  let tx = x + 0.2;
  if (n !== undefined) {
    slide.addShape(pres.shapes.OVAL, { x: x + 0.18, y: y + 0.2, w: 0.42, h: 0.42, fill: { color: H.accent2 }, line: { color: H.accent2 } });
    slide.addText(String(n), { x: x + 0.18, y: y + 0.2, w: 0.42, h: 0.42, fontSize: 13, bold: true, color: "FFFFFF", align: "center", valign: "middle", margin: 0, isTextBox: true });
    tx = x + 0.72;
  }
  slide.addText(title, { x: tx, y: y + 0.16, w: w - (tx - x) - 0.15, h: 0.5, fontSize: 15, bold: true, color: H.dk2, valign: "middle", margin: 0, isTextBox: true });
  if (body) slide.addText(body, { x: x + 0.2, y: y + 0.72, w: w - 0.4, h: h - 0.85, fontSize: 12, color: "334155", valign: "top", margin: 0, isTextBox: true, paraSpaceAfter: 3 });
}
function stat(slide, x, y, w, big, label) {
  slide.addText(String(big), { x, y, w, h: 0.9, fontSize: 34, bold: true, color: H.accent2, fontFace: "Cambria", margin: 0, isTextBox: true });
  slide.addText(label, { x, y: y + 0.9, w, h: 0.55, fontSize: 12, color: "334155", margin: 0, isTextBox: true, valign: "top" });
}
const bulletsOf = (items, size = 14) => items.map((t, i) => ({ text: t, options: { bullet: true, breakLine: i < items.length - 1, fontSize: size, color: "1F2937", paraSpaceAfter: 6 } }));

// ---------------------------------------------------------------- 1 title
let s = add("DARK", "Introduction");
s.addText("Scheme Eligibility Assistant", { placeholder: "title" });
s.addImage({ path: IMG("muj_logo_transparent.png"), x: 0.7, y: 0.5, w: 3.0, h: 0.572, objectName: "Manipal University Jaipur logo" });
s.addText("Explainable government-scheme eligibility and grounded Q&A, built on MongoDB\nName: ____________   Roll no: ____________   Guide: ____________", { placeholder: "body" });
s.addNotes("Introduce the project: a web app that tells a citizen which schemes they qualify for and why, and answers questions with citations.");

// ---------------------------------------------------------------- 2 problem
s = add("CONTENT", "Introduction");
s.addText("Finding the right scheme is hard", { placeholder: "title" });
s.addText(bulletsOf([
  "Eligibility rules are buried in long scheme pages: age bands, income caps, category, land, BPL, state",
  "Central and state schemes all have different shapes, and rules change over time",
  "Citizens rely on middlemen; CSC operators screen many people by hand",
  "A chatbot that guesses about someone's benefits can cause real harm",
]), { x: 0.5, y: 1.25, w: 5.2, h: 3.6, valign: "top", margin: 0, isTextBox: true });
stat(s, 6.2, 1.3, 3.3, S.schemes, "unique schemes parsed from " + S.pdfs + " myScheme PDFs");
stat(s, 6.2, 2.75, 1.6, S.central, "central");
stat(s, 7.9, 2.75, 1.6, S.state, "state / UT");
s.addText("covering " + S.states + " states and UTs (Hugging Face: shrijayan/gov_myscheme)", { x: 6.2, y: 4.3, w: 3.3, h: 0.5, fontSize: 11, italic: true, color: "64748B", margin: 0, isTextBox: true });

// ---------------------------------------------------------------- 3 objectives
s = add("CONTENT", "Introduction");
s.addText("Objectives", { placeholder: "title" });
[["Eligibility checker", "Profile → Eligible / Ineligible / Needs more info for every scheme, with a reason per rule"],
 ["Grounded Q&A", "Answers only from retrieved scheme text, cites sources, refuses when unsure"],
 ["Trustworthy records", "Versioned rules, append-only checksummed audit log, replayable decisions"],
 ["NoSQL depth", "Validation, CRUD, aggregation, indexes, transactions, TTL, text + vector search"]]
  .forEach(([t, b], i) => card(s, 0.5 + (i % 2) * 4.6, 1.25 + Math.floor(i / 2) * 1.95, 4.4, 1.75, t, b, i + 1));
s.addNotes("Core design principle: the language model never decides eligibility. Code decides facts; text generation only explains them.");

// ---------------------------------------------------------------- 4 why mongodb
s = add("CONTENT", "Database choice");
s.addText("Why MongoDB over a relational database", { placeholder: "title" });
const rows = [
  ["Need", "Relational", "MongoDB"],
  ["Variable-shaped schemes", "Sparse columns / EAV", "Flexible documents + JSON Schema"],
  ["Recursive rule tree", "Adjacency list + recursive CTE", "Nested sub-document, one read"],
  ["Audit with exact inputs", "Joins to versioned tables", "Embedded snapshots, no joins"],
  ["Text + vector search", "Extensions", "Text index + vector search beside data"],
  ["Atomic rule publish", "Transactions", "Multi-document transactions"],
];
s.addTable(rows.map((r, i) => r.map((c) => ({ text: c, options: { bold: i === 0, color: i === 0 ? "FFFFFF" : "1F2937", fill: { color: i === 0 ? H.dk2 : (i % 2 ? "FFFFFF" : H.lt2) }, fontSize: 12 } }))),
  { x: 0.5, y: 1.25, w: 9.0, colW: [2.8, 2.9, 3.3], border: { type: "solid", pt: 0.5, color: "D1D5DB" }, rowH: 0.5 });
s.addText("Trade-off accepted: no foreign keys, so we enforce unique indexes, validators and insert-only versions instead.", { x: 0.5, y: 4.45, w: 9, h: 0.5, fontSize: 12, italic: true, color: H.accent3, margin: 0, isTextBox: true });

// ---------------------------------------------------------------- 5 architecture
s = add("CONTENT", "Design");
s.addText("Architecture: three subsystems, one database", { placeholder: "title" });
s.addImage({ path: IMG("architecture.png"), x: 1.15, y: 1.1, w: 7.7, h: 4.07, objectName: "architecture diagram" });
s.addNotes("Web UI talks only to FastAPI. The RAG service hands eligibility questions to the rules engine. Ingestion publishes rules only after validation and human review.");

// ---------------------------------------------------------------- 6 data model
s = add("CONTENT", "Design");
s.addText("Data model: embed, reference, snapshot", { placeholder: "title" });
s.addImage({ path: IMG("data_model.png"), x: 0.4, y: 1.15, w: 6.0, h: 3.3, objectName: "data model diagram" });
s.addText(bulletsOf([
  "Embed what is read together: scheme + its rule tree",
  "Reference what changes on its own: chunks and versions by slug",
  "Snapshot what must never change: each evaluation stores the rules and profile it used",
  "12 collections, unique / compound / text / TTL indexes",
], 13), { x: 6.6, y: 1.2, w: 3.0, h: 3.8, valign: "top", margin: 0, isTextBox: true });

// ---------------------------------------------------------------- 7 scheme doc
s = add("CONTENT", "Design");
s.addText("A scheme is one document", { placeholder: "title" });
s.addText('{ "slug": "apy", "name": "Atal Pension Yojana",\n  "level": "central", "status": "published",\n  "current_version": 1,\n  "eligibility": { "op": "AND", "children": [\n    { "id": "r1", "attribute": "age",\n      "operator": "between", "value": [18, 40],\n      "source_quote": "The minimum age of joining\n        APY is 18 years and maximum is 40 years." },\n    { "op": "NOT", "children": [\n      { "id": "r2",\n        "attribute": "is_income_tax_payer",\n        "operator": "==", "value": true } ] } ] } }',
  { x: 0.5, y: 1.2, w: 4.9, h: 3.9, fontFace: "Courier New", fontSize: 10.5, color: "1F2937", fill: { color: "F3F4F6" }, margin: 0.15, valign: "top", isTextBox: true });
s.addImage({ path: IMG("rule_tree.png"), x: 5.6, y: 1.4, w: 3.95, h: 1.82, objectName: "rule tree diagram" });
s.addText("Groups AND / OR / NOT nest to any depth. Every leaf keeps the sentence it came from, and the validator checks it is really in the source text.", { x: 5.6, y: 3.45, w: 3.95, h: 1.4, fontSize: 12.5, color: "334155", margin: 0, isTextBox: true, valign: "top" });

// ---------------------------------------------------------------- 8 CRUD
s = add("CONTENT", "Implementation");
s.addText("CRUD across the collections", { placeholder: "title" });
[["Create", "register user · insert_many evaluations per run · insert version (in a transaction) · file a grievance with an atomic ticket number"],
 ["Read", "filter / text-search / paginate schemes · detail by slug · run results · user history (index-ordered)"],
 ["Update", "save profile ($set, upsert) · publish: repoint scheme to new version · grievance reply ($push to timeline)"],
 ["Delete", "delete my profile + history (privacy) · retire a scheme (soft delete keeps history)"]]
  .forEach(([t, b], i) => card(s, 0.5 + (i % 2) * 4.6, 1.25 + Math.floor(i / 2) * 1.95, 4.4, 1.75, t, b, ["C", "R", "U", "D"][i]));

// ---------------------------------------------------------------- 9 advanced
s = add("CONTENT", "Implementation");
s.addText("Advanced MongoDB features", { placeholder: "title" });
[["JSON Schema validators", "Database rejects bad verdicts, operators, ages"],
 ["Transactions", "Insert version N+1 + repoint scheme atomically"],
 ["Aggregation", "Verdict mix, most-missing answers, schemes per state"],
 ["Index tuning", "ESR compound indexes, checked with explain()"],
 ["TTL indexes", "Chat logs and rate-limit counters expire themselves"],
 ["Text + vector search", "$text + embeddings merged with RRF; $vectorSearch on Atlas"]]
  .forEach(([t, b], i) => card(s, 0.5 + (i % 3) * 3.05, 1.25 + Math.floor(i / 3) * 1.95, 2.85, 1.75, t, b));
const bench = R.bench || [];
if (bench.length) s.addNotes(bench.map((b) => `${b.query}: ${b.no_index.docs_examined} → ${b.with_index.docs_examined} docs examined`).join("\n"));

// ---------------------------------------------------------------- 10 engine
s = add("CONTENT", "Rules engine");
s.addText("Three-valued rules engine", { placeholder: "title" });
const tt = [["AND", "PASS", "FAIL", "UNKNOWN"], ["PASS", "PASS", "FAIL", "UNKNOWN"], ["FAIL", "FAIL", "FAIL", "FAIL"], ["UNKNOWN", "UNKNOWN", "FAIL", "UNKNOWN"]];
const tcol = { PASS: "2E7D5B", FAIL: "C2410C", UNKNOWN: "B45309", AND: "FFFFFF" };
s.addTable(tt.map((r, i) => r.map((c, j) => ({ text: c, options: { bold: i === 0 || j === 0, align: "center", fontSize: 13,
  color: i === 0 && j === 0 ? "FFFFFF" : (i === 0 || j === 0 ? "FFFFFF" : tcol[c]), fill: { color: i === 0 || j === 0 ? H.dk2 : (i % 2 ? "FFFFFF" : H.lt2) } } }))),
  { x: 0.5, y: 1.3, w: 4.4, colW: [1.1, 1.1, 1.1, 1.1], rowH: 0.55, border: { type: "solid", pt: 0.5, color: "D1D5DB" } });
s.addText(bulletsOf([
  "Missing answer = UNKNOWN, never FAIL → \"Needs more info\"",
  "One FAIL in an AND decides the verdict; irrelevant questions are dropped",
  "Every rule returns a reason, not just true/false",
  "Next-best question: the missing answer that unlocks the most verdicts",
  "Pure function: no database calls, so it is easy to test",
], 13), { x: 5.2, y: 1.25, w: 4.3, h: 3.8, valign: "top", margin: 0, isTextBox: true });

// ---------------------------------------------------------------- 11 ingestion
s = add("CONTENT", "Rules engine");
s.addText("From scheme text to published rules", { placeholder: "title" });
["Parse PDF", "Extract rules", "Validate", "Human review", "Publish (txn)"].forEach((t, i) => {
  const x = 0.5 + i * 1.86;
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 1.3, w: 1.6, h: 0.8, fill: { color: i === 3 ? H.accent2 : H.dk2 }, line: { color: i === 3 ? H.accent2 : H.dk2 }, rectRadius: 0.08 });
  s.addText(t, { x, y: 1.3, w: 1.6, h: 0.8, fontSize: 13, bold: true, color: "FFFFFF", align: "center", valign: "middle", margin: 0, isTextBox: true });
  if (i < 4) s.addShape(pres.shapes.RIGHT_TRIANGLE, { x: x + 1.64, y: 1.58, w: 0.18, h: 0.24, rotate: 90, fill: { color: "94A3B8" }, line: { color: "94A3B8" } });
});
stat(s, 0.5, 2.55, 2.8, S.leaves, "rule leaves proposed with a source quote each");
stat(s, 3.6, 2.55, 2.8, S.valid + " / " + S.schemes, "proposals pass automatic validation");
stat(s, 6.7, 2.55, 2.8, S.curated, "hand-reviewed schemes published for the demo");
s.addText("Validator checks: registered attributes only · operator matches type · quote really appears in the source · numbers appear in the quote · no contradictory ranges. Anything it cannot express goes into unmapped_conditions, which reviewers and users see.", { x: 0.5, y: 4.15, w: 9, h: 0.85, fontSize: 12, color: "334155", margin: 0, isTextBox: true });

// ---------------------------------------------------------------- 12 RAG
s = add("CONTENT", "Grounded Q&A");
s.addText("Grounded Q&A that refuses to guess", { placeholder: "title" });
[["Route the question", "Eligibility → rules engine; discovery → retrieve then check; info → retrieval; off-topic → refuse"],
 ["Hybrid retrieval", "Section chunks; vector similarity + MongoDB text search, merged with Reciprocal Rank Fusion"],
 ["Grounded answer", "Answer only from numbered sources, cite [n], code checks every citation; no citation → refusal line"]]
  .forEach(([t, b], i) => card(s, 0.5 + i * 3.05, 1.3, 2.85, 2.4, t, b, i + 1));
s.addText("The model only explains; verdicts always come from the engine.", { x: 0.5, y: 4.1, w: 9, h: 0.5, fontSize: 16, italic: true, bold: true, color: H.accent3, margin: 0, isTextBox: true });

// ---------------------------------------------------------------- 12b fixing wrong answers
s = add("CONTENT", "Grounded Q&A");
s.addText("Fixing wrong answers we found in testing", { placeholder: "title" });
const fx = [["Question", "Before", "After"],
  ["car loan", "Text about education loans", "\u201cNo scheme about car loan\u201d + related loan schemes"],
  ["atal yojna", "Refused as off-topic", "List of Atal schemes with sources"],
  ["aadhar card", "Refused as off-topic", "Document lists that mention Aadhaar"],
  ["How do I apply for \u2026?", "An eligibility verdict", "The application steps"]];
s.addTable(fx.map((r, i) => r.map((c, j) => ({ text: c, options: { bold: i === 0 || j === 0, fontSize: 12,
  color: i === 0 ? "FFFFFF" : j === 1 ? "C2410C" : j === 2 ? "2E7D5B" : "1F2937",
  fill: { color: i === 0 ? H.dk2 : (i % 2 ? "FFFFFF" : H.lt2) } } }))),
  { x: 0.5, y: 1.2, w: 5.6, colW: [1.6, 1.8, 2.2], rowH: 0.5, border: { type: "solid", pt: 0.5, color: "D1D5DB" } });
s.addText(bulletsOf([
  "Each passage must contain the question's topic words (not just one of them somewhere in the results)",
  "Spelling map + plural matching: yojna \u2192 yojana, aadhar \u2192 aadhaar, fishermen \u2192 fisherman",
  "A question matching a scheme name is never treated as off-topic",
  "Amounts like \u201cRs 10.00 lakh\u201d are no longer split in half",
], 12.5), { x: 6.35, y: 1.2, w: 3.2, h: 3.9, valign: "top", margin: 0, isTextBox: true });

// ---------------------------------------------------------------- 12c grievance portal
s = add("CONTENT", "Grievance portal");
s.addText("Grievance Portal: file, track, resolve", { placeholder: "title" });
s.addImage({ path: IMG("screen_6_grievance_portal.png"), x: 0.5, y: 1.15, w: 5.2, h: 3.29, objectName: "grievance portal screen" });
s.addText("Citizen files a complaint linked to a scheme (and optionally a past check), gets a ticket number (GRV-2026-…), follows the timeline and can reopen it.",
  { x: 0.5, y: 4.5, w: 5.2, h: 0.65, fontSize: 11, color: "334155", margin: 0, isTextBox: true });
[["Atomic ticket no.", "find_one_and_update + $inc on a counter, so numbers never repeat"],
 ["Embedded timeline", "Every reply is $push-ed into the complaint and read in one fetch"],
 ["$lookup + $facet", "Officer queue shows the filer's email; one query gives all dashboard counts"]]
  .forEach(([t, b], i) => card(s, 5.95, 1.15 + i * 1.33, 3.55, 1.2, t, b));

// ---------------------------------------------------------------- 13 security & testing
s = add("CONTENT", "Quality");
s.addText("Security, validation and testing", { placeholder: "title" });
card(s, 0.5, 1.25, 4.4, 3.75, "Security", "• PBKDF2-SHA256 password hashes, JWT bearer tokens\n• Roles: anonymous / user / admin (403 on admin routes)\n• Grievances visible only to the filer and admins\n• Consent before saving a profile; delete-my-data endpoint\n• No Aadhaar or ID numbers stored\n• Rate limit on chat via TTL counters\n• Audit records insert-only with SHA-256 checksum");
const T = R.tests;
card(s, 5.1, 1.25, 4.4, 3.75, "Testing", "• Truth tables for AND / OR / NOT\n• Property tests (Hypothesis): NOT(NOT(x)) = x\n• Fixture profiles → expected verdicts per scheme\n• Validator rejects invented or malformed rules\n• API tests for CRUD, auth, replay and the full grievance flow" + (T ? `\n\nLast run: ${T.passed} passed, ${T.failed} failed` : ""));

// ---------------------------------------------------------------- 14 results
s = add("CONTENT", "Results");
s.addText("Results", { placeholder: "title" });
const ev = R.rag_eval;
stat(s, 0.5, 1.3, 2.1, (R.fixture_accuracy || "—").split(" ")[0], "fixture verdict accuracy " + ((R.fixture_accuracy || "").split(" ")[1] || ""));
stat(s, 2.8, 1.3, 2.1, R.check_ms ? R.check_ms : "<1 s", "median to check all published schemes + write audit");
stat(s, 5.1, 1.3, 2.1, R.chunks || "—", "text chunks indexed for retrieval");
stat(s, 7.4, 1.3, 2.1, ev ? ev.headline["recall@5"].toFixed(2) : "—", "hybrid retrieval Recall@5");
if (ev) {
  const cfg = Object.entries(ev.configs);
  s.addChart(pres.charts.BAR, [{ name: "Recall@5", labels: cfg.map((c) => c[0]), values: cfg.map((c) => c[1]["recall@5"]) }], {
    x: 0.5, y: 3.0, w: 9, h: 2.1, barDir: "bar", showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "0.00",
    chartColors: [H.accent2], showLegend: false, valAxisMaxVal: 1, valAxisMinVal: 0, catAxisLabelFrequency: 1, catAxisLabelFontSize: 9, catAxisLabelColor: "334155", valAxisLabelColor: "64748B",
    valGridLine: { color: "E5E7EB", size: 0.5 }, catGridLine: { style: "none" }, showTitle: true, title: "Retrieval Recall@5 (" + ev.n + " questions; refusal on unanswerable " + ev.refusal + ")",
    titleFontSize: 12, titleColor: "334155", catAxisLabelFontFace: "+mn-lt", valAxisLabelFontFace: "+mn-lt", dataLabelFontFace: "+mn-lt", titleFontFace: "+mn-lt", dataLabelFontSize: 10,
  });
}

// ---------------------------------------------------------------- 14b screens
s = add("CONTENT", "Results");
s.addText("The working application", { placeholder: "title" });
s.addImage({ path: IMG("screen_3_eligibility_results.png"), x: 0.5, y: 1.2, w: 4.4, h: 2.78, objectName: "eligibility screen" });
s.addImage({ path: IMG("screen_4_grounded_answers.png"), x: 5.1, y: 1.2, w: 4.4, h: 2.78, objectName: "chat screen" });
s.addText("Eligibility check: verdict, reason for every rule, next best question", { x: 0.5, y: 4.2, w: 4.4, h: 0.6, fontSize: 12, color: "334155", margin: 0, isTextBox: true });
s.addText("Grounded answers: engine verdict + cited sources as clickable chips", { x: 5.1, y: 4.2, w: 4.4, h: 0.6, fontSize: 12, color: "334155", margin: 0, isTextBox: true });

s = add("CONTENT", "Results");
s.addText("Officer view: grievances and audit replay", { placeholder: "title" });
s.addImage({ path: IMG("screen_7_grievance_queue_admin.png"), x: 0.5, y: 1.2, w: 4.4, h: 2.78, objectName: "grievance queue screen" });
s.addImage({ path: IMG("screen_8_admin_stats_and_replay.png"), x: 5.1, y: 1.2, w: 4.4, h: 2.78, objectName: "admin stats screen" });
s.addText("Grievance queue: officer sets status and priority and replies; the citizen sees it in the timeline", { x: 0.5, y: 4.1, w: 4.4, h: 0.7, fontSize: 12, color: "334155", margin: 0, isTextBox: true });
s.addText("Dashboard from aggregation pipelines; Replay re-checks a stored decision and its checksum", { x: 5.1, y: 4.1, w: 4.4, h: 0.7, fontSize: 12, color: "334155", margin: 0, isTextBox: true });

s = add("CONTENT", "Results");
s.addText("Indexes: documents examined per query", { placeholder: "title" });
if (bench.length) {
  s.addChart(pres.charts.BAR, [
    { name: "Collection scan", labels: bench.map((b) => b.query), values: bench.map((b) => b.no_index.docs_examined) },
    { name: "With index", labels: bench.map((b) => b.query), values: bench.map((b) => b.with_index.docs_examined) }], {
    x: 0.5, y: 1.15, w: 9, h: 3.9, barDir: "bar", barGrouping: "clustered", showValue: true, dataLabelPosition: "outEnd",
    chartColors: ["94A3B8", H.accent1], showLegend: true, legendPos: "b", legendFontSize: 11, legendFontFace: "+mn-lt",
    catAxisLabelColor: "334155", valAxisLabelColor: "64748B", catAxisLabelFontSize: 11, valAxisLabelFontSize: 10,
    valGridLine: { color: "E5E7EB", size: 0.5 }, catGridLine: { style: "none" }, dataLabelFontSize: 10,
    catAxisLabelFontFace: "+mn-lt", valAxisLabelFontFace: "+mn-lt", dataLabelFontFace: "+mn-lt",
  });
  s.addNotes("Measured with explain('executionStats'); collection scan forced with hint({$natural: 1}). Every indexed plan is FETCH <- IXSCAN.");
}

// ---------------------------------------------------------------- 15 demo
s = add("CONTENT", "Results");
s.addText("Live demonstration", { placeholder: "title" });
[["Check", "Enter a profile → three groups with reasons → answer the suggested question"],
 ["Explore", "Scheme page: rule tree, source quotes, versions, last verified"],
 ["Ask", "Streamed answer with source chips; off-topic question is refused"],
 ["Grievance", "File a complaint, get a ticket; officer resolves it; citizen sees the reply"],
 ["Admin", "Approve a proposal → new version in a transaction; replay an evaluation"],
 ["Mongo shell + tests", "Validator rejects bad insert; indexes, explain(); pytest runs green"]]
  .forEach(([t, b], i) => card(s, 0.5 + (i % 3) * 3.05, 1.25 + Math.floor(i / 3) * 1.95, 2.85, 1.75, t, b, i + 1));

// ---------------------------------------------------------------- 16 conclusion
s = add("DARK", "Conclusion");
s.addText("Conclusion and next steps", { placeholder: "title" });
s.addText("MongoDB's document model fits rule-heavy, variable government data: one document per scheme, immutable versions, self-contained audit records.\nNext: ingest from the official API Setu feed, move to Atlas Vector Search, add a Hindi UI and a faithfulness evaluation set.", { placeholder: "body" });

pres.writeFile({ fileName: path.join(__dirname, "Scheme_Eligibility_Assistant_v4.pptx") }).then(async (f) => {
  try {
    const { applyTheme } = require(process.env.PPTX_SKILL + "/scripts/apply_theme.js");
    await applyTheme(f, THEME);
  } catch (e) { console.log("theme step skipped:", e.message); }
  console.log("wrote", f);
});
