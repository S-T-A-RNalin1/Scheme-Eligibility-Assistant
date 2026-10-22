"""Generate demo search traffic for the coverage-gap dashboard.

Real deployments collect demand from users' Ask questions and scheme searches. A fresh
demo database has almost none, so this script inserts realistic searches, each flagged
`demo: true` (the dashboard shows how many are simulated). The number of matching schemes
for every search is computed against the real scheme data, so supply is never invented.

    python scripts/simulate_searches.py            # add ~900 demo searches
    python scripts/simulate_searches.py --clear    # remove all demo searches
"""
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).absolute().parent.parent))

from api import analytics  # noqa: E402
from api.db import get_db  # noqa: E402

# Rough population (millions) by state / UT; square-rooted so large states don't drown out the rest.
POP = {"Uttar Pradesh": 240, "Maharashtra": 125, "Bihar": 125, "West Bengal": 100, "Madhya Pradesh": 85, "Rajasthan": 80,
       "Tamil Nadu": 77, "Gujarat": 70, "Karnataka": 68, "Andhra Pradesh": 53, "Odisha": 46, "Jharkhand": 39, "Telangana": 38,
       "Assam": 35, "Kerala": 35, "Punjab": 30, "Chhattisgarh": 30, "Haryana": 29, "Delhi": 21, "Jammu and Kashmir": 13,
       "Uttarakhand": 11, "Himachal Pradesh": 7.5, "Tripura": 4, "Meghalaya": 3.3, "Manipur": 3.2, "Nagaland": 2.2, "Goa": 1.6,
       "Arunachal Pradesh": 1.6, "Puducherry": 1.6, "Mizoram": 1.2, "Chandigarh": 1.2, "Sikkim": 0.7,
       "Dadra and Nagar Haveli and Daman and Diu": 0.6, "Andaman and Nicobar Islands": 0.4, "Ladakh": 0.3, "Lakshadweep": 0.07}

QUERIES = [
    "pension for widows", "old age pension", "pension for senior citizens", "scholarship for girls",
    "scholarship for SC students", "post matric scholarship OBC", "loan for women entrepreneurs", "subsidy for small business",
    "crop insurance for farmers", "drip irrigation subsidy", "dairy farming loan", "fishermen assistance",
    "assistance for disabled persons", "wheelchair for disabled", "housing for poor families", "toilet construction subsidy",
    "skill training for unemployed youth", "job training scheme", "maternity benefit for pregnant women", "help for orphan children",
    "construction workers welfare", "pension for unorganised workers", "street vendor loan", "handloom weaver support",
    "minority students scholarship", "tribal welfare scheme", "free coaching for competitive exams", "startup funding",
    "education loan for abroad", "marriage assistance for daughters", "free gas connection", "health insurance for poor",
    "treatment for serious disease", "bicycle for school girls", "laptop for students", "tractor subsidy",
    "solar pump for farmers", "goat rearing scheme", "sericulture support", "transgender welfare",
]


_SCHEME_TERMS = None


def match_count(db, q: str, state: str) -> int:
    """Schemes (central + the user's state) that contain the search's topic words, using the same
    stemmed relevance rule as the Ask section, so 'matching' means the same thing everywhere."""
    global _SCHEME_TERMS
    from api.rag.answer import _terms, needed_coverage, topic_terms
    if _SCHEME_TERMS is None:
        _SCHEME_TERMS = []
        for sc in db.schemes.find({"status": {"$ne": "retired"}}, {"name": 1, "tags": 1, "level": 1, "state": 1,
                                                                   "sections.description": 1, "sections.eligibility": 1}):
            sec = sc.get("sections") or {}
            text = " ".join([sc["name"], " ".join(sc.get("tags", [])), sec.get("description", ""), sec.get("eligibility", "")])
            _SCHEME_TERMS.append((sc["level"], sc.get("state"), _terms(text)))
    terms = topic_terms(q)
    if not terms:
        return 0
    need = needed_coverage(terms)
    return sum(1 for level, st, t in _SCHEME_TERMS
               if (level == "central" or st == state) and len(terms & t) / len(terms) >= need)


def main():
    db = get_db()
    analytics.ensure_indexes(db)
    if "--clear" in sys.argv:
        print("removed", db.search_logs.delete_many({"demo": True}).deleted_count, "demo searches")
        return
    random.seed(11)
    states = list(POP)
    weights = [math.sqrt(POP[s]) for s in states]
    cache, n = {}, 0
    for _ in range(900):
        state = random.choices(states, weights)[0]
        q = random.choice(QUERIES)
        key = (q, state)
        if key not in cache:
            cache[key] = match_count(db, q, state)
        analytics.log_search(db, q, random.choice(["ask", "ask", "browse"]), cache[key], state=state, demo=True)
        n += 1
    print(f"inserted {n} demo searches across {len(states)} regions")


if __name__ == "__main__":
    main()
