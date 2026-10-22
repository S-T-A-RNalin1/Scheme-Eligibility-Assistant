"""Rule extraction: propose a rule tree from a scheme's Eligibility / Exclusions prose.

This is the "proposer" stage of ingestion. It is deliberately conservative:
every leaf carries the exact sentence it came from (`source_quote`), and any
eligibility sentence it cannot express goes into `unmapped_conditions` so a
human reviewer sees it. Nothing proposed here is published without review.
(An LLM with JSON-schema output can replace this module behind the same
interface; the validator and review gate stay the same.)
"""
import re

from ..engine.attributes import STATES

EXTRACTOR_VERSION = "regex-extract@1.0"

NUM = r"(\d{1,3}(?:,\d{2,3})*(?:\.\d+)?|\d+(?:\.\d+)?)"
MONEY = rf"(?:₹|rs\.?|inr|rupees)\s*{NUM}\s*(lakh|lakhs|crore)?"


def sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text or "")
    # Protect abbreviations ("Rs. 50 lakh", "Ph.D.") from being treated as sentence ends.
    text = re.sub(r"\b(Rs|No|Ph|Dr|Sr|Smt|Shri|viz|i\.e|e\.g)\.\s*", lambda m: m.group(1) + "․ ", text, flags=re.I)
    parts = re.split(r"(?<=[.;:])(?!\d)\s*(?=[A-Z0-9(])|(?<=[a-z0-9)])(?=\d+\.\s?[A-Z])", text)
    parts = [p.replace("․ ", ". ").replace("․", ".") for p in parts]
    return [p.strip() for p in parts if len(p.strip()) > 3]


def _money(num: str, unit: str | None) -> float:
    n = float(num.replace(",", ""))
    if unit and unit.startswith("lakh"):
        n *= 100000
    elif unit == "crore":
        n *= 10000000
    return n


class _Builder:
    def __init__(self):
        self.leaves, self.used, self.n = [], set(), 0

    def add(self, attr, op, value, desc, quote, negate=False):
        if any(l["attribute"] == attr and not l.get("_neg") == negate for l in self.leaves):
            return  # one rule per attribute keeps proposals simple to review
        self.n += 1
        leaf = {"id": f"r{self.n}", "attribute": attr, "operator": op, "value": value,
                "description": desc, "source_quote": quote}
        if negate:
            leaf["_neg"] = True
        self.leaves.append(leaf)
        self.used.add(quote)


def _age(s, b):
    low = s.lower()
    if "age" not in low and "years" not in low:
        return
    if not re.search(r"\bage|aged|years of age|years old", low):
        return
    m = (re.search(rf"between (?:the )?(?:age[s]? (?:of |group of )?)?{NUM}\s*(?:years)?\s*(?:and|to|-|–)\s*{NUM}\s*years", low)
         or re.search(rf"age group (?:of )?{NUM}\s*(?:-|–|to)\s*{NUM}", low)
         or re.search(rf"minimum age[^.]*?{NUM} years and maximum[^.]*?{NUM}", low)
         or re.search(rf"{NUM}\s*(?:-|–|to)\s*{NUM} years", low))
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        if lo < hi <= 120:
            b.add("age", "between", [lo, hi], f"Age between {lo:g} and {hi:g} years", s)
        return
    m = re.search(rf"(?:above|at least|minimum(?: age)?(?: of)?|not less than|completed)\s*{NUM}\s*years", low) \
        or re.search(rf"{NUM}\s*years (?:of age )?(?:or|and) (?:above|more|older)", low)
    if m:
        b.add("age", ">=", float(m.group(1)), f"Age at least {float(m.group(1)):g} years", s)
        return
    m = re.search(rf"(?:below|under|not more than|less than|maximum(?: age)?(?: of)?|not exceed(?:ing)?|up to|upto)\s*{NUM}\s*years", low)
    if m and "age" in low:
        b.add("age", "<=", float(m.group(1)), f"Age at most {float(m.group(1)):g} years", s)


def _income(s, b):
    low = s.lower()
    if "income" not in low:
        return
    if re.search(r"no income (ceiling|limit)", low):
        return
    m = re.search(rf"(?:not exceed(?:ing)?|less than|below|up ?to|upto|not more than|should not be greater than|within|maximum of|does not exceed|or less)[^.]{{0,25}}?{MONEY}", low) \
        or re.search(rf"{MONEY}[^.]{{0,15}}(?:or less|and below|per annum or below)", low)
    if m:
        amount = _money(m.group(1), m.group(2))
        if 1000 <= amount <= 100000000:
            b.add("annual_income", "<=", amount, f"Annual family income up to ₹{amount:,.0f}", s)


def _category(s, b):
    low = s.lower()
    if not re.search(r"belong|from (?:a |the )?(?:scheduled|sc|st|obc)|category|caste|tribe|community", low):
        return
    if "other than schedule" in low or "general category" in low:
        b.add("category", "in", ["General", "EWS"], "General category (not SC/ST/OBC)", s)
        return
    cats = []
    if re.search(r"scheduled castes?|\bsc\b|\bscs\b", low):
        cats.append("SC")
    if re.search(r"scheduled tribes?|\bst\b|\bsts\b", low):
        cats.append("ST")
    if re.search(r"\bobcs?\b|other backward class", low):
        cats.append("OBC")
    if re.search(r"\bews\b|economically weaker", low):
        cats.append("EWS")
    if cats and re.search(r"must|should|only|eligible|belong|for (?:the )?(?:students|entrepreneurs|persons)", low):
        b.add("category", "in", cats, "Category: " + " / ".join(cats), s)


def _gender(s, b):
    low = s.lower()
    if re.search(r"(?:applicant|beneficiar(?:y|ies)|candidate|student)s?\b[^.]{0,30}(?:must|should|shall) be (?:a |an )?(?:woman|women|girl|female|widow)", low) \
            or re.search(r"^(?:only )?(?:women|girls|widows|female)\b", low) or re.search(r"applicable (?:only )?to women", low) \
            or re.search(r"(?:only|exclusively) for (?:women|girls|female)", low):
        b.add("gender", "==", "female", "Women / girls only", s)


def _flags(s, b, state):
    low = s.lower()
    if re.search(r"citizen of india|indian (?:citizen|national)|indian citizenship", low):
        b.add("is_citizen", "==", True, "Must be an Indian citizen", s)
    if re.search(r"below (?:the )?poverty line|\bbpl\b", low) and re.search(r"must|should|belong|eligible|household", low):
        b.add("is_bpl", "==", True, "Household must be Below Poverty Line", s)
    m = re.search(rf"(?:disabilit(?:y|ies)|handicap)[^.]{{0,60}}?{NUM}\s*%|{NUM}\s*%[^.]{{0,40}}disabilit", low)
    if m:
        pct = float(m.group(1) or m.group(2))
        b.add("disability_percent", ">=", pct, f"Disability of at least {pct:g}%", s)
    elif re.search(r"(?:must|should) be (?:a )?(?:person with disabilit|divyang|differently abled|pwd)", low):
        b.add("has_disability", "==", True, "Must be a person with disability", s)
    m = re.search(rf"(?:at least|minimum(?: of)?|not less than|secured)\s*{NUM}\s*%\s*(?:marks|aggregate)", low)
    if m:
        b.add("marks_percent", ">=", float(m.group(1)), f"At least {float(m.group(1)):g}% marks", s)
    if re.search(r"(?:must|should) be (?:a )?(?:regular |bonafide )?student|currently studying|pursuing (?:a |their )?(?:regular )?(?:course|studies|education|degree)", low):
        b.add("is_student", "==", True, "Must be a student", s)
    if re.search(r"(?:must|should) be (?:a |an )?(?:small |marginal )?farmer|farmers? (?:are|is) eligible|applicable to farmers", low):
        b.add("occupation", "in", ["farmer"], "Must be a farmer", s)
    m = re.search(rf"(?:up ?to|less than|not more than|maximum of|below)\s*{NUM}\s*(hectares?|ha\b|acres?)", low)
    if m and "land" in low:
        v = float(m.group(1)) * (0.4047 if m.group(2).startswith("acre") else 1)
        b.add("land_holding_hectares", "<=", round(v, 3), f"Land holding up to {m.group(1)} {m.group(2)}", s)
    if state and re.search(r"resident|domicile|native|permanently settled|belong to the state", low):
        b.add("state", "==", state, f"Must be a resident of {state}", s)
    if re.search(r"(?:must|should) (?:be )?resid\w* in (?:a )?rural|rural (?:area|household|youth|poor)", low):
        b.add("area_type", "==", "rural", "Must live in a rural area", s)


def _exclusions(text, b):
    for s in sentences(text):
        low = s.lower()
        if re.search(r"income[- ]?tax payer|paying income tax|pays income tax", low):
            b.add("is_income_tax_payer", "==", True, "Income-tax payers are excluded", s, negate=True)


REQUIREMENT = re.compile(r"\b(must|should|shall|eligible|only|required|not be)\b", re.I)


def propose(scheme: dict) -> dict:
    """Return {eligibility, unmapped_conditions, extracted_by} for a parsed scheme."""
    sec = scheme["sections"]
    b = _Builder()
    elig_sents = sentences(sec.get("eligibility", ""))
    for s in elig_sents:
        for fn in (_age, _income, _category, _gender):
            fn(s, b)
        _flags(s, b, scheme.get("state"))
    _exclusions(sec.get("exclusions", ""), b)
    if scheme.get("state") and not any(l["attribute"] == "state" for l in b.leaves):
        # State schemes are for residents of that state; the pre-filter relies on it too.
        b.add("state", "==", scheme["state"], f"Scheme of {scheme['state']} (state residents)",
              None)  # derived from scheme metadata, not from a sentence
    children = []
    for leaf in b.leaves:
        neg = leaf.pop("_neg", False)
        children.append({"op": "NOT", "children": [leaf]} if neg else leaf)
    unmapped = [s for s in elig_sents if s not in b.used and REQUIREMENT.search(s)][:12]
    return {"eligibility": {"op": "AND", "children": children},
            "unmapped_conditions": unmapped, "extracted_by": EXTRACTOR_VERSION}
