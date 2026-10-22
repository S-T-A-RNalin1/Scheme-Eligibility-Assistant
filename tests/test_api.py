"""End-to-end API tests against a real MongoDB (separate test database)."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pymongo.errors import WriteError

from api import config
from api.db import client as mongo_client, get_db, init_db
from api.engine.attributes import ATTRIBUTES
from api.main import app
from api.rag import retrieve
from api.rag.chunk import chunk_scheme
from api.rag import embed
from api.security import hash_password
from api.services import now, publish_version

ROOT = Path(__file__).absolute().parent.parent
SLUGS = ["apy", "aaby", "cbssc-tl", "ay"]


@pytest.fixture(scope="module")
def c():
    assert config.DB_NAME.endswith("_test")
    mongo_client().drop_database(config.DB_NAME)
    db = init_db(get_db())
    db.attribute_registry.insert_many([{**a, "order": i} for i, a in enumerate(ATTRIBUTES)])
    schemes = [s for s in json.loads((ROOT / "data" / "schemes_parsed.json").read_text(encoding="utf-8")) if s["slug"] in SLUGS]
    curated = json.loads((ROOT / "data" / "curated_rules.json").read_text(encoding="utf-8"))["schemes"]
    for s in schemes:
        db.schemes.insert_one({"slug": s["slug"], "name": s["name"], "level": s["level"], "state": s["state"], "tags": s["tags"],
                               "sections": s["sections"], "source_url": s["source_url"], "source_hash": s["source_hash"],
                               "status": "in_review", "current_version": None, "eligibility": None, "created_at": now()})
        db.ingestion_jobs.insert_one({"scheme_slug": s["slug"], "source_hash": s["source_hash"], "stage": "in_review",
                                      "proposed_eligibility": curated[s["slug"]]["eligibility"], "extracted_by": "test",
                                      "unmapped_conditions": [], "validation_errors": []})
        if s["slug"] != "ay":  # leave one in the review queue
            publish_version(db, s["slug"], curated[s["slug"]]["eligibility"], reviewed_by="reviewer:test", change_note="test",
                            source_text=" ".join(s["sections"].values()))
    chunks = [ch for s in schemes for ch in chunk_scheme(s)]
    vecs = embed.embed([ch["embed_text"] for ch in chunks])
    for ch, v in zip(chunks, vecs):
        ch["embedding"] = v.tolist()
    db.document_chunks.insert_many(chunks)
    retrieve.load_matrix(db, force=True)
    db.users.insert_one({"email": "admin@example.com", "name": "A", "password_hash": hash_password("adminpass1"), "role": "admin", "created_at": now()})
    with TestClient(app) as tc:
        yield tc
    mongo_client().drop_database(config.DB_NAME)


def auth(c, email, pw, register=False):
    r = c.post("/api/auth/register" if register else "/api/auth/login", json={"email": email, "password": pw, "name": "T"})
    assert r.status_code in (200, 201), r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_health_reports_replica_set(c):
    r = c.get("/api/health").json()
    assert r["status"] == "ok" and r["replica_set"] is True


def test_read_schemes_list_detail_and_search(c):
    r = c.get("/api/schemes", params={"q": "pension"}).json()
    assert r["items"][0]["slug"] == "apy"
    d = c.get("/api/schemes/apy").json()
    assert d["current_version"] == 1 and d["versions"][0]["reviewed_by"] == "reviewer:test"
    assert c.get("/api/schemes/nope").status_code == 404


def test_check_creates_audit_records(c):
    r = c.post("/api/eligibility/check", json={"profile": {"age": 30, "is_income_tax_payer": False}}).json()
    assert "apy" in [x["slug"] for x in r["eligible"]]
    assert r["next_question"] is not None
    stored = get_db().evaluations.count_documents({"run_id": r["run_id"]})
    assert stored == r["evaluated"] == 3  # published only; 'ay' still in review


def test_invalid_profile_rejected(c):
    assert c.post("/api/eligibility/check", json={"profile": {"age": -5}}).status_code == 422
    assert c.post("/api/eligibility/check", json={"profile": {"shoe_size": 9}}).status_code == 422
    assert c.post("/api/eligibility/check", json={"profile": {"state": "Atlantis"}}).status_code == 422


def test_profile_crud_and_privacy_delete(c):
    h = auth(c, "u1@example.com", "password123", register=True)
    assert c.post("/api/auth/register", json={"email": "u1@example.com", "password": "password123"}).status_code == 409
    assert c.put("/api/profile", json={"attributes": {"age": 30}, "consent": False}, headers=h).status_code == 400
    assert c.put("/api/profile", json={"attributes": {"age": 30, "state": "Assam"}, "consent": True}, headers=h).json()["saved"]
    assert c.get("/api/profile", headers=h).json()["attributes"] == {"age": 30.0, "state": "Assam"}
    c.put("/api/profile", json={"attributes": {"age": 31}, "consent": True}, headers=h)
    assert c.get("/api/profile", headers=h).json()["attributes"]["age"] == 31
    run = c.post("/api/eligibility/check", json={"use_saved_profile": True}, headers=h).json()
    assert run["evaluated"] >= 2
    assert len(c.get("/api/eligibility/history", headers=h).json()) == 1
    d = c.delete("/api/profile", headers=h).json()
    assert d["deleted_profile"] == 1 and d["deleted_evaluations"] == run["evaluated"]


def test_auth_required_and_admin_forbidden_for_users(c):
    assert c.get("/api/profile").status_code == 401
    h = auth(c, "u2@example.com", "password123", register=True)
    assert c.get("/api/admin/stats", headers=h).status_code == 403
    assert c.post("/api/auth/login", json={"email": "u2@example.com", "password": "wrongpass"}).status_code == 401


def test_rule_review_and_audit_endpoints_removed(c):
    h = auth(c, "admin@example.com", "adminpass1")
    ev = get_db().evaluations.find_one()
    for method, path in [("get", "/api/admin/review"), ("post", "/api/admin/review/ay/approve"),
                         ("get", "/api/admin/evaluations"), ("get", f"/api/admin/evaluations/{ev['_id']}/replay")]:
        assert getattr(c, method)(path, headers=h).status_code in (404, 405), path
    page = c.get("/admin").text
    assert 'id="review-queue"' not in page and 'id="audit"' not in page


def test_publishing_a_version_is_validated_and_atomic(c):
    from api.services import PublishError, publish_version
    db = get_db()
    bad = {"op": "AND", "children": [{"id": "r1", "attribute": "age", "operator": "~", "value": 1}]}
    with pytest.raises(PublishError):
        publish_version(db, "ay", bad, reviewed_by="reviewer:test", change_note="bad")
    assert db.scheme_versions.count_documents({"scheme_slug": "ay"}) == 0          # nothing half-written
    curated = json.loads((ROOT / "data" / "curated_rules.json").read_text(encoding="utf-8"))["schemes"]
    assert publish_version(db, "ay", curated["ay"]["eligibility"], reviewed_by="reviewer:test", change_note="ok") == 1
    s = db.schemes.find_one({"slug": "ay"})
    assert s["status"] == "published" and s["current_version"] == 1
    assert db.ingestion_jobs.find_one({"scheme_slug": "ay"})["stage"] == "published"


def test_stored_decisions_stay_tamper_evident(c):
    from api.services import replay
    db = get_db()
    ev = db.evaluations.find_one()
    r = replay(db, str(ev["_id"]))
    assert r["verdict_matches"] and r["checksum_valid"]
    db.evaluations.update_one({"_id": ev["_id"]}, {"$set": {"profile_snapshot.age": 99}})
    assert replay(db, str(ev["_id"]))["checksum_valid"] is False


def test_database_validator_rejects_bad_documents(c):
    with pytest.raises(WriteError):
        get_db().evaluations.insert_one({"run_id": "x", "verdict": "MAYBE"})
    with pytest.raises(WriteError):
        get_db().schemes.insert_one({"slug": "Bad Slug!", "name": "x", "level": "planet", "status": "published", "source_url": "u"})


def test_stats_aggregations(c):
    h = auth(c, "admin@example.com", "adminpass1")
    s = c.get("/api/admin/stats", headers=h).json()
    assert s["counts"]["schemes"] == 4 and sum(v["n"] for v in s["verdicts"]) > 0


def test_chat_routes_and_refusal(c):
    r = c.post("/api/chat", json={"question": "Am I eligible for Atal Pension Yojana?", "profile": {"age": 30, "is_income_tax_payer": False},
                                  "stream": False}).json()
    assert r["route"] == "eligibility" and "ELIGIBLE" in r["answer"]
    r = c.post("/api/chat", json={"question": "Who will win the cricket world cup?", "stream": False}).json()
    assert r["route"] == "off_topic"
    r = c.post("/api/chat", json={"question": "What is the age limit to join Atal Pension Yojana?", "stream": False}).json()
    assert r["citations"] and all(ci["scheme_slug"] for ci in r["citations"])


def test_soft_delete_retire(c):
    h = auth(c, "admin@example.com", "adminpass1")
    assert c.post("/api/admin/schemes/cbssc-tl/retire", headers=h).json()["retired"] == "cbssc-tl"
    slugs = [s["slug"] for s in c.get("/api/schemes").json()["items"]]
    assert "cbssc-tl" not in slugs


def test_grievance_lifecycle(c):
    u = auth(c, "g1@example.com", "password123", register=True)
    a = auth(c, "admin@example.com", "adminpass1")
    run = c.post("/api/eligibility/check", json={"profile": {"age": 30}}, headers=u).json()["run_id"]
    body = {"scheme_slug": "apy", "category": "application_status", "subject": "Application pending",
            "description": "I applied for APY three months ago and have not heard back.", "run_id": run}
    r = c.post("/api/grievances", json=body, headers=u)
    assert r.status_code == 201
    ticket = r.json()["ticket"]
    assert ticket.startswith("GRV-") and len(ticket) == 15
    # A second grievance gets the next number from the atomic counter.
    t2 = c.post("/api/grievances", json={**body, "run_id": None, "subject": "Second issue"}, headers=u).json()["ticket"]
    assert int(t2[-6:]) == int(ticket[-6:]) + 1
    assert [g["ticket"] for g in c.get("/api/grievances", headers=u).json()] == [t2, ticket]

    assert c.post(f"/api/grievances/{ticket}/comments", json={"note": "Any update?"}, headers=u).status_code == 200
    r = c.post(f"/api/admin/grievances/{ticket}/status", json={"status": "resolved", "note": "Application approved.",
                                                               "priority": "high"}, headers=a)
    assert r.json()["status"] == "resolved"
    g = c.get(f"/api/grievances/{ticket}", headers=u).json()
    assert g["status"] == "resolved" and g["resolved_at"] and g["priority"] == "high"
    assert [t["action"] for t in g["timeline"]] == ["filed", "comment", "status_change"]
    r = c.post(f"/api/grievances/{ticket}/comments", json={"note": "Money not received yet", "reopen": True}, headers=u)
    assert r.json()["status"] == "open"
    q = c.get("/api/admin/grievances", params={"status": "open"}, headers=a).json()
    assert ticket in [i["ticket"] for i in q["items"]] and q["items"][0]["filer"]["email"]
    assert c.get("/api/admin/stats", headers=a).json()["grievances"]["by_status"]


def test_grievance_access_and_validation(c):
    u = auth(c, "g2@example.com", "password123", register=True)
    other = auth(c, "g3@example.com", "password123", register=True)
    good = {"scheme_slug": "apy", "category": "documents", "subject": "Document rejected",
            "description": "My bank passbook copy was rejected without a reason."}
    assert c.post("/api/grievances", json=good).status_code == 401                       # login required
    assert c.post("/api/grievances", json={**good, "category": "spam"}, headers=u).status_code == 422
    assert c.post("/api/grievances", json={**good, "description": "too short"}, headers=u).status_code == 422
    assert c.post("/api/grievances", json={**good, "scheme_slug": "no-such"}, headers=u).status_code == 404
    assert c.post("/api/grievances", json={**good, "run_id": "run_deadbeef"}, headers=u).status_code == 400
    ticket = c.post("/api/grievances", json=good, headers=u).json()["ticket"]
    assert c.get(f"/api/grievances/{ticket}", headers=other).status_code == 403          # not your grievance
    assert c.post(f"/api/admin/grievances/{ticket}/status", json={"status": "closed", "note": "x!"}, headers=u).status_code == 403
    with pytest.raises(WriteError):                                                     # DB validator as last line
        get_db().grievances.insert_one({"ticket": "BAD", "status": "lost"})


def test_separate_citizen_and_admin_login(c):
    auth(c, "cit@example.com", "password123", register=True)
    ok = c.post("/api/auth/login", json={"email": "cit@example.com", "password": "password123", "as_role": "citizen"})
    assert ok.status_code == 200 and ok.json()["user"]["role"] == "user"
    r = c.post("/api/auth/login", json={"email": "cit@example.com", "password": "password123", "as_role": "admin"})
    assert r.status_code == 403 and "not an admin" in r.json()["detail"]
    r = c.post("/api/auth/login", json={"email": "admin@example.com", "password": "adminpass1", "as_role": "citizen"})
    assert r.status_code == 403
    r = c.post("/api/auth/login", json={"email": "admin@example.com", "password": "adminpass1", "as_role": "admin"})
    assert r.status_code == 200 and r.json()["user"]["role"] == "admin"
    assert c.post("/api/auth/login", json={"email": "admin@example.com", "password": "x", "as_role": "superuser"}).status_code == 422


def test_pages_are_served_separately(c):
    for path, marker in [("/", 'id="check"'), ("/login", 'class="role-tabs"'), ("/admin", 'id="coverage"')]:
        r = c.get(path)
        assert r.status_code == 200 and marker in r.text
    assert 'id="auth-form"' not in c.get("/").text  # no login form on the front page any more


def test_coverage_analytics(c):
    from api import analytics
    db = get_db()
    analytics.backfill(db)
    assert db.regions.count_documents({}) == len(analytics.REGIONS)
    assert "poor" in db.schemes.find_one({"slug": "aaby"})["beneficiary_groups"]  # BPL rule in Aam Aadmi Bima Yojana
    # Demand is logged from real searches: a scheme search and an Ask question.
    before = db.search_logs.count_documents({})
    c.get("/api/schemes", params={"q": "pension", "state": "Assam"})
    c.post("/api/chat", json={"question": "yacht loan", "stream": False, "profile": {"state": "Assam"}})  # nothing matches
    c.post("/api/chat", json={"question": "Who will win the cricket world cup?", "stream": False})  # off-topic: not demand
    logs = list(db.search_logs.find().sort("created_at", -1).limit(2))
    assert db.search_logs.count_documents({}) == before + 2
    assert {l["source"] for l in logs} == {"browse", "ask"} and all(l["state"] == "Assam" for l in logs)
    unmet = next(l for l in logs if l["source"] == "ask")
    assert unmet["results_count"] == 0 and unmet["q_norm"] == "yacht loan"
    for _ in range(3):
        analytics.log_search(db, "pension for senior citizens", "ask", 0, state="Assam")

    h = auth(c, "admin@example.com", "adminpass1")
    u = auth(c, "cov@example.com", "password123", register=True)
    assert c.get("/api/admin/coverage", headers=u).status_code == 403
    r = c.get("/api/admin/coverage", headers=h).json()
    assam = next(x for x in r["regions"] if x["name"] == "Assam")
    assert assam["searches"] >= 5 and assam["state_schemes"] == 1 and assam["low_match"] >= 4
    assert any(u_["query"] == "pension senior citizens" for u_ in r["unmet_searches"])
    assert {"groups", "matrix", "supply_bands", "results_bands"} <= set(r)
    near = c.get("/api/admin/coverage/nearby", params={"state": "Assam", "km": 400}, headers=h).json()
    assert near[0]["name"] == "Assam" and near[0]["km"] == 0
    assert [n["km"] for n in near] == sorted(n["km"] for n in near) and "Meghalaya" in {n["name"] for n in near}
    assert c.get("/api/admin/coverage/nearby", params={"state": "Atlantis"}, headers=h).status_code == 404


def test_beneficiary_group_detection():
    from api.analytics import groups_for_scheme, groups_in_text
    assert set(groups_in_text("pension for widows")) == {"women"}
    assert "farmers" in groups_in_text("drip irrigation subsidy for small farmers")
    rule_only = {"name": "X", "tags": [], "sections": {}, "eligibility": {"op": "AND", "children": [
        {"id": "r1", "attribute": "category", "operator": "in", "value": ["SC"]},
        {"id": "r2", "attribute": "gender", "operator": "==", "value": "female"}]}}
    assert groups_for_scheme(rule_only) == ["sc_st", "women"]


def test_application_tracker(c):
    from datetime import datetime, timedelta, timezone
    u = auth(c, "trk@example.com", "password123", register=True)
    other = auth(c, "trk2@example.com", "password123", register=True)
    r = c.post("/api/applications", json={"scheme_slug": "aaby"}, headers=u)
    assert r.status_code == 201 and r.json()["documents"] >= 3          # checklist seeded from the scheme's documents
    assert c.post("/api/applications", json={"scheme_slug": "aaby"}, headers=u).status_code == 409
    assert c.post("/api/applications", json={"scheme_slug": "no-such"}, headers=u).status_code == 404
    assert c.post("/api/applications", json={"scheme_slug": "aaby"}).status_code == 401

    app = c.get("/api/applications", headers=u).json()[0]
    assert app["status"] == "not_started" and app["docs_done"] == 0 and app["docs_total"] == len(app["documents"])
    first, second = app["documents"][0]["id"], app["documents"][1]["id"]

    # $set with arrayFilters ticks exactly one item inside the embedded checklist
    assert c.patch(f"/api/applications/aaby/documents/{first}", json={"done": True}, headers=u).status_code == 200
    app = c.get("/api/applications", headers=u).json()[0]
    assert app["docs_done"] == 1 and [d["done"] for d in app["documents"][:2]] == [True, False]
    assert c.patch("/api/applications/aaby/documents/nope", json={"done": True}, headers=u).status_code == 404
    # $push / $pull on the same array
    added = c.post("/api/applications/aaby/documents", json={"name": "Ration card copy"}, headers=u).json()
    assert c.get("/api/applications", headers=u).json()[0]["docs_total"] == app["docs_total"] + 1
    assert c.delete(f"/api/applications/aaby/documents/{added['id']}", headers=u).status_code == 200
    assert c.delete(f"/api/applications/aaby/documents/{second}", headers=u).status_code == 200
    assert c.get("/api/applications", headers=u).json()[0]["docs_total"] == app["docs_total"] - 1

    # status history grows with each change ($push); bad values are rejected
    assert c.patch("/api/applications/aaby", json={"status": "applied", "note": "Submitted at LIC office"}, headers=u).status_code == 200
    assert c.patch("/api/applications/aaby", json={"status": "pending"}, headers=u).status_code == 422
    assert c.patch("/api/applications/aaby", json={"deadline": "2026-02-30"}, headers=u).status_code == 422
    hist = c.get("/api/applications", headers=u).json()[0]["history"]
    assert [h["status"] for h in hist] == ["not_started", "applied"] and hist[-1]["note"] == "Submitted at LIC office"

    # reminders: due inside the reminder window, and overdue
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=2)).strftime("%Y-%m-%d")
    c.patch("/api/applications/aaby", json={"deadline": tomorrow, "reminder_days": 3}, headers=u)
    c.post("/api/applications", json={"scheme_slug": "apy"}, headers=u)
    c.patch("/api/applications/apy", json={"deadline": (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d")}, headers=u)
    rem = c.get("/api/applications/reminders", headers=u).json()
    assert [x["scheme_slug"] for x in rem["due_soon"]] == ["aaby"] and [x["scheme_slug"] for x in rem["overdue"]] == ["apy"]
    assert rem["this_week"] == 1
    c.patch("/api/applications/aaby", json={"status": "approved"}, headers=u)          # finished: no more reminders
    assert c.get("/api/applications/reminders", headers=u).json()["due_soon"] == []
    assert c.patch("/api/applications/aaby", json={"deadline": ""}, headers=u).status_code == 200  # clear deadline

    # another user can't touch it; the database validator is the last line of defence
    assert c.patch("/api/applications/aaby", json={"status": "rejected"}, headers=other).status_code == 404
    with pytest.raises(WriteError):
        get_db().applications.insert_one({"user_id": "x", "scheme_slug": "apy", "status": "maybe", "documents": [],
                                          "history": [], "created_at": 1, "updated_at": 1})
    # deleting my data also deletes my tracker
    assert c.delete("/api/profile", headers=u).status_code == 200
    assert c.get("/api/applications", headers=u).json() == []


def test_recommendation_ranking(c):
    from api import analytics
    db = get_db()
    analytics.backfill(db)
    p = {"age": 30, "state": "Assam", "is_income_tax_payer": False, "occupation": "weaver", "gender": "female",
         "is_bpl": True, "annual_income": 80000, "is_citizen": True}
    n_eval = db.evaluations.count_documents({})
    r = c.post("/api/recommendations", json={"profile": p}).json()
    assert db.evaluations.count_documents({}) == n_eval                 # ranking previews don't write the audit log
    slugs = [i["slug"] for i in r["items"]]
    assert {"aaby", "apy"} <= set(slugs) and "ay" not in slugs           # ineligible (age 30 > 21) is never recommended
    assert [i["score"] for i in r["items"]] == sorted((i["score"] for i in r["items"]), reverse=True)
    assert set(r["groups"]) >= {"women", "poor", "workers"}
    aaby = next(i for i in r["items"] if i["slug"] == "aaby")
    assert aaby["verdict"] == "ELIGIBLE" and aaby["why"][0].startswith("You meet every required condition")
    assert abs(sum(aaby["parts"].values()) - aaby["score"]) < 0.01
    assert aaby["similar_saves"] == 0

    # two users with a similar saved profile save Atal Pension Yojana: its popularity part goes up
    for i in range(2):
        h = auth(c, f"sim{i}@example.com", "password123", register=True)
        c.put("/api/profile", json={"attributes": {"state": "Assam", "occupation": "weaver", "age": 33}, "consent": True}, headers=h)
        c.post("/api/applications", json={"scheme_slug": "apy"}, headers=h)
    r2 = c.post("/api/recommendations", json={"profile": p}).json()
    apy1 = next(i for i in r["items"] if i["slug"] == "apy")
    apy2 = next(i for i in r2["items"] if i["slug"] == "apy")
    assert apy2["similar_saves"] == 2 and apy2["parts"]["popularity"] > apy1["parts"]["popularity"]
    assert any("similar profile" in w for w in apy2["why"])

    # a citizen with a missing answer gets "needs more info" items with what to tell us
    r3 = c.post("/api/recommendations", json={"profile": {"age": 30}}).json()
    assert any(i["verdict"] == "NEEDS_MORE_INFO" and any("tell us" in w for w in i["why"]) for i in r3["items"])


def test_recommendations_vary_and_respect_audience(c):
    """Regression: every profile used to get the same generic scheme. Recommendations must depend on the person,
    skip schemes aimed at someone else, and include clearly-labelled unreviewed matches."""
    from api import analytics
    from api.services import now
    db = get_db()
    # An in-review scheme for students with a validated machine-read rule proposal.
    db.schemes.update_one({"slug": "test-scholar"}, {"$setOnInsert": {
        "slug": "test-scholar", "name": "Test Merit Scholarship For College Students", "level": "central", "state": None,
        "tags": ["scholarship"], "sections": {"eligibility": "Students with at least 60% marks."}, "status": "in_review",
        "source_url": "https://example.org/s", "current_version": None, "eligibility": None, "created_at": now()}}, upsert=True)
    db.ingestion_jobs.update_one({"scheme_slug": "test-scholar"}, {"$set": {"source_hash": "h", "stage": "in_review",
        "proposed_eligibility": {"op": "AND", "children": [{"id": "r1", "attribute": "marks_percent", "operator": ">=", "value": 60}]},
        "validation_errors": [], "unmapped_conditions": []}}, upsert=True)
    analytics.backfill(db)

    student = {"age": 20, "is_student": True, "occupation": "student", "marks_percent": 75, "is_citizen": True, "is_income_tax_payer": False}
    senior = {"age": 68, "gender": "male", "occupation": "retired", "is_student": False, "is_citizen": True,
              "is_income_tax_payer": False, "is_bpl": True}
    rs = c.post("/api/recommendations", json={"profile": student}).json()
    rr = c.post("/api/recommendations", json={"profile": senior}).json()
    s_slugs, r_slugs = [i["slug"] for i in rs["items"]], [i["slug"] for i in rr["items"]]
    assert "test-scholar" in s_slugs and "test-scholar" not in r_slugs      # a student scholarship isn't for a 68-year-old
    assert s_slugs != r_slugs
    item = next(i for i in rs["items"] if i["slug"] == "test-scholar")
    assert item["verified"] is False and any("not yet checked by a reviewer" in w for w in item["why"])
    assert rs["candidates"]["unverified"] >= 1
