"""Parse myScheme page PDFs (Hugging Face dataset) into structured sections.

Each PDF is a print of a myScheme page: navigation chrome, then the scheme
title, state, tags and the sections Details / Benefits / Eligibility /
Exclusions / Application Process / Documents Required / FAQ / Sources.
"""
import hashlib
import re
from pathlib import Path

from pypdf import PdfReader

STATES = [
    "Andaman and Nicobar Islands", "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar",
    "Chandigarh", "Chhattisgarh", "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Goa",
    "Gujarat", "Haryana", "Himachal Pradesh", "Jammu and Kashmir", "Jharkhand", "Karnataka",
    "Kerala", "Ladakh", "Lakshadweep", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya",
    "Mizoram", "Nagaland", "Odisha", "Puducherry", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu",
    "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
]
# Longest first so "West Bengal" wins over a shorter prefix match.
STATES_BY_LEN = sorted(STATES, key=len, reverse=True)

SECTIONS = ["Details", "Benefits", "Eligibility", "Exclusions", "Application Process",
            "Documents Required", "Frequently Asked Questions", "Sources And References"]
SECTION_KEYS = {
    "Details": "description", "Benefits": "benefits", "Eligibility": "eligibility",
    "Exclusions": "exclusions", "Application Process": "application",
    "Documents Required": "documents", "Frequently Asked Questions": "faq",
    "Sources And References": "sources",
}
CHROME_END = "Check Eligibility"
TAIL_JUNK = re.compile(r"(Was this helpful\?|News and Updates|Share$|Feedback\s*$).*", re.S)


MOJIBAKE = {"â‚¹": "₹", "â€™": "'", "â€˜": "'", "â€œ": '"', "â€": '"', "â€“": "–", "â€”": "—",
            "â€¢": "•", "ï»¿": " ", "Â": "", "â€¦": "…"}


def fix_text(text: str) -> str:
    for bad, good in MOJIBAKE.items():
        text = text.replace(bad, good)
    return text


def read_pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    text = text.replace("\t", " ").replace("﻿", " ").replace("​", "")
    return re.sub(r"[  ]+", " ", fix_text(text))


def _split_sections(body: str) -> dict:
    """Split the body at the section headings that appear (in order) after the title block."""
    out, pos, found = {}, 0, []
    for name in SECTIONS:
        idx = body.find(name, pos)
        if idx == -1:
            continue
        found.append((idx, name))
        pos = idx + len(name)
    for i, (idx, name) in enumerate(found):
        end = found[i + 1][0] if i + 1 < len(found) else len(body)
        chunk = body[idx + len(name):end].strip()
        out[SECTION_KEYS[name]] = TAIL_JUNK.sub("", chunk).strip() if name == SECTIONS[-1] else chunk
    return out, (found[0][0] if found else len(body))


def parse_pdf(path: Path) -> dict | None:
    raw = read_pdf_text(path)
    if CHROME_END not in raw:
        return None
    name = re.split(r"Are\s+you\s+sure", raw)[0].strip().replace("\n", " ")
    body = raw.split(CHROME_END, 1)[1]
    body_flat = re.sub(r"\s*\n\s*", " ", body)
    sections, first_idx = _split_sections(body_flat)
    header = body_flat[:first_idx].strip()  # "<State?><Name><Tag><Tag>..."
    state = next((s for s in STATES_BY_LEN if header.startswith(s)), None)
    rest = header[len(state):] if state else header
    if rest.startswith(name):
        rest = rest[len(name):]
    name_words = {w.lower() for w in re.findall(r"\w+", name)}
    tags = [t for t in re.findall(r"[A-Z][a-z]+(?: [a-z]+)*|[A-Z]{2,}", rest)
            if t.lower() not in name_words and not t.startswith("Ministry")][:8]
    slug = path.stem
    return {
        "slug": slug,
        "name": name,
        "level": "state" if state else "central",
        "state": state,
        "tags": sorted({t.lower() for t in tags}),
        "sections": sections,
        "source_url": f"https://www.myscheme.gov.in/schemes/{re.sub(r'\(\d+\)$', '', slug)}",
        "source_hash": "sha256:" + hashlib.sha256(raw.encode()).hexdigest(),
    }


def parse_all(folder: Path) -> list[dict]:
    docs, seen = [], set()
    for pdf in sorted(folder.glob("*.pdf")):
        try:
            doc = parse_pdf(pdf)
        except Exception as exc:  # corrupt PDF: skip, it is logged by the caller
            print(f"skip {pdf.name}: {exc}")
            continue
        # The dataset contains a few "(1)" re-downloads of the same page.
        if doc and doc["source_hash"] not in seen and doc["sections"].get("eligibility"):
            seen.add(doc["source_hash"])
            docs.append(doc)
    return docs
