"""FastAPI application: REST + SSE endpoints and the static web UI."""
import json
import time
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pymongo.errors import DuplicateKeyError, WriteError

from . import analytics, config, tracker
from .db import get_db, init_db, supports_transactions
from .engine.attributes import ATTRIBUTES
from .models import (ChatIn, CheckIn, DocAddIn, DocDoneIn, GrievanceCommentIn, GrievanceIn, GrievanceStatusIn,
                     LoginIn, ProfileIn, RecommendIn, RegisterIn, TrackSaveIn, TrackUpdateIn)
from .rag.answer import answer
from .recommend import recommend
from .security import hash_password, make_token, optional_user, require_admin, require_user, verify_password
from .services import now, run_check

app = FastAPI(title="Scheme Eligibility Assistant", version="1.0.0",
              description="Explainable scheme eligibility checks and grounded Q&A on MongoDB.")
api = APIRouter(prefix="/api")


def db():
    return get_db()


@app.on_event("startup")
def _startup():
    d = init_db()
    analytics.ensure_indexes(d)
    tracker.ensure_indexes(d)


def _jsonable(doc):
    if isinstance(doc, list):
        return [_jsonable(d) for d in doc]
    if isinstance(doc, dict):
        return {k: _jsonable(v) for k, v in doc.items()}
    if isinstance(doc, ObjectId):
        return str(doc)
    if isinstance(doc, datetime):
        return doc.isoformat()
    return doc


@app.exception_handler(WriteError)
def _write_error(_, exc: WriteError):
    # Document failed the collection's JSON Schema validator.
    return JSONResponse(status_code=422, content={"detail": "Rejected by database validator", "code": exc.code})


# ------------------------------------------------------------------------- public
@api.get("/health")
def health():
    t = time.perf_counter()
    get_db().command("ping")
    return {"status": "ok", "db_ping_ms": round((time.perf_counter() - t) * 1000, 2),
            "replica_set": supports_transactions(), "llm": bool(config.ANTHROPIC_API_KEY)}


@api.get("/attributes")
def attributes():
    return list(db().attribute_registry.find({}, {"_id": 0}).sort("order", 1)) or ATTRIBUTES


SCHEME_LIST_FIELDS = {"slug": 1, "name": 1, "level": 1, "state": 1, "tags": 1, "status": 1, "current_version": 1,
                      "last_verified_at": 1, "source_url": 1, "_id": 0}


@api.get("/schemes")
def list_schemes(q: str | None = Query(None, max_length=100), level: str | None = Query(None, pattern="^(central|state)$"),
                 state: str | None = None, tag: str | None = None, status: str | None = Query(None, pattern="^(draft|in_review|published|retired)$"),
                 page: int = Query(1, ge=1, le=1000), size: int = Query(20, ge=1, le=100)):
    f = {"status": status} if status else {"status": {"$ne": "retired"}}
    if level:
        f["level"] = level
    if state:
        f["state"] = state
    if tag:
        f["tags"] = tag.lower()
    proj, sort = dict(SCHEME_LIST_FIELDS), [("status", -1), ("name", 1)]
    if q:
        f["$text"] = {"$search": q}
        proj["score"] = {"$meta": "textScore"}
        sort = [("score", {"$meta": "textScore"})]
    total = db().schemes.count_documents(f)
    items = list(db().schemes.find(f, proj).sort(sort).skip((page - 1) * size).limit(size))
    if q and page == 1:  # one demand signal per search, not per page turned
        analytics.log_search(db(), q, "browse", total, state=state)
    return {"total": total, "page": page, "size": size, "items": _jsonable(items)}


@api.get("/schemes/names")
def scheme_names():
    """Slug + name of every live scheme, for pickers (covered query: served from the projection only)."""
    docs = db().schemes.find({"status": {"$ne": "retired"}}, {"_id": 0, "slug": 1, "name": 1}).sort("name", 1)
    return list(docs)


@api.get("/schemes/{slug}")
def scheme_detail(slug: str):
    s = db().schemes.find_one({"slug": slug}, {"_id": 0})
    if not s:
        raise HTTPException(404, "Scheme not found")
    versions = list(db().scheme_versions.find({"scheme_slug": slug}, {"_id": 0, "eligibility": 0}).sort("version", -1))
    lv = s.get("last_verified_at")
    s["stale"] = bool(lv and datetime.now(timezone.utc) - lv > timedelta(days=config.STALE_AFTER_DAYS))
    job = db().ingestion_jobs.find_one({"scheme_slug": slug}, {"_id": 0, "stage": 1, "validation_errors": 1})
    return _jsonable({**s, "versions": versions, "ingestion": job})


# ------------------------------------------------------------------------- eligibility
@api.post("/eligibility/check")
def eligibility_check(body: CheckIn, user=Depends(optional_user)):
    if body.use_saved_profile:
        if not user:
            raise HTTPException(401, "Login required to use a saved profile")
        saved = db().user_profiles.find_one({"user_id": user["_id"]})
        profile = saved["attributes"] if saved else {}
    else:
        profile = body.profile.clean() if body.profile else {}
    t = time.perf_counter()
    res = run_check(db(), profile, user_id=user["_id"] if user else None)
    res["elapsed_ms"] = round((time.perf_counter() - t) * 1000, 1)
    res["ineligible_count"] = len(res["ineligible"])
    return _jsonable(res)


@api.get("/eligibility/runs/{run_id}")
def run_results(run_id: str, user=Depends(optional_user)):
    docs = list(db().evaluations.find({"run_id": run_id}, {"rules_snapshot": 0}))
    if not docs:
        raise HTTPException(404, "Run not found")
    owner = docs[0].get("user_id")
    if owner and (not user or (user["_id"] != owner and user.get("role") != "admin")):
        raise HTTPException(403, "Not your run")
    return _jsonable(docs)


@api.get("/eligibility/history")
def history(user=Depends(require_user), limit: int = Query(20, ge=1, le=100)):
    pipeline = [
        {"$match": {"user_id": user["_id"]}},
        {"$sort": {"evaluated_at": -1}},
        {"$group": {"_id": "$run_id", "evaluated_at": {"$first": "$evaluated_at"},
                    "eligible": {"$sum": {"$cond": [{"$eq": ["$verdict", "ELIGIBLE"]}, 1, 0]}},
                    "needs_more_info": {"$sum": {"$cond": [{"$eq": ["$verdict", "NEEDS_MORE_INFO"]}, 1, 0]}},
                    "ineligible": {"$sum": {"$cond": [{"$eq": ["$verdict", "INELIGIBLE"]}, 1, 0]}}}},
        {"$sort": {"evaluated_at": -1}}, {"$limit": limit},
    ]
    return _jsonable(list(db().evaluations.aggregate(pipeline)))


# ------------------------------------------------------------------------- auth + profile
@api.post("/auth/register", status_code=201)
def register(body: RegisterIn):
    try:
        uid = db().users.insert_one({"email": body.email.lower(), "name": body.name, "password_hash": hash_password(body.password),
                                     "role": "user", "auth_provider": "password", "created_at": now()}).inserted_id
    except DuplicateKeyError:
        raise HTTPException(409, "Email already registered")
    user = db().users.find_one({"_id": uid})
    return {"token": make_token(user), "user": {"email": user["email"], "name": user["name"], "role": user["role"]}}


@api.post("/auth/login")
def login(body: LoginIn):
    user = db().users.find_one({"email": body.email.lower()})
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(401, "Invalid email or password")
    if body.as_role == "admin" and user["role"] != "admin":
        raise HTTPException(403, "This is not an admin account. Please use the Citizen login.")
    if body.as_role == "citizen" and user["role"] == "admin":
        raise HTTPException(403, "Admin accounts sign in on the Admin tab.")
    return {"token": make_token(user), "user": {"email": user["email"], "name": user.get("name", ""), "role": user["role"]}}


@api.get("/auth/me")
def me(user=Depends(require_user)):
    return _jsonable({"email": user["email"], "name": user.get("name", ""), "role": user["role"]})


@api.get("/profile")
def get_profile(user=Depends(require_user)):
    p = db().user_profiles.find_one({"user_id": user["_id"]}, {"_id": 0, "user_id": 0})
    return _jsonable(p or {"attributes": {}, "consent": {"store_profile": False}})


@api.put("/profile")
def put_profile(body: ProfileIn, user=Depends(require_user)):
    if not body.consent:
        raise HTTPException(400, "Consent is required to store your profile; you can still check without saving")
    ts = now()
    db().user_profiles.update_one({"user_id": user["_id"]}, {"$set": {
        "attributes": body.attributes.clean(), "consent": {"store_profile": True, "given_at": ts}, "updated_at": ts}}, upsert=True)
    return {"saved": True}


@api.delete("/profile")
def delete_profile(user=Depends(require_user)):
    p = db().user_profiles.delete_one({"user_id": user["_id"]}).deleted_count
    e = db().evaluations.delete_many({"user_id": user["_id"]}).deleted_count
    db().applications.delete_many({"user_id": user["_id"]})
    return {"deleted_profile": p, "deleted_evaluations": e}


# ------------------------------------------------------------------------- application tracker
def _tracked(user, slug: str) -> dict:
    a = db().applications.find_one({"user_id": user["_id"], "scheme_slug": slug}, {"_id": 1})
    if not a:
        raise HTTPException(404, "This scheme is not in your tracker")
    return a


@api.get("/applications")
def list_applications(user=Depends(require_user)):
    return _jsonable(tracker.list_for(db(), user["_id"]))


@api.get("/applications/reminders")
def application_reminders(user=Depends(require_user)):
    return _jsonable(tracker.reminders(db(), user["_id"]))


@api.post("/applications", status_code=201)
def save_application(body: TrackSaveIn, user=Depends(require_user)):
    scheme = db().schemes.find_one({"slug": body.scheme_slug, "status": {"$ne": "retired"}}, {"slug": 1, "name": 1, "sections.documents": 1})
    if not scheme:
        raise HTTPException(404, "Unknown scheme")
    try:
        doc = tracker.save(db(), user["_id"], scheme)
    except DuplicateKeyError:
        raise HTTPException(409, "Already in your tracker")
    return {"scheme_slug": doc["scheme_slug"], "documents": len(doc["documents"])}


@api.patch("/applications/{slug}")
def update_application(slug: str, body: TrackUpdateIn, user=Depends(require_user)):
    _tracked(user, slug)
    kw = {}
    if "deadline" in body.model_fields_set:
        try:
            kw["deadline"] = tracker.parse_deadline(body.deadline)
        except ValueError:
            raise HTTPException(422, "Deadline must be a real date within the next 10 years")
    tracker.update(db(), user["_id"], slug, status=body.status, reminder_days=body.reminder_days, notes=body.notes,
                   note=body.note, **kw)
    return {"updated": slug}


@api.delete("/applications/{slug}")
def remove_application(slug: str, user=Depends(require_user)):
    _tracked(user, slug)
    db().applications.delete_one({"user_id": user["_id"], "scheme_slug": slug})
    return {"removed": slug}


@api.post("/applications/{slug}/documents", status_code=201)
def add_application_document(slug: str, body: DocAddIn, user=Depends(require_user)):
    _tracked(user, slug)
    d = tracker.add_doc(db(), user["_id"], slug, body.name)
    return _jsonable(d)


@api.patch("/applications/{slug}/documents/{doc_id}")
def tick_application_document(slug: str, doc_id: str, body: DocDoneIn, user=Depends(require_user)):
    _tracked(user, slug)
    if not tracker.set_doc_done(db(), user["_id"], slug, doc_id, body.done):
        raise HTTPException(404, "No such document in this checklist")
    return {"doc_id": doc_id, "done": body.done}


@api.delete("/applications/{slug}/documents/{doc_id}")
def remove_application_document(slug: str, doc_id: str, user=Depends(require_user)):
    _tracked(user, slug)
    if not tracker.remove_doc(db(), user["_id"], slug, doc_id):
        raise HTTPException(404, "No such document in this checklist")
    return {"removed": doc_id}


# ------------------------------------------------------------------------- recommendations
@api.post("/recommendations")
def recommendations(body: RecommendIn, user=Depends(optional_user)):
    profile = body.profile.clean() if body.profile else {}
    if body.use_saved_profile and user:
        saved = db().user_profiles.find_one({"user_id": user["_id"]})
        profile = saved["attributes"] if saved else {}
    return _jsonable(recommend(db(), profile, user_id=user["_id"] if user else None))


# ------------------------------------------------------------------------- grievances
GRIEVANCE_PUBLIC = {"_id": 0, "user_id": 0}


def _next_ticket() -> str:
    """Atomic per-year counter: findOneAndUpdate with $inc never hands out the same number twice."""
    year = datetime.now(timezone.utc).year
    doc = db().counters.find_one_and_update({"_id": f"grievance-{year}"}, {"$inc": {"seq": 1}},
                                            upsert=True, return_document=True)
    return f"GRV-{year}-{doc['seq']:06d}"


def _grievance_for(ticket: str, user: dict) -> dict:
    g = db().grievances.find_one({"ticket": ticket})
    if not g:
        raise HTTPException(404, "Grievance not found")
    if g["user_id"] != user["_id"] and user.get("role") != "admin":
        raise HTTPException(403, "Not your grievance")
    return g


@api.post("/grievances", status_code=201)
def file_grievance(body: GrievanceIn, user=Depends(require_user)):
    scheme = db().schemes.find_one({"slug": body.scheme_slug}, {"name": 1})
    if not scheme:
        raise HTTPException(404, "Unknown scheme")
    if body.run_id and not db().evaluations.find_one({"run_id": body.run_id, "user_id": user["_id"]}, {"_id": 1}):
        raise HTTPException(400, "That eligibility check is not in your history")
    ts = now()
    doc = {"ticket": _next_ticket(), "user_id": user["_id"], "scheme_slug": body.scheme_slug, "scheme_name": scheme["name"],
           "category": body.category, "subject": body.subject.strip(), "description": body.description.strip(),
           "run_id": body.run_id, "status": "open", "priority": "normal", "created_at": ts, "updated_at": ts,
           "resolved_at": None,
           "timeline": [{"at": ts, "by": "user", "action": "filed", "note": "Grievance filed", "status": "open"}]}
    db().grievances.insert_one(doc)
    return {"ticket": doc["ticket"], "status": "open"}


@api.get("/grievances")
def my_grievances(user=Depends(require_user)):
    docs = db().grievances.find({"user_id": user["_id"]}, GRIEVANCE_PUBLIC).sort("created_at", -1).limit(50)
    return _jsonable(list(docs))


@api.get("/grievances/{ticket}")
def grievance_detail(ticket: str, user=Depends(require_user)):
    g = _grievance_for(ticket, user)
    return _jsonable({k: v for k, v in g.items() if k not in GRIEVANCE_PUBLIC})


@api.post("/grievances/{ticket}/comments")
def comment_grievance(ticket: str, body: GrievanceCommentIn, user=Depends(require_user)):
    g = _grievance_for(ticket, user)
    by = "admin" if user.get("role") == "admin" and g["user_id"] != user["_id"] else "user"
    ts = now()
    entry = {"at": ts, "by": by, "action": "comment", "note": body.note.strip()}
    update = {"$push": {"timeline": entry}, "$set": {"updated_at": ts}}
    if body.reopen and by == "user" and g["status"] in ("resolved", "closed"):
        entry.update(action="reopened", status="open")
        update["$set"].update(status="open", resolved_at=None)
    db().grievances.update_one({"ticket": ticket}, update)
    return {"ticket": ticket, "status": update["$set"].get("status", g["status"])}


# ------------------------------------------------------------------------- chat
def _rate_limit(request: Request):
    key = f"chat:{request.client.host if request.client else 'anon'}"
    window = int(time.time() // 60)
    doc = db().rate_limits.find_one_and_update(
        {"key": key, "window": window},
        {"$inc": {"n": 1}, "$setOnInsert": {"expires_at": datetime.now(timezone.utc) + timedelta(minutes=2)}},
        upsert=True, return_document=True)
    if doc["n"] > config.CHAT_RATE_LIMIT_PER_MIN:
        raise HTTPException(429, "Too many questions; please wait a minute")


@api.post("/chat")
def chat(body: ChatIn, request: Request, user=Depends(optional_user)):
    _rate_limit(request)
    profile = body.profile.clean() if body.profile else {}
    if not profile and user:
        saved = db().user_profiles.find_one({"user_id": user["_id"]})
        profile = saved["attributes"] if saved else {}
    res = answer(db(), body.question, profile)
    if res["route"] != "off_topic":
        unmatched = res["answer"].startswith(("I don't have reliable", "I couldn't find"))
        matched = 0 if unmatched else len({c["scheme_slug"] for c in res.get("citations", [])} | {e["slug"] for e in res.get("eligibility", [])})
        analytics.log_search(db(), body.question, "ask", matched, state=profile.get("state"))
    db().chat_logs.insert_one({"user_id": user["_id"] if user else None, "question": body.question, "route": res["route"],
                               "cited": [c["scheme_slug"] for c in res["citations"]], "created_at": now()})
    res = _jsonable(res)
    if not body.stream:
        return res

    def events():
        # Stream the answer word by word, then the citations as a final event.
        yield f"event: meta\ndata: {json.dumps({'route': res['route']})}\n\n"
        for token in res["answer"].split(" "):
            yield f"data: {json.dumps(token + ' ')}\n\n"
            time.sleep(0.012)
        yield f"event: done\ndata: {json.dumps({k: res.get(k) for k in ('citations', 'sources', 'eligibility')}, ensure_ascii=False)}\n\n"
    return StreamingResponse(events(), media_type="text/event-stream")


# ------------------------------------------------------------------------- admin
admin = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])


@admin.get("/grievances")
def admin_grievances(status: str | None = Query(None, pattern="^(open|in_progress|resolved|closed)$"),
                     page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100)):
    match = {"status": status} if status else {}
    pipeline = [
        {"$match": match},
        {"$sort": {"updated_at": -1}}, {"$skip": (page - 1) * size}, {"$limit": size},
        # $lookup joins the filer's email for the officer's view (the user document stays the source of truth).
        {"$lookup": {"from": "users", "localField": "user_id", "foreignField": "_id", "as": "filer",
                     "pipeline": [{"$project": {"_id": 0, "email": 1, "name": 1}}]}},
        {"$set": {"filer": {"$first": "$filer"}}},
        {"$project": {"_id": 0, "user_id": 0}},
    ]
    return _jsonable({"total": db().grievances.count_documents(match), "items": list(db().grievances.aggregate(pipeline))})


@admin.post("/grievances/{ticket}/status")
def update_grievance(ticket: str, body: GrievanceStatusIn, user=Depends(require_admin)):
    g = db().grievances.find_one({"ticket": ticket}, {"status": 1})
    if not g:
        raise HTTPException(404, "Grievance not found")
    ts = now()
    sets = {"status": body.status, "updated_at": ts}
    if body.priority:
        sets["priority"] = body.priority
    if body.status in ("resolved", "closed") and g["status"] not in ("resolved", "closed"):
        sets["resolved_at"] = ts
    elif body.status in ("open", "in_progress"):
        sets["resolved_at"] = None
    entry = {"at": ts, "by": "admin", "action": "status_change", "note": body.note.strip(), "status": body.status,
             "officer": user["email"]}
    db().grievances.update_one({"ticket": ticket}, {"$set": sets, "$push": {"timeline": entry}})
    return {"ticket": ticket, "status": body.status}


@admin.get("/coverage")
def coverage():
    return _jsonable(analytics.coverage_report(db()))


@admin.get("/coverage/nearby")
def coverage_nearby(state: str = Query(..., max_length=60), km: int = Query(600, ge=50, le=3000)):
    if state not in analytics.REGIONS:
        raise HTTPException(404, "Unknown state / UT")
    return analytics.nearby(db(), state, km)


@admin.post("/schemes/{slug}/retire")
def retire(slug: str):
    r = db().schemes.update_one({"slug": slug}, {"$set": {"status": "retired", "updated_at": now()}})
    if not r.matched_count:
        raise HTTPException(404, "Scheme not found")
    return {"retired": slug}




@admin.get("/stats")
def stats():
    d = db()
    verdicts = list(d.evaluations.aggregate([{"$group": {"_id": "$verdict", "n": {"$sum": 1}}}, {"$sort": {"n": -1}}]))
    top_schemes = list(d.evaluations.aggregate([
        {"$group": {"_id": {"scheme": "$scheme_slug", "verdict": "$verdict"}, "n": {"$sum": 1}}},
        {"$group": {"_id": "$_id.scheme", "verdicts": {"$push": {"k": "$_id.verdict", "v": "$n"}}, "total": {"$sum": "$n"}}},
        {"$project": {"total": 1, "verdicts": {"$arrayToObject": "$verdicts"}}}, {"$sort": {"total": -1}}, {"$limit": 10}]))
    missing = list(d.evaluations.aggregate([
        {"$match": {"verdict": "NEEDS_MORE_INFO"}}, {"$unwind": "$missing_attributes"},
        {"$group": {"_id": "$missing_attributes", "n": {"$sum": 1}}}, {"$sort": {"n": -1}}, {"$limit": 8}]))
    by_state = list(d.schemes.aggregate([
        {"$group": {"_id": {"$ifNull": ["$state", "Central"]},
                    "published": {"$sum": {"$cond": [{"$eq": ["$status", "published"]}, 1, 0]}}, "total": {"$sum": 1}}},
        {"$sort": {"total": -1}}, {"$limit": 12}]))
    routes = list(d.chat_logs.aggregate([{"$group": {"_id": "$route", "n": {"$sum": 1}}}]))
    grievances = list(d.grievances.aggregate([
        {"$facet": {
            "by_status": [{"$group": {"_id": "$status", "n": {"$sum": 1}}}, {"$sort": {"n": -1}}],
            "by_category": [{"$group": {"_id": "$category", "n": {"$sum": 1}}}, {"$sort": {"n": -1}}],
            "resolution": [{"$match": {"resolved_at": {"$ne": None}}},
                           {"$group": {"_id": None, "n": {"$sum": 1},
                                       "avg_hours": {"$avg": {"$divide": [{"$subtract": ["$resolved_at", "$created_at"]}, 3600000]}}}}],
        }}]))[0]
    counts = {c: d[c].estimated_document_count() for c in ["schemes", "scheme_versions", "document_chunks", "evaluations",
                                                           "users", "user_profiles", "applications", "grievances", "chat_logs"]}
    return _jsonable({"counts": counts, "verdicts": verdicts, "top_schemes": top_schemes, "most_missing": missing,
                      "schemes_by_state": by_state, "chat_routes": routes, "grievances": grievances})


app.include_router(api)
app.include_router(admin)

WEB = config.ROOT / "web"
app.mount("/static", StaticFiles(directory=WEB), name="static")


@app.middleware("http")
async def no_stale_ui(request: Request, call_next):
    # The UI changes often during development: make browsers re-validate the page and its assets.
    response = await call_next(request)
    if request.url.path in ("/", "/login", "/admin") or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(WEB / "index.html")


@app.get("/login", include_in_schema=False)
def login_page():
    return FileResponse(WEB / "login.html")


@app.get("/admin", include_in_schema=False)
def admin_page():
    # The page itself is static; every admin API call it makes is checked server-side with require_admin.
    return FileResponse(WEB / "admin.html")
