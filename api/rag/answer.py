"""Question routing and grounded answer generation.

The LLM (optional) only ever narrates: eligibility verdicts come from the rules
engine, facts come from retrieved chunks, and every answer is citation-checked
in code. Without an API key an extractive composer builds the answer from the
best-matching source sentences, so the system works fully offline.
"""
import json
import re

from .. import config
from ..ingest.extract import sentences
from ..services import run_check
from .retrieve import hybrid_search

REFUSAL = "I don't have reliable information on that. Please check myscheme.gov.in."
OFF_TOPIC = ("I can only help with Indian government schemes — eligibility, benefits, documents "
             "and how to apply. Please ask about a scheme.")

ELIGIBILITY_PAT = re.compile(r"\b(am i|are we|is my|can i|could i|do i)\b.*\b(eligible|qualify|apply|get)\b|\beligib", re.I)
DISCOVERY_PAT = re.compile(r"\b(which|what|list|any|suggest|find|show)\b.*\bschemes?\b|\bschemes? (for|to help)\b", re.I)
DOMAIN_WORDS = re.compile(r"scheme|yojana|scholar|pension|subsid|loan|benefit|eligib|apply|document|insurance|grant|"
                          r"farmer|student|women|girl|disab|income|bpl|caste|tribe|obc|allowance|assistance|welfare|"
                          r"fellowship|stipend|certificate|portal|ministry|government|govt|kisan|mission|housing|aadhaar|"
                          r"ration|widow|pregnan|maternity|health|hospital|treatment|skill|training|job|employment|"
                          r"entrepreneur|business|startup|artisan|weaver|fisher|labour|worker|senior|elderly|child|"
                          r"orphan|minority|\bsc\b|\bst\b|\bews\b|land|crop|irrigation|house|toilet|electric", re.I)
# Common spellings people type, mapped to the spelling used in scheme text.
SPELLING = {"yojna": "yojana", "yojona": "yojana", "yojanaa": "yojana", "yozana": "yojana", "aadhar": "aadhaar",
            "adhar": "aadhaar", "adhaar": "aadhaar", "scholership": "scholarship", "scolarship": "scholarship",
            "scholarshp": "scholarship", "penshion": "pension", "pention": "pension", "kisaan": "kisan",
            "subsidey": "subsidy", "subsidi": "subsidy", "documants": "documents", "documnets": "documents",
            "elegible": "eligible", "eligable": "eligible", "insurence": "insurance"}
# Words too general to identify what a question is about.
GENERIC = {"scheme", "schemes", "yojana", "government", "govt", "india", "indian", "central", "state", "details",
           "information", "info", "know", "want", "need", "needed", "get", "give", "list", "about", "regarding",
           "help", "helps", "support", "provide", "provides", "available", "offer", "offers", "people", "person"}
# Words that say *which part* of a scheme is wanted, not which scheme; ignored when judging relevance.
SECTION_WORDS = {"document", "required", "require", "apply", "application", "applying", "process", "procedure",
                 "benefit", "eligibility", "eligible", "criterion", "criteria", "amount", "much", "detail", "exclusion",
                 "need", "needed", "step", "how", "who", "can", "qualify"}
SECTION_HINTS = [(r"\bdocument|papers?\b|certificate", "Documents Required"), (r"\bhow (do|to|can)\b.*\bapply|application|apply", "Application Process"),
                 (r"\bbenefit|how much|amount|assistance", "Benefits"), (r"\bexclu|not eligible|who cannot", "Exclusions"),
                 (r"\beligib|criteria|who can", "Eligibility")]
STOP = set("a an the of for to in on and or is are am i my me we our what which how do does can could be with by from "
           "this that it as at any there their about under scheme schemes yojana please tell".split())

SYSTEM_PROMPT = """You help Indian citizens understand government schemes.
Answer ONLY using the numbered sources provided by the user message.
After every factual sentence, cite its source like [2].
If the sources do not contain the answer, reply exactly:
"I don't have reliable information on that. Please check myscheme.gov.in."
Never state that the user is or is not eligible — eligibility comes only from the
ELIGIBILITY RESULTS block when it is provided; you may restate those verdicts and reasons.
Keep amounts, dates and limits exactly as written in the sources. Be concise (under 150 words)."""


def normalize(question: str) -> str:
    return re.sub(r"[A-Za-z]+", lambda m: SPELLING.get(m.group().lower(), m.group()), question)


def classify(question: str, names_hit: bool = False) -> str:
    if not DOMAIN_WORDS.search(question) and not names_hit:
        return "off_topic"
    # "How do I apply ..." asks for the application process, not for an eligibility verdict.
    if ELIGIBILITY_PAT.search(question) and not re.search(r"\bhow\b", question, re.I):
        return "eligibility"
    if DISCOVERY_PAT.search(question):
        return "discovery"
    return "information"


def _stem(w: str) -> str:
    """Tiny English stemmer so plurals match: fishermen -> fisherman, schemes -> scheme, subsidies -> subsidy."""
    if w.endswith("men") and len(w) > 4:
        return w[:-3] + "man"
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith(("ches", "shes", "sses", "xes")) and len(w) > 4:
        return w[:-2]
    if w.endswith("s") and not w.endswith(("ss", "us", "is")) and len(w) > 3:
        return w[:-1]
    return w


def _terms(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP and len(w) > 2}


def core_terms(question: str) -> set[str]:
    """The words that say what the question is about (stop words and generic words removed)."""
    return _terms(question) - {_stem(g) for g in GENERIC}


def topic_terms(question: str) -> set[str]:
    """Core terms minus section words ("documents", "apply"): what must appear in a relevant passage."""
    core = core_terms(question)
    return (core - {_stem(w) for w in SECTION_WORDS}) or core


def name_matches(db, question: str, limit: int = 6) -> list[dict]:
    """Schemes whose *name* contains the question's words, best overlap first."""
    q = topic_terms(question)
    if not q:
        return []
    found = list(db.schemes.find({"$text": {"$search": " ".join(sorted(q))}, "status": {"$ne": "retired"}},
                                 {"score": {"$meta": "textScore"}, "slug": 1, "name": 1, "status": 1})
                 .sort([("score", {"$meta": "textScore"})]).limit(40))
    for f in found:
        f["overlap"] = len(_terms(f["name"]) & q)
    found = [f for f in found if f["overlap"]]
    found.sort(key=lambda f: (-f["overlap"], -f["score"]))
    return found[:limit]


def coverage(q: set[str], text: str) -> float:
    return len(q & _terms(text)) / len(q) if q else 1.0


def needed_coverage(q: set[str]) -> float:
    # Short questions must be matched completely; longer ones need most of their words.
    return 1.0 if len(q) <= 2 else 0.75 if len(q) <= 4 else 0.5


def _first_sentence(text: str) -> str:
    sents = sentences(text)
    return (sents[0] if sents else text)[:260].rstrip(".") + "."


def _scheme_sources(db, schemes: list[dict]) -> list[dict]:
    """One 'Details' chunk per scheme, numbered as citation sources."""
    out = []
    proj = {"embedding": 0, "embed_text": 0}
    for s in schemes:
        ch = (db.document_chunks.find_one({"scheme_slug": s["slug"], "section": "Details"}, proj, sort=[("chunk_index", 1)])
              or db.document_chunks.find_one({"scheme_slug": s["slug"]}, proj, sort=[("chunk_index", 1)]))
        if ch:
            out.append({"n": 1 + len(out), "scheme_slug": ch["scheme_slug"], "scheme_name": ch["scheme_name"],
                        "section": ch["section"], "source_url": ch["source_url"], "text": ch["text"]})
    return out


def _public(sources):
    return [{k: s[k] for k in ("n", "scheme_slug", "scheme_name", "section", "source_url")} for s in sources]


def match_scheme(db, question: str):
    """Find a scheme named in the question (by slug/acronym or a strong name text match)."""
    words = set(re.findall(r"[a-z0-9\-()]+", question.lower()))
    hit = db.schemes.find_one({"slug": {"$in": list(words)}}, {"slug": 1, "name": 1, "status": 1})
    if hit:
        return hit
    res = list(db.schemes.find({"$text": {"$search": question}}, {"score": {"$meta": "textScore"}, "slug": 1, "name": 1, "status": 1})
               .sort([("score", {"$meta": "textScore"})]).limit(1))
    if res and len(_terms(res[0]["name"]) & _terms(question)) >= 2:
        return res[0]
    return None


def _extractive(question: str, sources: list[dict], want: str | None = None, max_sentences: int = 4) -> str:
    q = core_terms(question) or _terms(question)
    scored = []
    for src in sources:
        n = src["n"]
        in_section = want is not None and src["section"] == want
        for sent in sentences(src["text"]):
            overlap = len(q & _terms(sent))
            if overlap or in_section:
                scored.append((overlap + (0.5 if n <= 2 else 0) + (3 if in_section else 0) - 0.01 * len(scored), n, sent))
    scored.sort(key=lambda t: -t[0])
    picked, seen = [], set()
    for _, n, sent in scored:
        key = sent[:60]
        if key in seen:
            continue
        seen.add(key)
        picked.append(f"{sent.rstrip('.')}. [{n}]")
        if len(picked) >= max_sentences:
            break
    return " ".join(picked)


def _llm(question: str, sources: list[dict], eligibility_block: str | None) -> str | None:
    if not config.ANTHROPIC_API_KEY:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        src = "\n".join(f"[{i}] ({s['scheme_name']} · {s['section']}) {s['text']}" for i, s in enumerate(sources, 1))
        user = f"SOURCES:\n{src}\n\n" + (f"ELIGIBILITY RESULTS:\n{eligibility_block}\n\n" if eligibility_block else "") + f"QUESTION: {question}"
        msg = client.messages.create(model=config.LLM_MODEL, max_tokens=1024, system=SYSTEM_PROMPT,
                                     output_config={"effort": "low"},
                                     messages=[{"role": "user", "content": user}])
        if msg.stop_reason == "refusal":
            return None
        return "".join(b.text for b in msg.content if b.type == "text").strip()
    except Exception:
        return None  # any API problem: fall back to the extractive composer


def validate_citations(answer: str, n_sources: int) -> str:
    """Every [n] must point to a supplied source; an answer with no valid citation becomes the refusal."""
    if answer.strip() == REFUSAL:
        return REFUSAL
    cited = [int(c) for c in re.findall(r"\[(\d+)\]", answer)]
    if not cited or any(c < 1 or c > n_sources for c in cited):
        return REFUSAL
    return answer


def _verdict_text(r: dict) -> str:
    label = {"ELIGIBLE": "you appear ELIGIBLE", "INELIGIBLE": "you are NOT eligible",
             "NEEDS_MORE_INFO": "we need more information"}[r["verdict"]]
    lines = [f"Based on the published rules (version {r['scheme_version']}) for {r['name']}, {label}."]
    for reason in r["reasons"]:
        mark = {"PASS": "✔", "FAIL": "✘", "UNKNOWN": "?"}[reason["result"]]
        lines.append(f"{mark} {reason['detail']}")
    if r["missing_attributes"]:
        lines.append("Please tell us: " + ", ".join(a.replace("_", " ") for a in r["missing_attributes"]) + ".")
    if r.get("unmapped_conditions"):
        lines.append("Also check (not machine-verified): " + "; ".join(r["unmapped_conditions"]))
    return "\n".join(lines)


def answer(db, question: str, profile: dict | None = None, mode: str = "hybrid") -> dict:
    profile = profile or {}
    question = normalize(question)
    q_core = topic_terms(question)
    names = name_matches(db, question)
    route = classify(question, names_hit=bool(names))
    if route == "off_topic":
        return {"route": route, "answer": OFF_TOPIC, "citations": [], "eligibility": []}

    # Short "topic" questions that name schemes ("atal yojana", "pm kisan"): list the matching schemes.
    full_name_hits = [n for n in names if n["overlap"] == len(q_core)]
    if (route == "information" and q_core and len(q_core) <= 3 and full_name_hits
            and not re.search(r"\?|\bhow\b|\bwhat\b|\bwhich\b|\bwho\b", question, re.I)):
        sources = _scheme_sources(db, full_name_hits[:5])
        if sources:
            lines = [f"Schemes matching \u201c{' '.join(sorted(q_core))}\u201d in our data:"]
            lines += [f"\u2022 {s['scheme_name']} \u2014 {_first_sentence(s['text'])} [{s['n']}]" for s in sources]
            lines.append("Ask about one of them (for example its benefits, documents or eligibility) for details.")
            return {"route": "overview", "answer": "\n".join(lines), "citations": _public(sources), "eligibility": [],
                    "sources": _public(sources)}

    state = profile.get("state")
    eligibility, elig_block, focus = [], None, None
    if route == "eligibility":
        focus = match_scheme(db, question)
        if focus and focus.get("status") == "published":
            res = run_check(db, profile, slugs=[focus["slug"]])
            eligibility = res["eligible"] + res["needs_more_info"] + res["ineligible"]
        elif focus:
            route = "information"  # scheme found but its rules are not reviewed yet
        else:
            route = "discovery"
    elif route == "information":
        focus = match_scheme(db, question)

    query = question if not focus else f"{focus['name']} {question}"
    chunks, signal = hybrid_search(db, query, state=state, top_k=12, mode=mode)
    if focus:
        chunks = sorted(chunks, key=lambda c: c["scheme_slug"] != focus["slug"])
    want = next((sec for pat, sec in SECTION_HINTS if re.search(pat, question, re.I)), None)

    # Keep only pieces of text that really talk about what was asked. Coverage is measured per
    # piece (its text plus its scheme name), not over all results together.
    if not focus:
        need = needed_coverage(q_core)
        chunks = [c for c in chunks if coverage(q_core, c["text"] + " " + c["scheme_name"]) >= need]
    if want and chunks:
        # The question names a section ("documents", "how to apply"): put that section of the top scheme first.
        top = focus["slug"] if focus else chunks[0]["scheme_slug"]
        extra = list(db.document_chunks.find({"scheme_slug": top, "section": want}, {"embedding": 0, "embed_text": 0}).limit(2))
        ids = {c["_id"] for c in extra}
        chunks = extra + [c for c in chunks if c["_id"] not in ids]
    chunks = chunks[:6]

    if not chunks:
        # Nothing in our data is about this. Say so, and point to schemes whose names share a word with the question.
        related = [n for n in names if n["overlap"] / max(len(q_core), 1) >= 0.5][:4]
        if related:
            sources = _scheme_sources(db, related)
            lines = [f"I couldn't find a scheme about \u201c{' '.join(sorted(q_core))}\u201d in our data. "
                     "Related schemes that share a word with your question:"]
            lines += [f"\u2022 {s['scheme_name']} [{s['n']}]" for s in sources]
            lines.append("Please check myscheme.gov.in for the full list of schemes.")
            return {"route": route, "answer": "\n".join(lines), "citations": _public(sources), "eligibility": eligibility,
                    "sources": _public(sources)}
        return {"route": route, "answer": REFUSAL, "citations": [], "eligibility": eligibility}

    if route == "discovery":
        slugs = list(dict.fromkeys(c["scheme_slug"] for c in chunks))
        res = run_check(db, profile, slugs=slugs)
        eligibility = res["eligible"] + res["needs_more_info"] + res["ineligible"]

    sources = [{"n": i, "scheme_slug": c["scheme_slug"], "scheme_name": c["scheme_name"], "section": c["section"],
                "source_url": c["source_url"], "text": c["text"]} for i, c in enumerate(chunks, 1)]
    if signal["keyword_hits"] == 0 and signal["best_vector_score"] < 0.35 and not focus:
        return {"route": route, "answer": REFUSAL, "citations": [], "eligibility": eligibility}

    if eligibility:
        elig_block = json.dumps([{k: r[k] for k in ("slug", "name", "verdict", "reasons", "missing_attributes")} for r in eligibility],
                                ensure_ascii=False)
    text = _llm(question, sources, elig_block) or _extractive(question, sources, want)
    text = validate_citations(text, len(sources))
    if route == "eligibility" and eligibility:
        text = _verdict_text(eligibility[0]) + ("\n\n" + text if text != REFUSAL else "")
    elif route == "discovery" and eligibility:
        ok = [r["name"] for r in eligibility if r["verdict"] == "ELIGIBLE"]
        maybe = [r["name"] for r in eligibility if r["verdict"] == "NEEDS_MORE_INFO"]
        head = []
        if ok:
            head.append("Schemes you appear eligible for (rules engine): " + "; ".join(ok) + ".")
        if maybe:
            head.append("Need more information for: " + "; ".join(maybe) + ".")
        if head:
            text = "\n".join(head) + ("\n\n" + text if text != REFUSAL else "")
    used = {int(n) for n in re.findall(r"\[(\d+)\]", text)}
    citations = [c for c in _public(sources) if c["n"] in used]
    return {"route": route, "answer": text, "citations": citations, "eligibility": eligibility, "sources": _public(sources)}
