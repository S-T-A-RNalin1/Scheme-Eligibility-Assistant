"""Section-based chunking: one scheme section -> one or more ~120-350 word chunks with overlap."""
from ..ingest.extract import sentences

SECTION_TITLES = {"description": "Details", "benefits": "Benefits", "eligibility": "Eligibility",
                  "exclusions": "Exclusions", "application": "Application Process",
                  "documents": "Documents Required", "faq": "FAQ"}
MAX_WORDS, OVERLAP_SENTENCES = 350, 1


def chunk_scheme(scheme: dict) -> list[dict]:
    chunks, idx = [], 0
    for key, title in SECTION_TITLES.items():
        text = scheme["sections"].get(key)
        if not text or len(text) < 20:
            continue
        sents, buf = sentences(text), []
        for s in sents + [None]:
            if s is not None and sum(len(x.split()) for x in buf) + len(s.split()) <= MAX_WORDS:
                buf.append(s)
                continue
            if buf:
                body = " ".join(buf)
                chunks.append({
                    "scheme_slug": scheme["slug"], "scheme_name": scheme["name"], "section": title,
                    "chunk_index": idx, "text": body,
                    # The context prefix makes an isolated chunk meaningful to the embedder.
                    "embed_text": f"{scheme['name']} — {title}: {body}",
                    "source_url": scheme["source_url"], "level": scheme["level"], "state": scheme.get("state"),
                    "tags": scheme.get("tags", []), "language": "en",
                })
                idx += 1
                buf = buf[-OVERLAP_SENTENCES:] if s is not None else []
            if s is not None:
                buf.append(s)
    return chunks
