"""Measure the numbers quoted in the report and slides; writes docs/results.json.

  - pytest results
  - rules-engine fixture accuracy
  - eligibility-check latency over all published schemes (incl. audit write)
  - index benchmarks with explain("executionStats"), with vs. without index ($natural hint)
  - retrieval evaluation (Recall@5, MRR) for vector / keyword / hybrid, and refusal rate
"""
import json
import random
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).absolute().parent.parent
sys.path.insert(0, str(ROOT))

from bson import ObjectId  # noqa: E402

from api.db import get_db  # noqa: E402
from api.engine.evaluate import check  # noqa: E402
from api.rag.answer import REFUSAL, OFF_TOPIC, answer  # noqa: E402
from api.rag.retrieve import hybrid_search  # noqa: E402
from api.services import run_check  # noqa: E402

random.seed(7)
db = get_db()
out = {}


def log(m):
    print(m, flush=True)


# ---------------------------------------------------------------- tests
p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:warnings"], cwd=ROOT, capture_output=True, text=True)
last = p.stdout.strip().splitlines()[-1]
m = re.search(r"(\d+) passed", last)
f = re.search(r"(\d+) failed", last)
sec = re.search(r"in ([\d.]+)s", last)
import pytest  # noqa: E402
out["tests"] = {"passed": int(m.group(1)) if m else 0, "failed": int(f.group(1)) if f else 0,
                "seconds": float(sec.group(1)) if sec else None, "pytest": pytest.__version__, "summary": last}
log(f"tests: {last}")

# ---------------------------------------------------------------- fixture accuracy
cur = json.loads((ROOT / "data" / "curated_rules.json").read_text(encoding="utf-8"))["schemes"]
fx = json.loads((ROOT / "tests" / "fixtures" / "profiles.json").read_text(encoding="utf-8"))
cases = [(s, c) for s, cs in fx.items() if not s.startswith("_") for c in cs]
ok = sum(check(cur[s]["eligibility"], c["profile"])["verdict"] == c["expected"] for s, c in cases)
out["fixture_accuracy"] = f"{100 * ok / len(cases):.0f}% ({ok}/{len(cases)})"
log(f"fixtures: {out['fixture_accuracy']}")

# ---------------------------------------------------------------- generate realistic load (audit log volume)
STATES = ["Assam", "Kerala", "Maharashtra", "Gujarat", "Bihar", "Punjab", None]
users = [ObjectId() for _ in range(60)]


def rand_profile():
    p = {"age": random.randint(14, 70), "state": random.choice(STATES)}
    for k, vals in (("gender", ["male", "female"]), ("category", ["General", "OBC", "SC", "ST", "EWS"]),
                    ("is_bpl", [True, False]), ("is_citizen", [True]), ("is_income_tax_payer", [True, False]),
                    ("area_type", ["rural", "urban"]), ("is_student", [True, False]),
                    ("occupation", ["farmer", "student", "entrepreneur", "weaver", "unemployed", "salaried"])):
        if random.random() < 0.7:
            p[k] = random.choice(vals)
    if random.random() < 0.6:
        p["annual_income"] = random.choice([50000, 90000, 140000, 240000, 450000, 900000, 1500000])
    return {k: v for k, v in p.items() if v is not None}


if db.evaluations.estimated_document_count() < 4000:
    for _ in range(320):
        run_check(db, rand_profile(), user_id=random.choice(users))
times = []
for _ in range(25):
    t = time.perf_counter()
    run_check(db, rand_profile(), user_id=random.choice(users))
    times.append((time.perf_counter() - t) * 1000)
n_pub = db.schemes.count_documents({"status": "published"})
out["check_ms"] = f"{statistics.median(times):.1f} ms"
out["published"] = n_pub
log(f"check latency median {out['check_ms']} over {n_pub} published schemes; evaluations={db.evaluations.estimated_document_count()}")

# ---------------------------------------------------------------- index benchmarks
def explain(coll, flt, sort=None, hint=None):
    cmd = {"find": coll, "filter": flt}
    if sort:
        cmd["sort"] = sort
    if hint:
        cmd["hint"] = hint
    e = db.command("explain", cmd, verbosity="executionStats")
    st = e["executionStats"]
    plan = e["queryPlanner"]["winningPlan"]
    stages = []
    while plan:
        stages.append(plan.get("stage"))
        plan = plan.get("inputStage") or (plan.get("inputStages") or [None])[0]
    return {"docs_examined": st["totalDocsExamined"], "keys_examined": st["totalKeysExamined"],
            "returned": st["nReturned"], "ms": st["executionTimeMillis"], "stage": " ← ".join(s for s in stages if s)}


sample_eval = db.evaluations.find_one({"user_id": {"$ne": None}})
queries = [
    ("Check pre-filter: published, central or Assam", "schemes",
     {"status": "published", "$or": [{"level": "central"}, {"state": "Assam"}]}, None),
    ("User history, newest first", "evaluations", {"user_id": sample_eval["user_id"]}, {"evaluated_at": -1}),
    ("All verdicts of one run", "evaluations", {"run_id": sample_eval["run_id"]}, None),
    ("Audits of one scheme version", "evaluations", {"scheme_slug": "apy", "scheme_version": 1}, None),
    ("Chunks of one scheme", "document_chunks", {"scheme_slug": "apy"}, None),
]
bench = []
for name, coll, flt, sort in queries:
    with_ix = explain(coll, flt, sort)
    no_ix = explain(coll, flt, sort, hint={"$natural": 1})
    bench.append({"query": name, "collection": coll, "with_index": with_ix, "no_index": no_ix})
    log(f"  {name}: {no_ix['docs_examined']} -> {with_ix['docs_examined']} docs; {with_ix['stage']}")
out["bench"] = bench
out["evaluations"] = db.evaluations.estimated_document_count()
out["chunks"] = db.document_chunks.estimated_document_count()

# ---------------------------------------------------------------- retrieval evaluation
schemes = list(db.schemes.find({}, {"slug": 1, "name": 1, "sections.description": 1, "sections.benefits": 1, "tags": 1}))
random.shuffle(schemes)
named, described = [], []
for s in schemes[:100]:
    named.append((random.choice(["What are the benefits of {}?", "Who is eligible for {}?", "How do I apply for {}?"]).format(s["name"]), s["slug"]))
    desc = (s.get("sections", {}).get("description") or "")
    name_words = {w.lower() for w in re.findall(r"\w+", s["name"])}
    sents = [x for x in re.split(r"(?<=[.!?])\s+", desc) if len(x.split()) > 8]
    if sents:
        words = [w for w in re.findall(r"[A-Za-z]+", sents[-1] if len(sents) > 1 else sents[0]) if w.lower() not in name_words][:14]
        described.append(("Is there a scheme that " + " ".join(words).lower() + "?", s["slug"]))


def score(qs, mode):
    rec, rr = 0, 0.0
    for q, slug in qs:
        chunks, _ = hybrid_search(db, q, top_k=5, mode=mode)
        slugs = list(dict.fromkeys(c["scheme_slug"] for c in chunks))
        if slug in slugs:
            rec += 1
            rr += 1 / (slugs.index(slug) + 1)
    return {"recall@5": rec / len(qs), "mrr": rr / len(qs)}


configs = {}
for mode in ("vector", "keyword", "hybrid"):
    a, b = score(named, mode), score(described, mode)
    configs[f"{mode} · named"] = a
    configs[f"{mode} · descriptive"] = b
    log(f"  {mode}: named R@5={a['recall@5']:.2f} MRR={a['mrr']:.2f} | descriptive R@5={b['recall@5']:.2f} MRR={b['mrr']:.2f}")

unanswerable = ["Who will win the next football world cup?", "What is the capital of France?",
                "Give me a recipe for biryani", "What is the subsidy for quantum teleportation of Martian cows?",
                "Is there a scheme for buying a private jet on Mars?", "Tell me a joke about cats",
                "What stock should I buy tomorrow?", "Scheme for interstellar dragon breeding licences",
                "How do I hack my neighbour's wifi?", "What is the weather in Delhi today?"]
refused = sum(answer(db, q)["answer"] in (REFUSAL, OFF_TOPIC) for q in unanswerable)
out["rag_eval"] = {"n": len(named) + len(described), "named": len(named), "descriptive": len(described),
                   "configs": configs, "refusal": f"{refused}/{len(unanswerable)}"}
out["rag_eval"]["headline"] = configs["hybrid · named"]  # headline number on the slide
log(f"refusal on unanswerable: {refused}/{len(unanswerable)}")

(ROOT / "docs" / "results.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
log("wrote docs/results.json")
