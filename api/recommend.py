"""Personalised recommendation ranking (content-based + a light "similar users" signal).

Candidates come from two tiers:
  * verified   — schemes with reviewer-approved rules, checked by the rules engine (as on the results page);
  * unverified — schemes still in review, pre-checked against their machine-read (validated) rule proposal.
    These are clearly labelled "rules not verified" and only shown when they fit the person's groups.

Ineligible schemes are never recommended. MongoDB then scores and sorts all candidates in one pipeline:

  score = 0.45 * rule_match * (0.5 + 0.5 * specificity)   conditions met, worth more when the rules target someone
        + 0.40 * group_match                              the person's groups the scheme is for ($setIntersection):
                                                          full credit if it's a primary group (title / tags / rules),
                                                          half credit if the scheme text only mentions it
        + 0.15 * popularity                               saves by users with a similar profile ($lookup)
  unverified candidates are multiplied by 0.85 (less certain).

`specificity` stops schemes whose only rules are generic (age, citizenship, state) from topping every list.
Every result carries its score parts and plain reasons.
"""
from .analytics import LABELS
from .engine.evaluate import check
from .services import run_check

W_RULE, W_GROUP, W_POP = 0.45, 0.40, 0.15
UNVERIFIED_FACTOR = 0.85
GENERIC_ATTRS = {"age", "is_citizen", "state"}
SIMILAR_FIELDS = ["state", "category", "occupation", "gender", "area_type"]
WORKER_OCC = {"agricultural_labourer", "artisan", "weaver", "fisherman", "construction_worker", "street_vendor",
              "unorganised_worker"}


def profile_groups(p: dict) -> list[str]:
    """Beneficiary groups a profile belongs to, from the same vocabulary used to tag schemes."""
    g, occ, age = set(), p.get("occupation"), p.get("age")
    if p.get("gender") == "female":
        g.add("women")
    if p.get("category") in ("SC", "ST"):
        g.add("sc_st")
    if p.get("category") == "OBC":
        g.add("obc")
    if p.get("is_minority"):
        g.add("minority")
    if p.get("is_student") or occ == "student":
        g.add("students")
    if occ in ("farmer", "agricultural_labourer", "fisherman") or (p.get("land_holding_hectares") or 0) > 0:
        g.add("farmers")
    if p.get("has_disability") or (p.get("disability_percent") or 0) > 0:
        g.add("disability")
    if age is not None and age >= 60:
        g.add("senior")
    if p.get("is_bpl") or (p.get("annual_income") is not None and p["annual_income"] <= 100000):
        g.add("poor")
    if occ in ("entrepreneur", "self_employed"):
        g.add("entrepreneurs")
    if occ in WORKER_OCC:
        g.add("workers")
    if age is not None and 15 <= age <= 35 and (occ in ("unemployed", "student") or p.get("is_student")):
        g.add("youth")
    if age is not None and age < 18:
        g.add("children")
    return sorted(g)


def similar_user_ids(db, profile: dict, exclude=None) -> list:
    """Users whose saved profile shares at least 2 of state / category / occupation / gender / area."""
    conds = [{"$cond": [{"$eq": [f"$attributes.{f}", profile[f]]}, 1, 0]} for f in SIMILAR_FIELDS if profile.get(f)]
    if len(conds) < 2:
        return []
    pipeline = [{"$match": {"user_id": {"$ne": exclude}}},
                {"$project": {"user_id": 1, "sim": {"$add": conds}}},
                {"$match": {"sim": {"$gte": 2}}}, {"$limit": 5000}]
    return [d["user_id"] for d in db.user_profiles.aggregate(pipeline)]


# Groups that say *who a scheme is for*. If every one of these on a scheme clearly doesn't fit the person,
# the scheme is aimed at someone else (e.g. student scholarships for a 67-year-old) and isn't recommended.
AUDIENCE = {"students", "children", "senior", "disability", "farmers", "women"}


def conflicts(group: str, p: dict) -> bool:
    age, occ = p.get("age"), p.get("occupation")
    if group == "students":
        return p.get("is_student") is False or (not p.get("is_student") and occ not in (None, "student") and age is not None and age > 30)
    if group == "children":
        return age is not None and age >= 18
    if group == "senior":
        return age is not None and age < 55
    if group == "disability":
        return p.get("has_disability") is False or (p.get("disability_percent") == 0 and not p.get("has_disability"))
    if group == "farmers":
        return occ is not None and occ not in ("farmer", "agricultural_labourer", "fisherman") and not (p.get("land_holding_hectares") or 0)
    if group == "women":
        return p.get("gender") in ("male",)
    return False


AGE_BASED = {"senior", "children"}  # an age band in a scheme's audience is a hard requirement on its own


def aimed_elsewhere(scheme_groups: list[str], p: dict) -> bool:
    audience = [g for g in scheme_groups if g in AUDIENCE]
    if any(g in AGE_BASED and conflicts(g, p) for g in audience):
        return True
    return bool(audience) and all(conflicts(g, p) for g in audience)


def _leaves(node):
    if not node:
        return []
    if "attribute" in node:
        return [node]
    return [x for c in node.get("children", []) for x in _leaves(c)]


def _stat(slug: str, tree: dict, res: dict, verified: bool, unchecked: int = 0) -> dict:
    """`unchecked` = requirements the extractor found in the text but could not turn into rules (unreviewed schemes);
    they count as conditions we can't confirm."""
    passed = sum(1 for x in res["reasons"] if x["result"] == "PASS")
    # Only conditions still open count against a scheme: failed alternatives inside a satisfied OR don't.
    unknown = sum(1 for x in res["reasons"] if x["result"] == "UNKNOWN" and x.get("attribute") in res["missing_attributes"]) + unchecked
    leaves = _leaves(tree)
    targeted = sum(1 for l in leaves if l["attribute"] not in GENERIC_ATTRS)
    return {"slug": slug, "verdict": res["verdict"], "verified": verified, "passed": passed, "unknown": unknown,
            "rule_match": 1.0 if res["verdict"] == "ELIGIBLE" and not unchecked else round(passed / max(passed + unknown, 1), 4),
            "unchecked": unchecked,
            "specificity": round(targeted / len(leaves), 4) if leaves else 0.0, "missing": res["missing_attributes"]}


def _unverified_candidates(db, profile: dict, groups: list[str], exclude: set[str]) -> list[dict]:
    """In-review schemes for this person's state (or central) whose validated, machine-read rules don't rule
    them out and whose beneficiary groups overlap the person's. Never used to say "eligible"."""
    if not groups:
        return []
    scope = {"status": "in_review", "beneficiary_groups": {"$in": groups}, "slug": {"$nin": list(exclude)}}
    scope["$or"] = [{"level": "central"}] + ([{"state": profile["state"]}] if profile.get("state") else [])
    slugs = [s["slug"] for s in db.schemes.find(scope, {"slug": 1})]
    jobs = db.ingestion_jobs.find({"scheme_slug": {"$in": slugs}, "validation_errors": {"$size": 0}},
                                  {"scheme_slug": 1, "proposed_eligibility": 1, "unmapped_conditions": 1})
    out = []
    for j in jobs:
        tree = j.get("proposed_eligibility")
        if not tree or not _leaves(tree):
            continue
        res = check(tree, profile)
        if res["verdict"] != "INELIGIBLE":
            out.append(_stat(j["scheme_slug"], tree, res, verified=False, unchecked=len(j.get("unmapped_conditions") or [])))
    return out


def recommend(db, profile: dict, user_id=None, limit: int = 8) -> dict:
    groups = profile_groups(profile)
    res = run_check(db, profile, user_id=user_id, write_audit=False)
    published = {s["slug"]: s["eligibility"] for s in db.schemes.find({"status": "published"}, {"slug": 1, "eligibility": 1})}
    stats = [_stat(r["slug"], published.get(r["slug"]), r, verified=True) for r in res["eligible"] + res["needs_more_info"]]
    stats += _unverified_candidates(db, profile, groups, exclude=set(published))
    meta = {d["slug"]: d for d in db.schemes.find({"slug": {"$in": [s["slug"] for s in stats]}},
                                                {"slug": 1, "level": 1, "beneficiary_groups": 1, "primary_groups": 1})}
    keep = []
    for st in stats:
        m = meta.get(st["slug"], {})
        primary, mentioned = set(m.get("primary_groups", [])), set(m.get("beneficiary_groups", []))
        fully_eligible = st["verified"] and st["verdict"] == "ELIGIBLE" and st["specificity"] > 0
        if aimed_elsewhere(sorted(primary), profile) and not fully_eligible:
            continue
        if groups and st["specificity"] == 0 and not (mentioned & set(groups)):
            continue  # generic rules (only age / citizenship / state) and nothing about the person's groups: noise
        if not st["verified"]:
            # Machine-read rules are less certain: the scheme must be *for* one of the person's groups, and if its
            # rules are vague (only age / citizenship / state) it must be a scheme of their own state too.
            if not (primary & set(groups)):
                continue
            if st["specificity"] == 0 and m.get("level") != "state":
                continue
        keep.append(st)
    stats = keep
    if not stats:
        return {"groups": groups, "group_labels": [LABELS[g] for g in groups], "items": [], "evaluated": res["evaluated"]}

    similar = similar_user_ids(db, profile, exclude=user_id)
    saved_by_me = {a["scheme_slug"] for a in db.applications.find({"user_id": user_id}, {"scheme_slug": 1})} if user_id else set()
    n_groups = len(groups)
    pipeline = [
        {"$match": {"slug": {"$in": [s["slug"] for s in stats]}}},
        # Bring in the engine's result for this scheme (passed in as a literal array).
        {"$addFields": {"rule": {"$first": {"$filter": {"input": {"$literal": stats}, "cond": {"$eq": ["$$this.slug", "$slug"]}}}}}},
        {"$addFields": {"matched_groups": {"$setIntersection": [{"$ifNull": ["$beneficiary_groups", []]}, groups]},
                        "matched_primary": {"$setIntersection": [{"$ifNull": ["$primary_groups", []]}, groups]}}},
        # A scheme aimed at other groups (e.g. student scholarships for a 67-year-old) isn't a recommendation,
        # unless reviewed rules say the person is fully eligible.
        {"$match": {"$expr": {"$or": [{"$eq": [n_groups, 0]}, {"$gt": [{"$size": "$matched_groups"}, 0]},
                                      {"$and": ["$rule.verified", {"$eq": ["$rule.verdict", "ELIGIBLE"]}]}]}}},
        # How many similar users saved this scheme to their tracker.
        {"$lookup": {"from": "applications", "localField": "slug", "foreignField": "scheme_slug", "as": "saves",
                     "pipeline": [{"$match": {"user_id": {"$in": similar}}}, {"$project": {"_id": 1}}]}},
        {"$addFields": {
            "similar_saves": {"$size": "$saves"},
            # primary groups count fully, groups only mentioned in the text count half
            "group_match": {"$cond": [{"$gt": [n_groups, 0]}, {"$min": [1, {"$divide": [{"$add": [
                {"$size": "$matched_primary"},
                {"$multiply": [0.5, {"$size": {"$setDifference": ["$matched_groups", "$matched_primary"]}}]}]}, n_groups]}]}, 0]},
            "rule_part": {"$multiply": [W_RULE, "$rule.rule_match", {"$add": [0.5, {"$multiply": [0.5, "$rule.specificity"]}]}]},
        }},
        {"$addFields": {"popularity": {"$divide": ["$similar_saves", {"$add": ["$similar_saves", 3]}]}}},  # 0 → 0, 3 saves → 0.5
        {"$addFields": {"score": {"$round": [{"$multiply": [
            {"$add": ["$rule_part", {"$multiply": [W_GROUP, "$group_match"]}, {"$multiply": [W_POP, "$popularity"]}]},
            {"$cond": ["$rule.verified", 1, UNVERIFIED_FACTOR]}]}, 3]}}},
        {"$sort": {"score": -1, "rule.verified": -1, "name": 1}},
        {"$limit": limit},
        {"$project": {"_id": 0, "slug": 1, "name": 1, "level": 1, "state": 1, "source_url": 1, "score": 1, "rule": 1,
                      "matched_groups": 1, "matched_primary": 1, "similar_saves": 1, "group_match": 1, "popularity": 1, "rule_part": 1,
                      "unmapped_conditions": 1}},
    ]
    items = list(db.schemes.aggregate(pipeline))
    for it in items:
        r = it["rule"]
        factor = 1 if r["verified"] else UNVERIFIED_FACTOR
        if not r["verified"]:
            why = ["Rules read automatically from the scheme page and not yet checked by a reviewer — confirm on the official page"]
            if r["unchecked"]:
                why.append(f"{r['unchecked']} other requirement{'s' if r['unchecked'] != 1 else ''} on the scheme page couldn't be checked automatically")
        elif r["verdict"] == "ELIGIBLE":
            why = ["You meet every required condition — eligible"]
        else:
            why = [f"You meet {r['passed']} condition{'s' if r['passed'] != 1 else ''}; {r['unknown']} still unknown"]
        if it["matched_primary"]:
            why.append("Meant for: " + ", ".join(LABELS.get(g, g) for g in it["matched_primary"]))
        side = [g for g in it["matched_groups"] if g not in it["matched_primary"]]
        if side:
            why.append("Also mentions: " + ", ".join(LABELS.get(g, g) for g in side))
        if groups and not it["matched_groups"]:
            why.append("Not specifically aimed at your groups")
        if r["specificity"] == 0:
            why.append("Its rules are general (only age, citizenship or state)")
        if it["similar_saves"]:
            why.append(f"Saved by {it['similar_saves']} user{'s' if it['similar_saves'] != 1 else ''} with a similar profile")
        if r["missing"]:
            why.append("To confirm, tell us: " + ", ".join(m.replace("_", " ") for m in r["missing"]))
        if r["verified"] and it.get("unmapped_conditions"):
            why.append("Also check: " + "; ".join(it["unmapped_conditions"][:2]))
        it.update(verdict=r["verdict"], verified=r["verified"], why=why, saved=it["slug"] in saved_by_me,
                  parts={"rule_match": round(factor * it["rule_part"], 3), "group_match": round(factor * W_GROUP * it["group_match"], 3),
                         "popularity": round(factor * W_POP * it["popularity"], 3)})
        for k in ("rule", "group_match", "popularity", "rule_part", "unmapped_conditions", "matched_primary"):
            it.pop(k, None)
    verified_n = sum(1 for s in stats if s["verified"])
    return {"groups": groups, "group_labels": [LABELS[g] for g in groups], "items": items, "evaluated": res["evaluated"],
            "candidates": {"verified": verified_n, "unverified": len(stats) - verified_n},
            "similar_users": len(similar), "weights": {"rule_match": W_RULE, "group_match": W_GROUP, "popularity": W_POP}}
