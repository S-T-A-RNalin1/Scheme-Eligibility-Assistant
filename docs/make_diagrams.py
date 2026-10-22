"""Render the architecture, data-model and engine diagrams used in the report and slides."""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams["text.parse_math"] = False  # "$push", "$facet" are MongoDB operators, not maths
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

OUT = Path(__file__).absolute().parent / "img"
OUT.mkdir(exist_ok=True)

INK, MUTED = "#1F2937", "#6B7280"
C = {"web": "#DBEAFE", "api": "#E0E7FF", "eng": "#DCFCE7", "rag": "#FEF3C7", "db": "#D1FAE5", "ing": "#FCE7F3"}
EDGE = {"web": "#2563EB", "api": "#4F46E5", "eng": "#16A34A", "rag": "#D97706", "db": "#059669", "ing": "#DB2777"}


def box(ax, x, y, w, h, title, lines, kind):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.12",
                                fc=C[kind], ec=EDGE[kind], lw=1.6))
    ax.text(x + w / 2, y + h - 0.28, title, ha="center", va="top", fontsize=11, fontweight="bold", color=INK)
    for i, line in enumerate(lines):
        ax.text(x + w / 2, y + h - 0.68 - i * 0.30, line, ha="center", va="top", fontsize=8.5, color=MUTED)


def arrow(ax, a, b, label="", both=False):
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle="<|-|>" if both else "-|>", mutation_scale=13,
                                 color="#374151", lw=1.3, shrinkA=2, shrinkB=2))
    if label:
        ax.text((a[0] + b[0]) / 2 + 0.08, (a[1] + b[1]) / 2 + 0.08, label, fontsize=8, color="#374151")


def architecture():
    fig, ax = plt.subplots(figsize=(12, 7.2))
    ax.set_xlim(0, 12); ax.set_ylim(0, 7.2); ax.axis("off")
    box(ax, 0.3, 5.3, 3.4, 1.6, "Web UI: 3 pages", ["/  check, ranked picks, Ask, tracker", "/login  Citizen | Admin", "/admin  coverage gaps, grievances"], "web")
    box(ax, 4.3, 5.3, 3.4, 1.6, "FastAPI backend", ["REST + SSE, Pydantic v2", "JWT, citizen / admin roles", "Recommendations, coverage analytics"], "api")
    box(ax, 0.3, 2.7, 3.4, 1.9, "Rules engine (pure)", ["Rule-tree interpreter", "3-valued logic: PASS/FAIL/UNKNOWN", "Reasons + next-best question", "Validator (publish gate)"], "eng")
    box(ax, 4.3, 2.7, 3.4, 1.9, "Grounded RAG service", ["Intent router", "Hybrid retrieval (vector+text, RRF)", "Grounding prompt + citation check", "Refuses when unsupported"], "rag")
    box(ax, 8.3, 2.7, 3.4, 1.9, "Ingestion pipeline", ["fetch → parse → extract", "validate → hand-check → publish", "chunk + embed, tag groups", "ingestion_jobs state machine"], "ing")
    box(ax, 0.6, 0.2, 10.8, 1.8, "MongoDB (replica set rs0) · 15 collections", ["schemes · scheme_versions · document_chunks · evaluations · applications · grievances · counters", "users · user_profiles · attribute_registry · ingestion_jobs · search_logs · regions · chat_logs · rate_limits",
                                                             "JSON-Schema validators · compound/text/TTL/2dsphere indexes · transactions"], "db")
    box(ax, 8.3, 5.3, 3.4, 1.6, "Data sources", ["Hugging Face gov_myscheme", "(myScheme.gov.in pages)", "601 PDFs → 570 schemes"], "ing")
    arrow(ax, (3.7, 6.1), (4.3, 6.1), "HTTPS", both=True)
    arrow(ax, (5.2, 5.3), (2.6, 4.6), "check")
    arrow(ax, (6.0, 5.3), (6.0, 4.6), "chat")
    arrow(ax, (4.3, 2.9), (3.7, 2.9), "")
    arrow(ax, (10.0, 5.3), (10.0, 4.6), "PDF text")
    arrow(ax, (2.0, 2.7), (3.6, 2.0), "rules / audit")
    arrow(ax, (6.0, 2.7), (6.0, 2.0), "chunks")
    arrow(ax, (10.0, 2.7), (8.6, 2.0), "publish (txn)")
    fig.savefig(OUT / "architecture.png", dpi=170, bbox_inches="tight"); plt.close(fig)


def data_model():
    fig, ax = plt.subplots(figsize=(12, 6.6))
    ax.set_xlim(0, 12); ax.set_ylim(0, 6.6); ax.axis("off")
    cols = [
        (0.2, 3.5, "schemes", ["slug (unique)", "name, level, state, tags[]", "sections{…}, benefits", "eligibility{op, children[]}", "current_version, status", "last_verified_at"], "db"),
        (4.2, 3.5, "scheme_versions", ["scheme_slug + version (unique)", "eligibility (frozen)", "source_snapshot_hash", "extracted_by, reviewed_by", "change_note, effective_from", "append-only"], "eng"),
        (8.2, 3.5, "evaluations", ["run_id, user_id", "scheme_slug, scheme_version", "profile_snapshot (embedded)", "rules_snapshot (embedded)", "verdict, reasons[], missing[]", "checksum (sha256)"], "rag"),
        (0.2, 0.2, "document_chunks", ["scheme_slug, section", "chunk_index, text", "embedding[256] (float)", "level, state, tags (filters)", "source_url (citations)", "text index"], "web"),
        (4.2, 0.2, "users / profiles / applications", ["users: email (unique), role", "user_profiles: attributes, consent", "applications: user + scheme (unique)", "documents[] ($set + arrayFilters)", "history[] ($push), deadline", "reminders via $dateDiff + $facet"], "api"),
        (8.2, 0.2, "grievances · analytics", ["grievances: ticket, timeline[]", "counters: atomic ticket no. ($inc)", "search_logs: demand, TTL 180 days", "regions: GeoJSON point", "2dsphere index → $geoNear", "schemes: primary / beneficiary groups"], "ing"),
    ]
    for x, y, t, lines, k in cols:
        box(ax, x, y, 3.6, 2.9, t, lines, k)
    arrow(ax, (3.8, 5.0), (4.2, 5.0), "1 : N")
    arrow(ax, (7.8, 5.0), (8.2, 5.0), "snapshot")
    arrow(ax, (2.0, 3.5), (2.0, 3.1), "1 : N (slug)")
    arrow(ax, (6.0, 3.1), (8.2, 4.0), "user_id")
    arrow(ax, (10.0, 3.1), (10.0, 3.5), "")
    fig.savefig(OUT / "data_model.png", dpi=170, bbox_inches="tight"); plt.close(fig)


def rule_tree():
    fig, ax = plt.subplots(figsize=(10, 4.6))
    ax.set_xlim(0, 10); ax.set_ylim(0, 4.6); ax.axis("off")

    def node(x, y, text, kind, w=2.3):
        ax.add_patch(FancyBboxPatch((x - w / 2, y - 0.32), w, 0.64, boxstyle="round,pad=0.02,rounding_size=0.1",
                                    fc=C[kind], ec=EDGE[kind], lw=1.4))
        ax.text(x, y, text, ha="center", va="center", fontsize=9, color=INK)
    node(5, 4.0, "AND  →  NEEDS_MORE_INFO", "api", 3.0)
    node(1.6, 2.5, "age between [18, 40]\nPASS (age = 29)", "eng", 2.9)
    node(5, 2.5, "NOT", "api", 1.2)
    node(8.4, 2.5, "state == profile state\nUNKNOWN → asked next", "rag", 2.9)
    node(5, 1.0, "is_income_tax_payer == true\nFAIL → NOT gives PASS", "eng", 3.2)
    for a, b in [((5, 3.68), (1.6, 2.82)), ((5, 3.68), (5, 2.82)), ((5, 3.68), (8.4, 2.82)), ((5, 2.18), (5, 1.32))]:
        arrow(ax, a, b)
    ax.text(5, 0.2, "Illustration: one FAIL in an AND settles the verdict; UNKNOWN only matters if nothing has failed.",
            ha="center", fontsize=8.5, color=MUTED)
    fig.savefig(OUT / "rule_tree.png", dpi=170, bbox_inches="tight"); plt.close(fig)


if __name__ == "__main__":
    architecture(); data_model(); rule_tree()
    print("diagrams written to", OUT)
