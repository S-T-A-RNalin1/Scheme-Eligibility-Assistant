"""Scheme coverage gap analytics.

Supply  = which schemes exist for each region (state/UT) and beneficiary group.
Demand  = what people search for (Ask questions and scheme searches), logged in `search_logs`.
A gap is a place or group where demand is high but few schemes match.

District-level data is not part of the myScheme dataset (state schemes apply state-wide),
so regions are states and union territories. The same pipelines work per district once
schemes and searches carry a district field.
"""
import re
from datetime import datetime, timedelta, timezone

from pymongo import ASCENDING, DESCENDING, GEOSPHERE, UpdateOne

# Approximate geographic centres (lat, lon) of each state / UT, for the coverage map.
REGIONS = {
    "Andaman and Nicobar Islands": (11.74, 92.66, "ut"), "Andhra Pradesh": (15.91, 79.74, "state"),
    "Arunachal Pradesh": (28.22, 94.73, "state"), "Assam": (26.20, 92.94, "state"), "Bihar": (25.10, 85.31, "state"),
    "Chandigarh": (30.73, 76.78, "ut"), "Chhattisgarh": (21.28, 81.87, "state"),
    "Dadra and Nagar Haveli and Daman and Diu": (20.40, 72.83, "ut"), "Delhi": (28.70, 77.10, "ut"),
    "Goa": (15.30, 74.12, "state"), "Gujarat": (22.26, 71.19, "state"), "Haryana": (29.06, 76.09, "state"),
    "Himachal Pradesh": (31.10, 77.17, "state"), "Jammu and Kashmir": (33.78, 76.58, "ut"),
    "Jharkhand": (23.61, 85.28, "state"), "Karnataka": (15.32, 75.71, "state"), "Kerala": (10.85, 76.27, "state"),
    "Ladakh": (34.15, 77.58, "ut"), "Lakshadweep": (10.57, 72.64, "ut"), "Madhya Pradesh": (22.97, 78.66, "state"),
    "Maharashtra": (19.75, 75.71, "state"), "Manipur": (24.66, 93.91, "state"), "Meghalaya": (25.47, 91.37, "state"),
    "Mizoram": (23.16, 92.94, "state"), "Nagaland": (26.16, 94.56, "state"), "Odisha": (20.95, 85.10, "state"),
    "Puducherry": (11.94, 79.81, "ut"), "Punjab": (31.15, 75.34, "state"), "Rajasthan": (27.02, 74.22, "state"),
    "Sikkim": (27.53, 88.51, "state"), "Tamil Nadu": (11.13, 78.66, "state"), "Telangana": (18.11, 79.02, "state"),
    "Tripura": (23.94, 91.99, "state"), "Uttar Pradesh": (26.85, 80.95, "state"),
    "Uttarakhand": (30.07, 79.02, "state"), "West Bengal": (22.99, 87.85, "state"),
}

# Beneficiary groups: (label, text pattern). Rule attributes add more evidence in groups_for_scheme().
GROUPS = {
    "women": ("Women & girls", r"\b(women|woman|girls?|female|widows?|mahila|mothers?|pregnan\w*|maternity|daughters?)\b"),
    "sc_st": ("SC / ST", r"scheduled castes?|scheduled tribes?|\bsc\b|\bst\b|\bsc/st\b|tribal|adivasi"),
    "obc": ("OBC / backward classes", r"\bobcs?\b|other backward|backward class\w*|\bebcs?\b"),
    "minority": ("Minorities", r"minorit\w*|muslim|christian|sikh|buddhist|jain|parsi"),
    "students": ("Students", r"students?|scholarships?|school|college|fellowships?|stipend|studies|education(al)? (loan|assistance)"),
    "farmers": ("Farmers", r"farmers?|agricultur\w*|kisan|crops?|horticultur\w*|irrigation|livestock|dairy|fisher\w*|sericultur\w*"),
    "disability": ("Persons with disability", r"disab\w*|divyang\w*|handicap\w*|\bpwds?\b|blind|deaf"),
    "senior": ("Senior citizens", r"senior citizens?|old age|elderly|aged persons?|oldage|above (the age of )?(60|65)\b|(60|65) years (of age )?and above|aged (60|65)"),
    "poor": ("BPL / low income", r"below poverty|\bbpl\b|\bpoor\b|economically weaker|\bews\b|low income|antyodaya"),
    "entrepreneurs": ("Entrepreneurs & MSMEs", r"entrepreneur\w*|enterprises?|msmes?|start-?ups?|self[- ]employ\w*|industr\w*|capital investment"),
    "workers": ("Workers & artisans", r"workers?|labou?r\w*|construction|unorgani[sz]ed|artisans?|weavers?|handloom|street vendors?|migrant"),
    "youth": ("Youth & job seekers", r"\byouth|young|unemployed|skills?|training|apprentice\w*|employment|jobs?\b"),
    "children": ("Children", r"\bchild|children|orphans?|infants?"),
}
GROUP_RE = {k: re.compile(p, re.I) for k, (_, p) in GROUPS.items()}
LABELS = {k: lbl for k, (lbl, _) in GROUPS.items()}
DEMAND_WINDOW_DAYS = 180
LOW_MATCH = 2  # a search returning this many matching schemes or fewer counts as poorly served


def groups_in_text(text: str) -> list[str]:
    return [k for k, rx in GROUP_RE.items() if rx.search(text or "")]


def _rule_groups(node) -> set[str]:
    out = set()
    if not node:
        return out
    if "attribute" in node:
        a, v = node["attribute"], node.get("value")
        vals = {str(x).lower() for x in (v if isinstance(v, list) else [v])}
        if a == "gender" and "female" in vals:
            out.add("women")
        if a == "category" and vals & {"sc", "st"}:
            out.add("sc_st")
        if a == "category" and "obc" in vals:
            out.add("obc")
        if a == "is_student":
            out.add("students")
        if a == "occupation" and "farmer" in vals:
            out.add("farmers")
        if a in ("has_disability", "disability_percent"):
            out.add("disability")
        if a == "is_bpl":
            out.add("poor")
        if a == "is_minority":
            out.add("minority")
        return out
    for c in node.get("children", []):
        out |= _rule_groups(c)
    return out


def primary_groups_for_scheme(s: dict) -> list[str]:
    """Who the scheme is *for*: groups named in its title or tags, or required by its rules.
    (Body text also mentions groups in passing, e.g. "30% of seats reserved for girls".)"""
    return sorted(set(groups_in_text(s.get("name", "") + " " + " ".join(s.get("tags", [])))) | _rule_groups(s.get("eligibility")))


def groups_for_scheme(s: dict) -> list[str]:
    sec = s.get("sections") or {}
    text = " ".join([s.get("name", ""), " ".join(s.get("tags", [])), sec.get("eligibility", ""), (sec.get("description") or "")[:600]])
    return sorted(set(groups_in_text(text)) | _rule_groups(s.get("eligibility")))


def ensure_indexes(db):
    db.regions.create_index([("location", GEOSPHERE)])  # 2dsphere: enables $geoNear / $near on the map
    db.regions.create_index([("name", ASCENDING)], unique=True)
    db.schemes.create_index([("beneficiary_groups", ASCENDING)])
    db.schemes.create_index([("primary_groups", ASCENDING)])
    db.search_logs.create_index([("created_at", DESCENDING)])
    db.search_logs.create_index([("state", ASCENDING), ("created_at", DESCENDING)])
    db.search_logs.create_index([("q_norm", ASCENDING)])
    # Search history is only needed for trends: it expires on its own (data minimisation).
    db.search_logs.create_index([("expires_at", ASCENDING)], expireAfterSeconds=0)


def backfill(db) -> int:
    """Tag every scheme with its beneficiary groups and (re)load the region points."""
    ensure_indexes(db)
    db.regions.bulk_write([UpdateOne({"name": n}, {"$set": {"name": n, "type": t,
                                                            "location": {"type": "Point", "coordinates": [lon, lat]}}},
                                     upsert=True) for n, (lat, lon, t) in REGIONS.items()])
    ops = [UpdateOne({"_id": s["_id"]}, {"$set": {"beneficiary_groups": groups_for_scheme(s),
                                                  "primary_groups": primary_groups_for_scheme(s)}})
           for s in db.schemes.find({}, {"name": 1, "tags": 1, "sections.eligibility": 1, "sections.description": 1, "eligibility": 1})]
    if ops:
        db.schemes.bulk_write(ops, ordered=False)
    return len(ops)


def normalize_query(q: str) -> str:
    words = re.findall(r"[a-z0-9]+", q.lower())
    stop = {"the", "a", "an", "for", "of", "in", "to", "and", "is", "are", "what", "which", "how", "do", "i", "can",
            "my", "me", "scheme", "schemes", "yojana", "any", "there", "get", "about", "please", "tell", "with"}
    return " ".join(w for w in words if w not in stop)[:80]


def log_search(db, q: str, source: str, results_count: int, state: str | None = None, demo: bool = False):
    now = datetime.now(timezone.utc)
    db.search_logs.insert_one({
        "q_norm": normalize_query(q), "groups": groups_in_text(q), "state": state if state in REGIONS else None,
        "source": source, "results_count": int(results_count), "demo": demo, "created_at": now,
        "expires_at": now + timedelta(days=DEMAND_WINDOW_DAYS)})


def coverage_report(db) -> dict:
    live = {"status": {"$ne": "retired"}}
    supply = next(db.schemes.aggregate([{"$match": live}, {"$facet": {
        "by_state": [{"$match": {"level": "state"}}, {"$group": {"_id": "$state", "n": {"$sum": 1}}}],
        "central": [{"$match": {"level": "central"}}, {"$count": "n"}],
        "by_group": [{"$unwind": "$beneficiary_groups"}, {"$group": {"_id": "$beneficiary_groups", "n": {"$sum": 1}}}],
        "central_by_group": [{"$match": {"level": "central"}}, {"$unwind": "$beneficiary_groups"},
                             {"$group": {"_id": "$beneficiary_groups", "n": {"$sum": 1}}}],
        "state_group": [{"$match": {"level": "state"}}, {"$unwind": "$beneficiary_groups"},
                        {"$group": {"_id": {"state": "$state", "group": "$beneficiary_groups"}, "n": {"$sum": 1}}}],
        # $bucket: how many states fall in each band of state-specific scheme counts.
        "bands": [{"$match": {"level": "state"}}, {"$group": {"_id": "$state", "n": {"$sum": 1}}},
                  {"$bucket": {"groupBy": "$n", "boundaries": [1, 5, 10, 20, 40], "default": "40+",
                               "output": {"states": {"$sum": 1}, "names": {"$push": "$_id"}}}}],
    }}]))
    since = datetime.now(timezone.utc) - timedelta(days=DEMAND_WINDOW_DAYS)
    demand = next(db.search_logs.aggregate([{"$match": {"created_at": {"$gte": since}}}, {"$facet": {
        "total": [{"$count": "n"}],
        "demo": [{"$match": {"demo": True}}, {"$count": "n"}],
        "by_state": [{"$match": {"state": {"$ne": None}}},
                     {"$group": {"_id": "$state", "n": {"$sum": 1}, "low": {"$sum": {"$cond": [{"$lte": ["$results_count", LOW_MATCH]}, 1, 0]}},
                                 "avg_results": {"$avg": "$results_count"}}}],
        "by_group": [{"$unwind": "$groups"},
                     {"$group": {"_id": "$groups", "n": {"$sum": 1}, "low": {"$sum": {"$cond": [{"$lte": ["$results_count", LOW_MATCH]}, 1, 0]}},
                                 "avg_results": {"$avg": "$results_count"}}}],
        "state_group": [{"$match": {"state": {"$ne": None}}}, {"$unwind": "$groups"},
                        {"$group": {"_id": {"state": "$state", "group": "$groups"}, "n": {"$sum": 1}}}],
        "low_match": [{"$match": {"results_count": {"$lte": LOW_MATCH}, "q_norm": {"$ne": ""}}},
                      {"$group": {"_id": "$q_norm", "searches": {"$sum": 1}, "avg_results": {"$avg": "$results_count"},
                                  "states": {"$addToSet": "$state"}, "groups": {"$first": "$groups"}}},
                      {"$sort": {"searches": -1}}, {"$limit": 15}],
        # $bucket: how many searches returned 0, 1-2, 3-5, 6-10, 11+ matching schemes.
        "results_bands": [{"$bucket": {"groupBy": "$results_count", "boundaries": [0, 1, 3, 6, 11], "default": "11+",
                                       "output": {"searches": {"$sum": 1}}}}],
    }}]))

    st_supply = {d["_id"]: d["n"] for d in supply["by_state"]}
    central = supply["central"][0]["n"] if supply["central"] else 0
    st_demand = {d["_id"]: d for d in demand["by_state"]}
    total_supply = sum(st_supply.values()) or 1
    total_demand = sum(d["n"] for d in demand["by_state"]) or 1
    sg_supply = {(d["_id"]["state"], d["_id"]["group"]): d["n"] for d in supply["state_group"]}
    central_g = {d["_id"]: d["n"] for d in supply["central_by_group"]}
    sg_demand = {(d["_id"]["state"], d["_id"]["group"]): d["n"] for d in demand["state_group"]}

    regions = []
    for r in db.regions.find({}, {"_id": 0}):
        name = r["name"]
        sup, dem = st_supply.get(name, 0), st_demand.get(name, {})
        n_dem = dem.get("n", 0)
        # Gap index: share of all searches coming from this region / share of all state schemes it has.
        # 1 = balanced; above 1 = more demand than its share of schemes. +1 smoothing avoids division by zero.
        gap = round((n_dem / total_demand) / ((sup + 1) / (total_supply + len(REGIONS))), 2) if n_dem else 0.0
        missing = [{"group": g, "label": LABELS[g], "searches": sg_demand[(name, g)]}
                   for g in GROUPS if sg_demand.get((name, g), 0) >= 3 and sg_supply.get((name, g), 0) == 0]
        missing.sort(key=lambda m: -m["searches"])
        regions.append({"name": name, "type": r["type"], "lon": r["location"]["coordinates"][0], "lat": r["location"]["coordinates"][1],
                        "state_schemes": sup, "searches": n_dem, "low_match": dem.get("low", 0),
                        "low_match_rate": round(dem.get("low", 0) / n_dem, 2) if n_dem else 0.0,
                        "gap_index": gap, "level": "high" if gap >= 2 else "medium" if gap >= 1 else "low",
                        "uncovered_groups": missing[:4]})
    regions.sort(key=lambda x: -x["gap_index"])

    groups = []
    dem_g = {d["_id"]: d for d in demand["by_group"]}
    sup_g = {d["_id"]: d["n"] for d in supply["by_group"]}
    for g, label in LABELS.items():
        d = dem_g.get(g, {})
        groups.append({"group": g, "label": label, "schemes": sup_g.get(g, 0), "central_schemes": central_g.get(g, 0),
                       "searches": d.get("n", 0), "low_match": d.get("low", 0),
                       "avg_results": round(d.get("avg_results") or 0, 1),
                       "searches_per_scheme": round(d.get("n", 0) / max(sup_g.get(g, 0), 1), 1)})
    groups.sort(key=lambda x: -x["searches_per_scheme"])

    matrix = {"groups": list(LABELS), "labels": LABELS,
              "rows": [{"state": n, "cells": {g: sg_supply.get((n, g), 0) for g in GROUPS}} for n in sorted(REGIONS)]}
    return {
        "note": "Regions are states and UTs; the dataset has no district-level schemes.",
        "central_schemes": central, "central_by_group": central_g,
        "searches": demand["total"][0]["n"] if demand["total"] else 0,
        "demo_searches": demand["demo"][0]["n"] if demand["demo"] else 0,
        "window_days": DEMAND_WINDOW_DAYS, "low_match_threshold": LOW_MATCH,
        "regions": regions, "groups": groups, "matrix": matrix,
        "supply_bands": supply["bands"], "results_bands": demand["results_bands"],
        "unmet_searches": [{"query": d["_id"], "searches": d["searches"], "avg_results": round(d["avg_results"], 1),
                            "states": sorted(s for s in d["states"] if s), "groups": [LABELS[g] for g in d["groups"] or []]}
                           for d in demand["low_match"]],
    }


def nearby(db, state: str, km: int = 600) -> list[dict]:
    """Regions within `km` of a state's centre, nearest first ($geoNear on the 2dsphere index)."""
    r = db.regions.find_one({"name": state})
    if not r:
        return []
    pts = db.regions.aggregate([
        {"$geoNear": {"near": r["location"], "distanceField": "dist_m", "maxDistance": km * 1000, "spherical": True}},
        {"$lookup": {"from": "schemes", "let": {"n": "$name"}, "as": "s",
                     "pipeline": [{"$match": {"$expr": {"$eq": ["$state", "$$n"]}, "status": {"$ne": "retired"}}}, {"$count": "n"}]}},
        {"$project": {"_id": 0, "name": 1, "km": {"$round": [{"$divide": ["$dist_m", 1000]}, 0]},
                      "state_schemes": {"$ifNull": [{"$first": "$s.n"}, 0]}}},
    ])
    return list(pts)
