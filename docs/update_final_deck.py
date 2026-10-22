"""Update the hand-edited 16-slide deck (Scheme_Eligibility_Assistant_Final.pptx) in place.

Only content changes: text, the two diagrams, two screenshots and the two charts. Layout, styling,
slide count and the team's own edits (title slide etc.) are kept.
"""
import copy
import json
from pathlib import Path

from pptx import Presentation
from pptx.chart.data import CategoryChartData

DOCS = Path(__file__).absolute().parent
IMG = DOCS / "img"
DECK = DOCS / "Scheme_Eligibility_Assistant_Final.pptx"
R = json.loads((DOCS / "results.json").read_text(encoding="utf-8"))


def set_text(shape, text):
    """Replace a text box's text, keeping the first run's formatting on every line."""
    tf = shape.text_frame
    lines = text.split("\n")
    body = tf._txBody
    while len(tf.paragraphs) < len(lines):
        body.append(copy.deepcopy(tf.paragraphs[-1]._p))
    for p in list(tf.paragraphs)[len(lines):]:
        body.remove(p._p)
    for p, line in zip(tf.paragraphs, lines):
        runs = p.runs
        if not runs:
            p.add_run().text = line
            continue
        runs[0].text = line
        for r in runs[1:]:
            p._p.remove(r._r)


def shape(slide, idx):
    return list(slide.shapes)[idx]


def replace_picture(slide, idx, path):
    """Put the new image inside the old picture's box (scaled to fit, centred), so nothing else on the slide moves."""
    old = shape(slide, idx)
    from PIL import Image
    w_px, h_px = Image.open(path).size
    scale = min(old.width / w_px, old.height / h_px)
    width, height = int(w_px * scale), int(h_px * scale)
    left = old.left + (old.width - width) // 2
    new = slide.shapes.add_picture(str(path), left, old.top, width, height)
    new.name = old.name
    old._element.addprevious(new._element)  # same z-order position as the old picture
    old._element.getparent().remove(old._element)
    return new


prs = Presentation(DECK)
S = list(prs.slides)
assert len(S) == 16, len(S)

# 3 — Objectives
s = S[2]
set_text(shape(s, 5), "Profile → Eligible / Ineligible / Needs more info for every scheme, a reason per rule, every check saved with a checksum")
set_text(shape(s, 14), "Personal tools")
set_text(shape(s, 15), "Ranked recommendations, an application tracker with reminders, and a grievance portal")
set_text(shape(s, 20), "CRUD, validation, $facet / $bucket aggregation, geospatial $geoNear, arrayFilters, transactions, TTL")

# 5, 6 — diagrams
replace_picture(S[4], 1, IMG / "architecture.png")
replace_picture(S[5], 1, IMG / "data_model.png")
set_text(shape(S[5], 2), "Embed what is read together: scheme + its rule tree; tracker checklist + history\n"
                         "Reference what changes on its own: chunks, versions, applications by slug\n"
                         "Snapshot what must never change: each evaluation stores the rules and profile it used\n"
                         "15 collections; unique / compound / text / TTL / 2dsphere indexes")

# 8 — CRUD
s = S[7]
set_text(shape(s, 5), "register · insert_many evaluations per check · version in a transaction · grievance with atomic ticket no. · save scheme to tracker")
set_text(shape(s, 10), "filter / text-search / paginate schemes · detail by slug · user history (index-ordered) · ranked recommendations")
set_text(shape(s, 15), "profile ($set, upsert) · tracker status + checklist ($set with arrayFilters) · grievance reply ($push)")
set_text(shape(s, 20), "delete my data (profile, history, tracker) · remove checklist item ($pull) · retire a scheme (soft delete)")

# 9 — Advanced features (6 cards)
s = S[8]
set_text(shape(s, 8), "$facet · $bucket")
set_text(shape(s, 9), "Coverage gaps by state and group; reminders; dashboards")
set_text(shape(s, 14), "Geospatial + TTL")
set_text(shape(s, 15), "2dsphere + $geoNear for nearby states; logs expire on their own")

# 10 — Rules pipeline (no admin review screen any more)
s = S[9]
set_text(shape(s, 11), "Hand-check")
set_text(shape(s, 20), "hand-checked schemes published")
set_text(shape(s, 21), "Validator checks: registered attributes only · operator matches type · quote really appears in the source · "
                       "numbers appear in the quote · no contradictory ranges. Unchecked proposals are used only as clearly "
                       "labelled \"unverified\" recommendation hints.")

# 11 — Grounded Q&A
s = S[10]
set_text(shape(s, 5), "Eligibility → rules engine; info → retrieval; off-topic → refuse. Spelling and plural matching (yojna → yojana)")
set_text(shape(s, 15), "Only numbered sources, each passage must contain the question's topic words; no valid citation → refusal")

# 12 — Security & testing
t = R["tests"]
s = S[11]
set_text(shape(s, 3), "• PBKDF2-SHA256 password hashes, JWT bearer tokens\n"
                      "• Separate Citizen / Admin login; the server checks the role\n"
                      "• Admin routes return 403 to citizens\n"
                      "• Grievances and trackers visible only to their owner\n"
                      "• No Aadhaar or ID numbers stored; delete-my-data\n"
                      "• Audit records insert-only with SHA-256 checksum")
set_text(shape(s, 6), "• Truth tables for AND / OR / NOT\n"
                      "• Property tests (Hypothesis): NOT(NOT(x)) = x\n"
                      "• Fixture profiles → expected verdicts\n"
                      "• Validator rejects invented or malformed rules\n"
                      "• API tests: CRUD, login roles, tracker, ranking, coverage, grievances\n"
                      f"\nLast run: {t['passed']} passed, {t['failed']} failed")
size = shape(s, 6).text_frame.paragraphs[0].runs[0].font.size
for para in shape(s, 6).text_frame.paragraphs:  # the copied blank line had a larger font; match the bullets
    for run in para.runs:
        run.font.size = size

# 13 — Results: numbers + recall chart
s = S[12]
set_text(shape(s, 3), R["check_ms"])
set_text(shape(s, 5), str(R["chunks"]))
ev = R["rag_eval"]
set_text(shape(s, 7), f"{ev['headline']['recall@5']:.2f}")
chart = shape(s, 9).chart
cd = CategoryChartData()
cd.categories = list(ev["configs"])
cd.add_series("Recall@5", [v["recall@5"] for v in ev["configs"].values()])
chart.replace_data(cd)
if chart.has_title:
    chart.chart_title.text_frame.text = f"Retrieval Recall@5 ({ev['n']} questions; refusal on unanswerable {ev['refusal']})"

# 14 — Working application: citizen + officer views
s = S[13]
replace_picture(s, 2, IMG / "screen_7_coverage_gap_analytics_admin.png")
replace_picture(s, 1, IMG / "screen_3_recommendations_and_results.png")
set_text(shape(s, 3), "Citizen: ranked recommendations with reasons, Save to tracker")
set_text(shape(s, 4), "Officer: coverage-gap map and tables ($facet, $bucket, $geoNear)")

# 15 — Index benchmark chart
bench = R["bench"]
chart = shape(S[14], 1).chart
cd = CategoryChartData()
cd.categories = [b["query"] for b in bench]
cd.add_series("Collection scan", [b["no_index"]["docs_examined"] for b in bench])
cd.add_series("With index", [b["with_index"]["docs_examined"] for b in bench])
chart.replace_data(cd)

# 16 — Conclusion
set_text(shape(S[15], 1), "MongoDB's document model fits rule-heavy, variable government data: one document per scheme, "
                          "immutable versions, self-contained audit records, plus ranked recommendations, a tracker, "
                          "grievances and coverage-gap analytics built on aggregation and geospatial indexes.\n"
                          "Next: ingest from the official API Setu feed, add district-level data, move to Atlas Vector "
                          "Search, and add a Hindi UI.")

assert len(prs.slides) == 16
prs.save(DECK)
print("updated", DECK.name, "—", len(prs.slides), "slides")
