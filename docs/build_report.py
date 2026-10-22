"""Generate the project report (docs/Scheme_Eligibility_Assistant_Report.docx).

Dataset and extraction numbers are computed live from the project; test /
benchmark / evaluation numbers are read from docs/results.json, which
scripts/collect_results.py writes after a real run.
"""
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).absolute().parent.parent
sys.path.insert(0, str(ROOT))
from api.engine.validate import leaves, validate_tree  # noqa: E402
from api.ingest.extract import propose  # noqa: E402

IMG = ROOT / "docs" / "img"
OUT = ROOT / "docs" / "Scheme_Eligibility_Assistant_Report_v3.docx"
ACCENT = RGBColor(0x1F, 0x3A, 0x8A)

# ---------------------------------------------------------------- live numbers
schemes = json.loads((ROOT / "data" / "schemes_parsed.json").read_text(encoding="utf-8"))
curated = json.loads((ROOT / "data" / "curated_rules.json").read_text(encoding="utf-8"))["schemes"]
n_pdfs = len(list((ROOT / "data" / "raw_pdfs").glob("*.pdf")))
levels = Counter(s["level"] for s in schemes)
n_states = len({s["state"] for s in schemes if s["state"]})
valid, attr_counts, leaf_total = 0, Counter(), 0
for s in schemes:
    p = propose(s)
    ls = leaves(p["eligibility"])
    leaf_total += len(ls)
    attr_counts.update(l["attribute"] for l in ls)
    if not validate_tree(p["eligibility"], " ".join(s["sections"].values())):
        valid += 1
results_path = ROOT / "docs" / "results.json"
R = json.loads(results_path.read_text(encoding="utf-8")) if results_path.exists() else {}


# ---------------------------------------------------------------- helpers
doc = Document()
sec = doc.sections[0]
sec.page_height, sec.page_width = Cm(29.7), Cm(21.0)
for side in ("left_margin", "right_margin"):
    setattr(sec, side, Cm(2.3))
sec.top_margin = sec.bottom_margin = Cm(2.2)

styles = doc.styles
styles["Normal"].font.name = "Calibri"
styles["Normal"].font.size = Pt(11)
styles["Normal"].paragraph_format.space_after = Pt(6)
styles["Normal"].paragraph_format.line_spacing = 1.15
for lvl, size in ((1, 16), (2, 13), (3, 11.5)):
    st = styles[f"Heading {lvl}"]
    st.font.name = "Calibri"
    st.font.size = Pt(size)
    st.font.color.rgb = ACCENT
    st.font.bold = True
    st.paragraph_format.space_before = Pt(14 if lvl == 1 else 10)
    st.paragraph_format.space_after = Pt(6)


def para(text="", bold=False, italic=False, size=None, align=None, color=None):
    p = doc.add_paragraph()
    _runs(p, text, bold, italic, size, color)
    if align:
        p.alignment = align
    return p


def _runs(p, text, bold=False, italic=False, size=None, color=None):
    # **bold** spans inside text
    parts = text.split("**")
    for i, part in enumerate(parts):
        if not part:
            continue
        r = p.add_run(part)
        r.bold = bold or (i % 2 == 1)
        r.italic = italic
        if size:
            r.font.size = Pt(size)
        if color:
            r.font.color.rgb = color


def bullets(items, style="List Bullet"):
    for it in items:
        p = doc.add_paragraph(style=style)
        _runs(p, it)
        p.paragraph_format.space_after = Pt(3)


def code(text):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.4)
    p.paragraph_format.space_after = Pt(8)
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), "F3F4F6")
    p._p.get_or_add_pPr().append(shd)
    r = p.add_run(text)
    r.font.name = "Consolas"
    r._element.rPr.rFonts.set(qn("w:eastAsia"), "Consolas")
    r.font.size = Pt(8.5)


def shade(cell, fill):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), fill)
    tcPr.append(shd)


def table(header, rows, widths=None, size=9.5):
    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(header):
        c = t.rows[0].cells[i]
        c.text = ""
        r = c.paragraphs[0].add_run(h)
        r.bold, r.font.size = True, Pt(size)
        r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        shade(c, "1F3A8A")
    for ri, row in enumerate(rows):
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""
            _runs(cells[i].paragraphs[0], str(v), size=size)
            if ri % 2:
                shade(cells[i], "EEF2FF")
    if widths:
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Cm(w)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t


def figure(path, caption, width=16):
    if Path(path).exists():
        doc.add_picture(str(path), width=Cm(width))
        doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
        para(caption, italic=True, size=9, align=WD_ALIGN_PARAGRAPH.CENTER, color=RGBColor(0x55, 0x55, 0x55))


def page_break():
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


def r(key, default="—"):
    cur = R
    for k in key.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


# ---------------------------------------------------------------- title page
GREY = RGBColor(0x6B, 0x72, 0x80)
CENTER = WD_ALIGN_PARAGRAPH.CENTER


def running_text(container, text):
    p = container.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT if container is sec.header else CENTER
    r = p.add_run(text)
    r.font.size, r.font.color.rgb = Pt(8), GREY


running_text(sec.header, "Scheme Eligibility Assistant — Explainable Eligibility & Grounded Q&A | Technical Documentation")
running_text(sec.footer, "Scheme Eligibility Assistant Project Report — MongoDB Architecture & Rules Engine")


def tp(text, size=11, bold=False, color=None, space=6, underline=False):
    p = para(text, bold=bold, size=size, align=CENTER, color=color)
    p.paragraph_format.space_after = Pt(space)
    if underline:
        for run in p.runs:
            run.underline = True
    return p


tp("A NoSQL Report on", size=11, underline=True, space=10)
tp("Scheme Eligibility Assistant: Explainable Government-Scheme Eligibility & Grounded Q&A on MongoDB",
   size=20, bold=True, color=ACCENT, space=14)
tp("Submitted to Manipal University Jaipur", size=11, space=4)
tp("Towards the partial fulfillment for the Award of the Degree of", size=11, space=10)
tp("B. Tech Computer Science and Engineering (Artificial Intelligence and Machine Learning)", size=13, bold=True,
   color=ACCENT, space=8)
tp("In Computer Science and Engineering (AIML)", size=11, space=4)
tp("2024-2028", size=11, space=10)
tp("By", size=11, underline=True, space=6)
tp("Student Name (Registration No.)  |  Student Name (Registration No.)", size=11, space=4)
tp("Student Name (Registration No.)  |  Student Name (Registration No.)", size=11, space=16)
doc.add_picture(str(IMG / "muj_logo_transparent.png"), width=Cm(9.5))
doc.paragraphs[-1].alignment = CENTER
doc.paragraphs[-1].paragraph_format.space_after = Pt(22)
tp("Under the guidance of", size=11, space=4)
tp("Guide Name", size=11, bold=True, space=16)
tp("Department of Artificial Intelligence and Machine Learning", size=15, bold=True, color=ACCENT, space=8)
tp("Manipal University Jaipur", size=15, bold=True, color=ACCENT, space=8)
tp("Jaipur, Rajasthan", size=15, bold=True, color=ACCENT, space=0)
page_break()

# ---------------------------------------------------------------- abstract + contents
doc.add_heading("Abstract", 1)
para(f"India runs thousands of central and state welfare schemes, but citizens and the field officers who help them "
     f"struggle to find out which schemes a person qualifies for. Eligibility rules are buried in long scheme pages, they "
     f"differ in shape from scheme to scheme, and they change over time. This project builds the **Scheme Eligibility "
     f"Assistant**, a web application with two modes: (1) an **eligibility checker** in which a deterministic, versioned "
     f"rules engine evaluates a short user profile against every published scheme and returns Eligible, Ineligible or "
     f"Needs-more-info with the exact reason for each rule; and (2) a **grounded Q&A assistant** that answers free-form "
     f"questions only from retrieved official scheme text, with citations, and refuses rather than guessing.")
para(f"MongoDB is the only database. Each scheme is a single document holding a nested eligibility rule tree; rule "
     f"changes create immutable version documents inside multi-document transactions; every eligibility check is stored "
     f"as a self-contained audit document that embeds snapshots of the rules and profile it used, with a SHA-256 checksum "
     f"for tamper-evidence. Retrieval combines vector similarity over stored embeddings with MongoDB full-text search, "
     f"merged by Reciprocal Rank Fusion. The data comes from the public Hugging Face dataset shrijayan/gov_myscheme: "
     f"{n_pdfs} myScheme PDFs, parsed into {len(schemes)} unique schemes ({levels['central']} central, {levels['state']} state, "
     f"covering {n_states} states/UTs). The core design principle is that **the language model never decides "
     f"eligibility**: code decides facts, and text generation only explains them.")
para("Keywords: MongoDB, document model, JSON Schema validation, aggregation pipeline, transactions, TTL index, "
     "text search, vector search, rules engine, three-valued logic, retrieval-augmented generation.", italic=True, size=10)

doc.add_heading("Contents", 1)
for line in ["1. Problem identification and real-world relevance", "2. Objectives and scope",
             "3. NoSQL database selection and justification", "4. System architecture",
             "5. Database design and data modelling", "6. CRUD implementation",
             "7. Advanced NoSQL features and query optimisation", "8. Rules engine design",
             "9. Grounded retrieval-augmented Q&A", "10. Application integration and functionality",
             "11. Testing, security and data validation", "12. Results", "13. Limitations and future work",
             "14. Conclusion", "References", "Appendix A — Setup and run instructions",
             "Appendix B — Demonstration / viva script"]:
    para(line).paragraph_format.space_after = Pt(1)
page_break()

# ---------------------------------------------------------------- 1. Problem
doc.add_heading("1. Problem identification and real-world relevance", 1)
doc.add_heading("1.1 Problem statement", 2)
para("A citizen who wants to know \"which government schemes can I get?\" today has to read dense portal pages, "
     "interpret legal eligibility text (age bands, income ceilings, social category, land holding, BPL status, state "
     "of residence) and repeat this for hundreds of schemes. Many rely on middlemen. Field-level civil servants — block "
     "officers and Common Service Centre (CSC) operators — face the same problem at scale. General-purpose chatbots are "
     "not a safe answer: a confidently wrong statement about someone's benefits is genuinely harmful.")
doc.add_heading("1.2 Who it serves", 2)
bullets(["**Citizens** looking for benefits they are entitled to, without sharing identity documents.",
         "**CSC operators and block officers** who screen many applicants and need explainable answers.",
         "**Scheme administrators** who must publish rule changes safely and audit past decisions."])
doc.add_heading("1.3 Why it matters", 2)
bullets(["Under-utilisation of welfare schemes is common because eligible people do not know they qualify.",
         "Eligibility decisions must be **explainable** (which rule passed or failed) and **reproducible** (what were the "
         "rules on the day the person checked).",
         "Rules change; showing when data was last verified, and versioning rules instead of overwriting them, are real "
         "governance concerns rather than nice-to-haves."])

# ---------------------------------------------------------------- 2. Objectives
doc.add_heading("2. Objectives and scope", 1)
doc.add_heading("2.1 Objectives", 2)
bullets(["Model heterogeneous scheme data (central and state schemes have different shapes) in a document database.",
         "Encode eligibility as **data** (a rule tree), not code, so hundreds of schemes can be evaluated by one interpreter.",
         "Return **three-valued** verdicts — Eligible / Ineligible / Needs more info — with a reason for every rule and the "
         "single most useful next question to ask.",
         "Keep an **append-only, tamper-evident audit log** of every check, replayable from its own snapshots.",
         "Version rules immutably and publish new versions atomically using **multi-document transactions**.",
         "Answer free-form questions only from retrieved scheme text with **citations** and a hard refusal fallback.",
         "Demonstrate full CRUD, indexing and query optimisation, aggregation, validation, TTL, text and vector search, "
         "authentication, role-based access and automated tests."])
doc.add_heading("2.2 Scope", 2)
table(["In scope", "Out of scope (future work)"], [
    [f"{len(schemes)} schemes from the Hugging Face myScheme dataset; {len(curated)} with hand-reviewed rule trees",
     "Live sync with the official API Setu / myScheme APIs"],
    ["Profile wizard, results, scheme browser, Q&A, admin review queue", "Applying for a scheme on the user's behalf"],
    ["English text; multilingual embeddings are a drop-in replacement", "Full Hindi / regional-language UI"],
    ["Local MongoDB replica set; Atlas-ready code paths", "Production cloud deployment and monitoring"],
], widths=[8.2, 8.2])
para("Disclaimer: this is an academic project on public data, not an official service. Every scheme links to its "
     "official myScheme page and users are asked to verify there.", italic=True, size=10)

# ---------------------------------------------------------------- 3. NoSQL selection
doc.add_heading("3. NoSQL database selection and justification", 1)
doc.add_heading("3.1 Why a document database", 2)
para("The central entity — a scheme — is naturally one nested object: descriptive sections, a list of benefits, a "
     "list of required documents and, most importantly, an eligibility tree of arbitrary depth (A AND (B OR C) AND NOT D). "
     "Central and state schemes do not share a fixed set of columns. In a relational design this would be split into "
     "schemes, criteria, criteria-groups, benefits and documents tables and reassembled with joins on every request; "
     "the recursive rule tree needs either an adjacency-list table with recursive CTEs or a JSON column anyway.")
table(["Requirement", "Relational (e.g. PostgreSQL)", "MongoDB (chosen)"], [
    ["Variable-shaped scheme records", "Sparse columns or EAV tables", "Flexible documents, validated by JSON Schema"],
    ["Recursive eligibility tree", "Adjacency list + recursive CTE, or JSONB", "Native nested sub-document, read in one fetch"],
    ["Load scheme + rules for evaluation", "Several joins", "Single document read, no joins"],
    ["Immutable audit with exact inputs", "Join back to versioned tables (must never change)", "Embedded snapshots — self-contained record"],
    ["Hybrid search (text + vectors)", "Extensions (pg_trgm, pgvector)", "Text index + vector search beside the data"],
    ["Atomic rule publish", "Transactions", "Multi-document ACID transactions (replica set)"],
    ["Horizontal scale for audit log", "Partitioning / read replicas", "Sharding on run/user keys; replica sets"],
], widths=[4.6, 5.6, 6.2], size=9)
doc.add_heading("3.2 Why MongoDB specifically", 2)
bullets(["**Document model + JSON Schema validators**: we keep flexibility but the server itself rejects malformed rule "
         "operators, invalid verdicts, negative ages or missing checksums.",
         "**Aggregation framework** for analytics (verdict distribution, most-missing attributes, schemes per state) "
         "computed inside the database.",
         "**Multi-document transactions** (available on replica sets) make 'insert version N + repoint the scheme' atomic.",
         "**TTL indexes** expire chat logs and rate-limit counters automatically — data minimisation by design.",
         "**Text indexes** for keyword retrieval and **Atlas Vector Search** ($vectorSearch) for semantic retrieval; the "
         "code detects Atlas and otherwise uses an in-process cosine index over embeddings stored in MongoDB.",
         "Mature Python driver (PyMongo) that fits a FastAPI backend."])
doc.add_heading("3.3 Trade-off accepted", 2)
para("MongoDB has no foreign keys. We replace them with application-level invariants: unique indexes (slug, "
     "scheme_slug+version, email, user_id on profiles), JSON Schema validators on collections, Pydantic validation at the "
     "API boundary, a publish-time rule validator, and the rule that published versions and evaluations are never "
     "updated — only inserted.")

# ---------------------------------------------------------------- 4. Architecture
doc.add_heading("4. System architecture", 1)
para("Three subsystems share one MongoDB deployment: an offline ingestion pipeline, a deterministic rules engine and a "
     "retrieval-augmented Q&A service that hands eligibility questions to the engine. The web client talks only to the "
     "FastAPI backend.")
figure(IMG / "architecture.png", "Figure 1 — System architecture")
table(["Layer", "Technology", "Reason"], [
    ["Frontend", "Single-page HTML + vanilla JS (served by FastAPI)", "No build step; works offline for the demo; SSE streaming"],
    ["Backend API", "Python 3.12, FastAPI, Pydantic v2, Uvicorn", "Typed endpoints, automatic OpenAPI docs at /docs"],
    ["Database", "MongoDB 8.3, single-node replica set rs0", "Transactions need a replica set; same code runs on Atlas"],
    ["Driver", "PyMongo 4", "Official driver; sessions/transactions; aggregation"],
    ["Embeddings", "TF-IDF → TruncatedSVD (LSA), 256-d, L2-normalised", "Fully offline; swappable for a bge-m3-style model"],
    ["LLM (optional)", "Claude via Anthropic SDK", "Only narrates retrieved text; extractive fallback when no API key"],
    ["Auth", "JWT (HS256) + PBKDF2-SHA256 password hashes", "Stateless sessions; user/admin roles"],
    ["Testing", "pytest, Hypothesis, FastAPI TestClient", "Truth tables, property tests, fixtures, API tests"],
], widths=[3.0, 6.4, 7.0], size=9)

# ---------------------------------------------------------------- 5. Data model
doc.add_heading("5. Database design and data modelling", 1)
para("Guiding rule: **embed what is read together, reference what changes independently, snapshot what must never "
     "change.** The database has ten collections.")
figure(IMG / "data_model.png", "Figure 2 — Collections and relationships")
table(["Collection", "Holds", "Pattern", "Key indexes"], [
    ["schemes", "One live scheme with sections, tags and its current eligibility tree", "Embedded tree", "slug (unique); {status, level, state}; tags; text(name, description, tags)"],
    ["scheme_versions", "Frozen copy of every published rule set", "Append-only, versioned", "{scheme_slug, version:-1} unique"],
    ["evaluations", "Audit log of every check with profile + rules snapshots and checksum", "Embedded snapshots, append-only", "{user_id, evaluated_at:-1}; run_id; {scheme_slug, scheme_version}"],
    ["document_chunks", "Section-based text chunks + 256-d embeddings for retrieval", "Reference by slug; denormalised filters", "{scheme_slug, chunk_index} unique; {level, state}; text(text, scheme_name)"],
    ["users", "Account (email, password hash, role)", "Standard", "email unique"],
    ["user_profiles", "Eligibility attributes + consent", "Flexible sub-document", "user_id unique"],
    ["attribute_registry", "Vocabulary of allowed rule attributes; drives the wizard", "Reference data", "key unique"],
    ["ingestion_jobs", "Pipeline state per scheme + proposed rules", "State machine", "{scheme_slug, source_hash} unique; {stage, updated_at}"],
    ["chat_logs", "Questions, routes and cited sources", "Expiring log", "TTL on created_at (30 days)"],
    ["rate_limits", "Per-IP request counters", "Expiring counters", "TTL on expires_at; {key, window} unique"],
], widths=[2.9, 5.2, 3.3, 5.0], size=8.5)
doc.add_heading("5.1 The scheme document", 2)
code('''{
  "slug": "apy",  "name": "Atal Pension Yojana",
  "level": "central", "state": null, "tags": ["pension", "unorganized", ...],
  "sections": {"description": "...", "benefits": "...", "eligibility": "...", "exclusions": "...", ...},
  "source_url": "https://www.myscheme.gov.in/schemes/apy",
  "status": "published", "current_version": 1, "last_verified_at": ISODate("2026-10-21"),
  "eligibility": { "op": "AND", "children": [
      { "id": "r1", "attribute": "age", "operator": "between", "value": [18, 40],
        "description": "Joining age 18 to 40 years",
        "source_quote": "The minimum age of joining APY is 18 years and maximum is 40 years." },
      { "op": "NOT", "children": [
          { "id": "r2", "attribute": "is_income_tax_payer", "operator": "==", "value": true,
            "description": "Income-tax payers (current or past) are excluded" } ] } ] },
  "unmapped_conditions": ["Contribution by auto-debit from a savings bank account"]
}''')
para("Operators: ==, !=, <, <=, >, >=, in, not_in, between, exists. Groups: AND, OR, NOT (nestable). Every leaf keeps "
     "the exact sentence it came from (source_quote), which the validator checks against the source text.")
doc.add_heading("5.2 The evaluation (audit) document", 2)
code('''{
  "run_id": "run_7f3c...", "user_id": ObjectId("...") | null,
  "scheme_slug": "apy", "scheme_version": 1, "engine_version": "rules-engine@1.0.0",
  "evaluated_at": ISODate("2026-10-21T08:12:44.120Z"),
  "profile_snapshot": { "age": 29, "is_income_tax_payer": false },      // only attributes the rules used
  "rules_snapshot":   { /* frozen copy of eligibility v1 */ },
  "verdict": "ELIGIBLE",
  "reasons": [ {"rule_id": "r1", "result": "PASS", "detail": "age = 29 satisfies between [18, 40] ..."}, ... ],
  "missing_attributes": [],
  "checksum": "sha256:9a1e..."                                           // hash of all fields above
}''')
para("Because the evaluation embeds what it used, it can be replayed and verified without joins, and stays truthful even "
     "if the scheme or the user's profile changes later. Only the attributes the scheme's rules reference are "
     "snapshotted (data minimisation).")
doc.add_heading("5.3 Data types and access patterns", 2)
table(["Access pattern", "How the model serves it"], [
    ["Run a check over all schemes for a profile", "Index {status, level, state} pre-filters central + user-state published schemes; one read per scheme document, no joins"],
    ["Show scheme detail page", "Single document by unique slug"],
    ["List a user's history, newest first", "Compound index {user_id, evaluated_at: -1} gives an index-ordered scan"],
    ["Show all verdicts of one click", "Index on run_id"],
    ["Which evaluations used version N of a scheme?", "Index {scheme_slug, scheme_version}"],
    ["Keyword search by scheme name (e.g. 'Atal Pension')", "Text index on chunks (scheme_name weighted 5x)"],
    ["Semantic search", "256-d float array per chunk; $vectorSearch on Atlas, cosine fallback elsewhere"],
], widths=[6, 10.4], size=9)
doc.add_heading("5.4 Scalability considerations", 2)
bullets(["evaluations grows fastest (one document per scheme per check). It is append-only and naturally shardable on "
         "{user_id, evaluated_at} or hashed run_id; old runs can be archived to cold storage.",
         "document_chunks carries level/state/tags copied from the scheme so vector and text search can pre-filter without "
         "a lookup.",
         "Scheme documents are small (tens of KB) and far below the 16 MB document limit even with full text sections.",
         "Reads of schemes dominate and can be served from secondary members with readPreference=secondaryPreferred."])

# ---------------------------------------------------------------- 6. CRUD
doc.add_heading("6. CRUD implementation", 1)
para("All operations go through PyMongo from FastAPI route handlers. Every write is validated twice: by Pydantic at the "
     "API boundary and by the collection's JSON Schema validator inside MongoDB.")
table(["Operation", "Collection", "Endpoint", "MongoDB call"], [
    ["Create", "users", "POST /api/auth/register", "insert_one (unique email index rejects duplicates)"],
    ["Create", "evaluations", "POST /api/eligibility/check", "insert_many (one per scheme, shared run_id)"],
    ["Create", "scheme_versions", "POST /api/admin/review/{slug}/approve", "insert_one inside a transaction"],
    ["Create", "ingestion_jobs", "scripts/seed.py, POST /api/admin/ingest", "update_one(..., upsert=True) — idempotent on slug + hash"],
    ["Read", "schemes", "GET /api/schemes?level=&state=&tag=&q=&page=", "find + text search + skip/limit pagination"],
    ["Read", "schemes", "GET /api/schemes/{slug}", "find_one by unique slug"],
    ["Read", "evaluations", "GET /api/eligibility/runs/{run_id}", "find by run_id"],
    ["Read", "evaluations", "GET /api/admin/stats", "aggregate pipelines ($match, $group, $unwind, $sort)"],
    ["Update", "user_profiles", "PUT /api/profile", "update_one({user_id}, {$set: ...}, upsert=True)"],
    ["Update", "schemes", "approve / retire", "update_one $set status, current_version, eligibility (in transaction)"],
    ["Delete", "user_profiles + evaluations", "DELETE /api/profile", "delete_one + delete_many (right to erasure)"],
    ["Delete (soft)", "schemes", "POST /api/admin/schemes/{slug}/retire", "status → retired (history preserved)"],
], widths=[2.0, 3.2, 5.4, 5.8], size=8.5)
doc.add_heading("6.1 Example: create with validation", 2)
code('''def register(body: RegisterIn):                       # Pydantic: email format, password >= 8 chars
    try:
        uid = db.users.insert_one({"email": body.email.lower(), "name": body.name,
                                   "password_hash": hash_password(body.password),
                                   "role": "user", "created_at": now()}).inserted_id
    except DuplicateKeyError:
        raise HTTPException(409, "Email already registered")''')
doc.add_heading("6.2 Example: update with upsert and consent", 2)
code('''db.user_profiles.update_one(
    {"user_id": user["_id"]},
    {"$set": {"attributes": clean, "consent": {"store_profile": True, "given_at": now()}, "updated_at": now()}},
    upsert=True)''')
doc.add_heading("6.3 Example: delete (privacy)", 2)
code('''db.user_profiles.delete_one({"user_id": user["_id"]})
db.evaluations.delete_many({"user_id": user["_id"]})      # the user's own history only''')
para("Persistence is verified by the API tests, which create, read back, update and delete through HTTP and then query "
     "MongoDB directly.")

# ---------------------------------------------------------------- 7. Advanced
doc.add_heading("7. Advanced NoSQL features and query optimisation", 1)
doc.add_heading("7.1 JSON Schema validation at the database", 2)
code('''db.create_collection("evaluations", validator={"$jsonSchema": {
    "bsonType": "object",
    "required": ["run_id", "scheme_slug", "scheme_version", "verdict", "reasons", "checksum", ...],
    "properties": {
        "verdict":  {"enum": ["ELIGIBLE", "INELIGIBLE", "NEEDS_MORE_INFO"]},
        "checksum": {"bsonType": "string", "pattern": "^sha256:"} }}}, validationLevel="strict")''')
para("Similar validators guard schemes (level, status and group-operator enums; slug pattern), user_profiles "
     "(age 0–120, non-negative income and land) and users (email pattern, role enum).")
doc.add_heading("7.2 Multi-document transaction: publishing a rule version", 2)
code('''with client.start_session() as s:
    s.with_transaction(lambda sess: (
        db.scheme_versions.insert_one({...version N + 1...}, session=sess),
        db.schemes.update_one({"slug": slug}, {"$set": {"eligibility": tree, "current_version": N + 1,
                                                        "status": "published"}}, session=sess)))''')
para("Either both writes happen or neither does, so a scheme can never point to a version that does not exist. "
     "Published versions are never modified; a rule change is always a new version with a change note and reviewer.")
doc.add_heading("7.3 Aggregation pipelines", 2)
code('''# Verdict distribution per scheme across all checks
db.evaluations.aggregate([
  {"$group": {"_id": {"scheme": "$scheme_slug", "verdict": "$verdict"}, "n": {"$sum": 1}}},
  {"$group": {"_id": "$_id.scheme", "verdicts": {"$push": {"k": "$_id.verdict", "v": "$n"}}, "total": {"$sum": "$n"}}},
  {"$project": {"total": 1, "verdicts": {"$arrayToObject": "$verdicts"}}},
  {"$sort": {"total": -1}}, {"$limit": 10}])

# Which missing answers block the most verdicts? (drives UX)
db.evaluations.aggregate([
  {"$match": {"verdict": "NEEDS_MORE_INFO"}}, {"$unwind": "$missing_attributes"},
  {"$group": {"_id": "$missing_attributes", "n": {"$sum": 1}}}, {"$sort": {"n": -1}}])

# Schemes per state, split by publish status
db.schemes.aggregate([{"$group": {"_id": {"$ifNull": ["$state", "Central"]},
                                  "published": {"$sum": {"$cond": [{"$eq": ["$status", "published"]}, 1, 0]}},
                                  "total": {"$sum": 1}}}, {"$sort": {"total": -1}}])''')
doc.add_heading("7.4 Indexing and query optimisation", 2)
para("Queries were checked with explain('executionStats'). The table compares the same query with and without its "
     "supporting index (numbers from scripts/collect_results.py on this dataset; 'without index' forces a collection scan with hint($natural)).")
bench = r("bench", [])
if bench:
    table(["Query", "Without index", "With index", "Plan with index"],
          [[b["query"], f"{b['no_index']['docs_examined']} docs · {b['no_index']['ms']} ms",
            f"{b['with_index']['docs_examined']} docs · {b['with_index']['ms']} ms", b["with_index"]["stage"]] for b in bench],
          widths=[5.6, 3.4, 3.4, 4.0], size=8.5)
else:
    para("[Benchmark table is generated by scripts/collect_results.py.]", italic=True)
bullets(["Equality-sort-range ordering in compound indexes: {status, level, state} for the check pre-filter and "
         "{user_id, evaluated_at: -1} for history (index-ordered, no in-memory SORT stage).",
         "Projections exclude large fields (embeddings, embed_text) from result documents.",
         "Bulk insert_many(ordered=False) writes all evaluations of a run in one round trip.",
         "Text index weights (scheme_name 5x) make exact scheme-name questions rank first."])
doc.add_heading("7.5 TTL indexes", 2)
code('''db.chat_logs.create_index("created_at", expireAfterSeconds=30*24*3600)    # questions auto-deleted after 30 days
db.rate_limits.create_index("expires_at", expireAfterSeconds=0)            # per-minute counters expire themselves''')
doc.add_heading("7.6 Text search and vector search (hybrid retrieval)", 2)
para("Keyword search uses a weighted MongoDB text index ($text, sorted by textScore). Semantic search uses 256-d "
     "embeddings stored on each chunk. On MongoDB Atlas the code issues a $vectorSearch aggregation against a "
     "'chunks_vector' index with level/state pre-filters; on a self-hosted server it loads the embedding matrix from "
     "MongoDB once and computes cosine similarity in NumPy. Results are merged with Reciprocal Rank Fusion: "
     "score(d) = Σ 1 / (60 + rank_i(d)).")

# ---------------------------------------------------------------- 8. Rules engine
doc.add_heading("8. Rules engine design", 1)
para("The engine is a small recursive interpreter over the rule tree (api/engine/evaluate.py). It is pure — no "
     "database access — so it is unit-testable and evaluates every scheme in memory in milliseconds.")
figure(IMG / "rule_tree.png", "Figure 3 — Evaluating a rule tree with three-valued logic", width=14)
doc.add_heading("8.1 Three-valued logic", 2)
para("A missing answer is UNKNOWN, never FAIL. This turns \"you are not eligible\" into \"tell us your land holding and "
     "we can check\".")
table(["AND", "PASS", "FAIL", "UNKNOWN"], [["PASS", "PASS", "FAIL", "UNKNOWN"], ["FAIL", "FAIL", "FAIL", "FAIL"],
                                          ["UNKNOWN", "UNKNOWN", "FAIL", "UNKNOWN"]], widths=[3, 3, 3, 3])
para("OR mirrors AND (any PASS → PASS; all FAIL → FAIL; otherwise UNKNOWN). NOT swaps PASS/FAIL and keeps UNKNOWN. "
     "Final mapping: PASS → ELIGIBLE, FAIL → INELIGIBLE, UNKNOWN → NEEDS_MORE_INFO with the missing attributes. Once a "
     "group's result is decided, its missing attributes are dropped, so users are never asked questions that cannot "
     "change the outcome.")
doc.add_heading("8.2 Next-best question", 2)
para("Across all NEEDS_MORE_INFO verdicts the engine counts how often each missing attribute appears and asks the most "
     "frequent one first — one answer then unlocks the most verdicts.")
doc.add_heading("8.3 From prose to rules: extraction, validation, human review", 2)
para(f"The ingestion pipeline proposes a rule tree for every scheme from its Eligibility and Exclusions sections "
     f"(api/ingest/extract.py). Each leaf carries the exact source sentence; any eligibility sentence that cannot be "
     f"expressed with registered attributes goes into unmapped_conditions and is shown to reviewers and users. Across "
     f"the {len(schemes)} schemes the extractor proposed {leaf_total} rule leaves; {valid} proposals passed automatic "
     f"validation. The validator (api/engine/validate.py) checks: registered attributes only, operator/type match, enum "
     f"values, 'between' ranges, that every source_quote really appears in the source text (catches invented rules), "
     f"that numbers in a rule appear in its quote, and contradictory ranges. Nothing is published without a human "
     f"approving it in the admin review screen; {len(curated)} widely used schemes were hand-reviewed for the demo.")
table(["Attribute", "Leaves proposed"], [[a, n] for a, n in attr_counts.most_common(10)], widths=[6, 4])

# ---------------------------------------------------------------- 9. RAG
doc.add_heading("9. Grounded retrieval-augmented Q&A", 1)
bullets(["**Chunking by section** (Details, Benefits, Eligibility, Exclusions, Application, Documents, FAQ), split at "
         "sentence boundaries into ≤350-word chunks with one sentence of overlap; each chunk is prefixed with "
         "'<Scheme> — <Section>:' before embedding so it is meaningful in isolation.",
         "**Hybrid retrieval**: vector + keyword, fused with RRF, top 6 chunks, optionally pre-filtered to central + "
         "the user's state.",
         "**Intent routing**: eligibility questions ('am I eligible for APY?') go to the rules engine; discovery questions "
         "('schemes for women entrepreneurs') retrieve candidate schemes and then run the engine on them; information "
         "questions use pure retrieval; off-topic questions are politely refused.",
         "**Grounding**: answers are built only from the numbered sources; every sentence carries a citation [n]; code "
         "checks that every citation points to a supplied source; an answer with no valid citation is replaced by the "
         "refusal line \"I don't have reliable information on that. Please check myscheme.gov.in.\"",
         "**The LLM never decides eligibility**: verdicts come only from the engine's ELIGIBILITY RESULTS block. Without an "
         "API key the system composes an extractive answer from the highest-scoring source sentences, so it is fully "
         "functional offline."])

# ---------------------------------------------------------------- 10. Integration
doc.add_heading("10. Application integration and functionality", 1)
table(["Method", "Path", "Purpose", "Auth"], [
    ["GET", "/api/health", "Liveness + database ping + replica-set status", "Public"],
    ["GET", "/api/attributes", "Attribute registry → drives the profile wizard", "Public"],
    ["GET", "/api/schemes", "List/filter/search schemes with pagination", "Public"],
    ["GET", "/api/schemes/{slug}", "Scheme detail, current rules, versions, staleness", "Public"],
    ["POST", "/api/eligibility/check", "Run the engine on a profile; writes the audit log", "Optional"],
    ["GET", "/api/eligibility/runs/{run_id}", "Results of a past run", "Optional"],
    ["GET", "/api/eligibility/history", "The user's own past checks", "User"],
    ["POST", "/api/auth/register · /api/auth/login", "Create account / obtain JWT", "Public"],
    ["GET · PUT · DELETE", "/api/profile", "Read / save (with consent) / delete profile and history", "User"],
    ["POST", "/api/chat", "Ask a question; streamed answer (SSE) with citations", "Optional, rate-limited"],
    ["GET", "/api/admin/review", "Schemes awaiting review with proposals and validation errors", "Admin"],
    ["POST", "/api/admin/review/{slug}/approve", "Approve / edit a rule tree → publish new version (transaction)", "Admin"],
    ["POST", "/api/admin/schemes/{slug}/retire", "Soft-delete a scheme", "Admin"],
    ["GET", "/api/admin/evaluations/{id}/replay", "Re-run a stored evaluation; verify verdict and checksum", "Admin"],
    ["GET", "/api/admin/stats", "Aggregation dashboards", "Admin"],
], widths=[2.4, 5.6, 6.2, 2.2], size=8.5)
para("User interface pages: **Check** (profile wizard generated from the attribute registry, results in three groups "
     "with reasons, next-best-question prompt), **Ask** (streamed answers with clickable source chips), **Schemes** "
     "(search and filters, detail with rule tree and version history, 'last verified' warning), **Account** (login, "
     "saved profile, history, delete my data) and **Admin** (review queue, approve, stats, replay). Errors from the API "
     "are shown as readable messages; loading and empty states are handled.")
shots = sorted((IMG).glob("screen_*.png"))
for i, s in enumerate(shots, 1):
    figure(s, f"Figure {3 + i} — {s.stem.split('_', 2)[2].replace('_', ' ').capitalize()}", width=15.5)

# ---------------------------------------------------------------- 11. Testing & security
doc.add_heading("11. Testing, security and data validation", 1)
doc.add_heading("11.1 Input validation (three layers)", 2)
bullets(["**API**: Pydantic models with ranges (age 0–120, income ≥ 0, marks 0–100), enums from the registry, string "
         "length limits; unknown profile keys are rejected.",
         "**Rules**: the publish-time validator described in §8.3.",
         "**Database**: JSON Schema validators with validationLevel=strict; unique indexes for identity invariants."])
doc.add_heading("11.2 Authentication and access control", 2)
bullets(["Passwords hashed with PBKDF2-SHA256 (240,000 iterations, per-user salt); constant-time comparison.",
         "JWT bearer tokens (HS256, 12-hour expiry); secret read from the environment.",
         "Roles: anonymous users may check eligibility (profile stays in the browser); users can save profiles and see "
         "history; only admins reach /api/admin/* (HTTP 403 otherwise).",
         "Audit integrity: evaluations are insert-only from the API; each carries a SHA-256 checksum verified on replay.",
         "Privacy: no Aadhaar or identity numbers are collected; profiles are saved only with explicit consent; "
         "DELETE /api/profile erases profile and history; chat logs expire via TTL.",
         "Abuse control: per-IP rate limit on /api/chat using a TTL-indexed counter collection.",
         "Injection safety: queries are built as Python dicts (no string concatenation); operator keys from user input "
         "are never passed through."])
doc.add_heading("11.3 Automated tests", 2)
table(["Suite", "What it checks"], [
    ["tests/test_engine.py", "AND/OR/NOT truth tables over PASS/FAIL/UNKNOWN; short-circuit drops irrelevant missing attributes; next-best question"],
    ["tests/test_properties.py (Hypothesis)", "NOT(NOT(x)) == x; adding a missing answer never turns PASS into UNKNOWN; verdict is total"],
    ["tests/test_fixtures.py", "Per-scheme fixture profiles → expected verdict for the curated schemes"],
    ["tests/test_validate.py", "Unknown attribute/operator, bad enum, invented source quote, number not in quote, contradictions are rejected"],
    ["tests/test_api.py", "End-to-end CRUD through HTTP on a temporary database; auth and 403 for non-admins; replay checksum; validator rejection"],
], widths=[5.2, 11.2], size=9)
tests = r("tests")
if tests != "—":
    para(f"Result of the last run: **{tests['passed']} passed, {tests['failed']} failed** in {tests['seconds']} s "
         f"(pytest {tests.get('pytest', '')}).")

# ---------------------------------------------------------------- 12. Results
doc.add_heading("12. Results", 1)
table(["Measure", "Value"], [
    ["PDFs downloaded from Hugging Face (duplicates removed)", n_pdfs],
    ["Unique schemes parsed with an Eligibility section", len(schemes)],
    ["Central / state schemes", f"{levels['central']} / {levels['state']}"],
    ["States / UTs covered", n_states],
    ["Rule leaves proposed by extractor", leaf_total],
    ["Proposals passing automatic validation", f"{valid} of {len(schemes)}"],
    ["Hand-reviewed published schemes (demo)", len(curated)],
    ["Text chunks indexed for retrieval", r("chunks")],
    ["Evaluation (audit) documents in the benchmark database", r("evaluations")],
    ["Automated tests", r("tests.summary")],
    ["Rules-engine fixture accuracy", r("fixture_accuracy")],
    ["Median eligibility check over all published schemes (incl. audit write)", r("check_ms")],
], widths=[11, 5.4])
ev = r("rag_eval")
if ev != "—":
    para(f"Retrieval evaluation on {ev['n']} questions whose answer scheme is known (question → expected scheme):")
    table(["Configuration", "Recall@5", "MRR"], [[k, f"{v['recall@5']:.2f}", f"{v['mrr']:.2f}"] for k, v in ev["configs"].items()],
          widths=[6, 4, 4])
    if "refusal" in ev:
        para(f"Unanswerable / off-topic questions correctly refused: {ev['refusal']}.")
    c = ev["configs"]
    para(f"'Named' questions mention the scheme by name; 'descriptive' questions paraphrase the scheme's purpose "
         f"without its name. Keyword search is near-perfect when the name is present (Recall@5 "
         f"{c['keyword · named']['recall@5']:.2f}) but weak on paraphrases ({c['keyword · descriptive']['recall@5']:.2f}); "
         f"vector search is the reverse. Hybrid RRF keeps the named-question accuracy "
         f"({c['hybrid · named']['recall@5']:.2f}) but on descriptive questions it scored "
         f"{c['hybrid · descriptive']['recall@5']:.2f}, below vector-only ({c['vector · descriptive']['recall@5']:.2f}), because "
         f"low-quality keyword matches dilute the fused ranking. An honest finding of the evaluation: a next step is to "
         f"weight the two lists (or route by whether a scheme name is detected) and to re-test.")

# ---------------------------------------------------------------- 13. Limitations
doc.add_heading("13. Limitations and future work", 1)
bullets(["The dataset is a snapshot (pages from 2024) and may be outdated; the UI shows last_verified_at and flags schemes "
         "not verified in 90 days. Production use should ingest from the official API Setu myScheme APIs.",
         "The rule extractor is pattern-based; an LLM with JSON-schema output can replace it behind the same validator "
         "and review gate. Some conditions (e.g. 'no family member in government service') remain unmapped and are shown "
         "as warnings.",
         "LSA embeddings are English-centric; a multilingual model would let Hindi questions retrieve English text.",
         "Deployment to MongoDB Atlas (to use native $vectorSearch / $search indexes), a Hindi UI and an evaluation set "
         "for answer faithfulness are the next steps."])

# ---------------------------------------------------------------- 14. Conclusion
doc.add_heading("14. Conclusion", 1)
para("The project shows that MongoDB's document model fits rule-heavy, heterogeneous government data well: each scheme "
     "and its recursive eligibility tree is one document, versions are immutable documents published in transactions, "
     "and each decision is a self-contained, checksummed audit document that can be replayed without joins. JSON Schema "
     "validators, unique and compound indexes, text and vector search, aggregation pipelines and TTL indexes cover the "
     "integrity, performance and privacy needs. On top of this, a three-valued rules engine gives explainable verdicts "
     "and a grounded Q&A layer answers questions with citations while never deciding eligibility itself.")

doc.add_heading("References", 1)
bullets(["MongoDB Manual — Data Modeling, Schema Validation, Transactions, TTL Indexes, Text Indexes, Aggregation. https://www.mongodb.com/docs/manual/",
         "MongoDB Atlas Vector Search and Atlas Search documentation. https://www.mongodb.com/docs/atlas/",
         "myScheme — National platform for government schemes. https://www.myscheme.gov.in/",
         "shrijayan/gov_myscheme dataset, Hugging Face. https://huggingface.co/datasets/shrijayan/gov_myscheme",
         "FastAPI documentation. https://fastapi.tiangolo.com/  ·  PyMongo documentation. https://pymongo.readthedocs.io/",
         "Cormack, Clarke, Büttcher (2009). Reciprocal Rank Fusion outperforms Condorcet and individual rank learning methods. SIGIR.",
         "Lewis et al. (2020). Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks. NeurIPS."], style="List Number")

doc.add_heading("Appendix A — Setup and run instructions", 1)
code('''# 1. Python packages
pip install -r requirements.txt
# 2. Start a single-node replica set (transactions need it) — Windows PowerShell
powershell -ExecutionPolicy Bypass -File scripts\\start_mongo.ps1
# 3. Download data (token only needed if rate-limited), parse, extract, publish, chunk + embed
$env:HF_TOKEN="<your token>"; python scripts\\download_hf.py
python scripts\\seed.py
# 4. Run the app  ->  http://127.0.0.1:8000  (API docs at /docs)
uvicorn api.main:app --port 8000
# 5. Tests
pytest -q''')
para("Demo accounts (admin@example.org, user@example.org) are created by the seed script with random passwords, "
     "which are written to the git-ignored file .env.demo for local use only.", size=10)

doc.add_heading("Appendix B — Demonstration / viva script", 1)
bullets(["Open Check, enter age 29, state Assam, income ₹90,000, BPL yes → show Eligible / Needs-more-info / Ineligible "
         "groups and the per-rule reasons; answer the suggested next question and watch verdicts move.",
         "Open a scheme (APY) → rule tree with source quotes, version history and last-verified date.",
         "Ask: 'What documents are needed for Atal Pension Yojana?' → streamed answer with source chips; then ask an "
         "off-topic question to show the refusal.",
         "Admin: approve a proposed scheme from the review queue → new version created in a transaction; replay an "
         "evaluation to show verdict + checksum verification.",
         "MongoDB shell / Compass: show validators (try inserting a bad verdict → rejected), indexes, explain() plans, "
         "aggregation pipeline output, the TTL index.",
         "Run pytest to show the test suite passing."])
para("Plagiarism report: to be generated with the institution's plagiarism-checking tool and attached with this report.",
     italic=True, size=10)

OUT.parent.mkdir(exist_ok=True)
doc.save(OUT)
print("wrote", OUT)

# Numbers shared with the slide deck generator (docs/build_deck.js)
(ROOT / "docs" / "stats.json").write_text(json.dumps({
    "pdfs": n_pdfs, "schemes": len(schemes), "central": levels["central"], "state": levels["state"],
    "states": n_states, "leaves": leaf_total, "valid": valid, "curated": len(curated),
    "top_attrs": attr_counts.most_common(6)}, indent=1), encoding="utf-8")
