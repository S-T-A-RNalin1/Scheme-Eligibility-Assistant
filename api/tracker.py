"""Application tracker: a citizen's own record of schemes they saved and how their application is going.

One document per (user, scheme) in `applications`. The documents checklist and the status history are
embedded arrays, updated in place with $set + arrayFilters, $push and $pull. Status here is what the
citizen records for themselves; it is never presented as an official government status.
"""
import re
import uuid
from datetime import datetime, timedelta, timezone

from pymongo import ASCENDING, DESCENDING

from .ingest.extract import sentences

STATUSES = ["not_started", "applied", "approved", "rejected"]
OPEN_STATUSES = ["not_started", "applied"]

APPLICATION_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["user_id", "scheme_slug", "status", "documents", "history", "created_at", "updated_at"],
        "properties": {
            "status": {"enum": STATUSES},
            "deadline": {"bsonType": ["date", "null"]},
            "reminder_days": {"bsonType": "int", "minimum": 0, "maximum": 60},
            "notes": {"bsonType": "string", "maxLength": 2000},
            "documents": {"bsonType": "array", "maxItems": 40, "items": {
                "bsonType": "object", "required": ["id", "name", "done"],
                "properties": {"id": {"bsonType": "string"}, "name": {"bsonType": "string", "minLength": 2, "maxLength": 160},
                               "done": {"bsonType": "bool"}}}},
            "history": {"bsonType": "array", "items": {"bsonType": "object", "required": ["at", "status"]}},
        },
    }
}


def ensure_indexes(db):
    if "applications" not in db.list_collection_names():
        db.create_collection("applications", validator=APPLICATION_VALIDATOR, validationLevel="strict")
    else:
        db.command("collMod", "applications", validator=APPLICATION_VALIDATOR, validationLevel="strict")
    db.applications.create_index([("user_id", ASCENDING), ("scheme_slug", ASCENDING)], unique=True)
    db.applications.create_index([("user_id", ASCENDING), ("deadline", ASCENDING)])
    db.applications.create_index([("scheme_slug", ASCENDING), ("user_id", ASCENDING)])  # "saved by" counts
    db.applications.create_index([("user_id", ASCENDING), ("updated_at", DESCENDING)])


def _now():
    t = datetime.now(timezone.utc)
    return t.replace(microsecond=t.microsecond // 1000 * 1000)


def checklist_from_text(text: str, limit: int = 12) -> list[str]:
    """Turn a scheme's 'Documents Required' prose into checklist items.

    The scraped text often runs items together ("Aadhaar CardFirst page of Passbook"), so we also
    split where a lower-case letter is directly followed by a capitalised word.
    """
    if not text:
        return []
    text = re.sub(r"(?<=[a-z)\]])(?=[A-Z][a-z])", "\n", text)
    parts = []
    for line in re.split(r"[\n;•]+", text):
        parts.extend(sentences(line) or [line])
    items, seen = [], set()
    for p in parts:
        p = re.sub(r"^\s*(\d+[.)]|[-–•*])\s*", "", p)
        p = re.sub(r"(?<=[.)])\s*\d{1,2}$", "", p.strip()).strip(" .:,")  # "...proof of identity.2" -> next item's number
        key = p.lower()
        if 3 <= len(p) <= 160 and key not in seen and not key.startswith(("note", "the following", "documents required")):
            seen.add(key)
            items.append(p)
    # Many pages list a short heading followed by a sentence explaining it; keep the headings.
    short = [i for i in items if len(i) <= 60]
    if len(short) >= 3:
        items = short
    return items[:limit]


def new_doc(name: str) -> dict:
    return {"id": uuid.uuid4().hex[:10], "name": name.strip()[:160], "done": False, "done_at": None}


def save(db, user_id, scheme: dict) -> dict:
    ts = _now()
    docs = [new_doc(n) for n in checklist_from_text((scheme.get("sections") or {}).get("documents", ""))]
    doc = {"user_id": user_id, "scheme_slug": scheme["slug"], "scheme_name": scheme["name"], "status": "not_started",
           "deadline": None, "reminder_days": 3, "notes": "", "documents": docs,
           "history": [{"at": ts, "status": "not_started", "note": "Saved to tracker"}], "created_at": ts, "updated_at": ts}
    db.applications.insert_one(doc)
    return doc


def update(db, user_id, slug: str, status=None, deadline=..., reminder_days=None, notes=None, note: str = "") -> bool:
    ts = _now()
    sets, push = {"updated_at": ts}, None
    current = db.applications.find_one({"user_id": user_id, "scheme_slug": slug}, {"status": 1})
    if not current:
        return False
    if status and status != current["status"]:
        sets["status"] = status
        push = {"history": {"at": ts, "status": status, "note": note or ""}}
    if deadline is not ...:
        sets["deadline"] = deadline
    if reminder_days is not None:
        sets["reminder_days"] = int(reminder_days)
    if notes is not None:
        sets["notes"] = notes
    upd = {"$set": sets}
    if push:
        upd["$push"] = push
    db.applications.update_one({"user_id": user_id, "scheme_slug": slug}, upd)
    return True


def set_doc_done(db, user_id, slug: str, doc_id: str, done: bool) -> bool:
    # arrayFilters updates exactly the matching checklist item inside the embedded array.
    r = db.applications.update_one(
        {"user_id": user_id, "scheme_slug": slug},
        {"$set": {"documents.$[d].done": done, "documents.$[d].done_at": _now() if done else None, "updated_at": _now()}},
        array_filters=[{"d.id": doc_id}])
    return r.matched_count == 1 and bool(db.applications.find_one(
        {"user_id": user_id, "scheme_slug": slug, "documents.id": doc_id}, {"_id": 1}))


def add_doc(db, user_id, slug: str, name: str) -> dict | None:
    d = new_doc(name)
    r = db.applications.update_one({"user_id": user_id, "scheme_slug": slug},
                                   {"$push": {"documents": d}, "$set": {"updated_at": _now()}})
    return d if r.matched_count else None


def remove_doc(db, user_id, slug: str, doc_id: str) -> bool:
    r = db.applications.update_one({"user_id": user_id, "scheme_slug": slug},
                                   {"$pull": {"documents": {"id": doc_id}}, "$set": {"updated_at": _now()}})
    return r.modified_count == 1


def _with_progress(match: dict) -> list:
    """Shared pipeline stages: documents done/total and whole days left until the deadline."""
    return [
        {"$match": match},
        {"$addFields": {
            "docs_total": {"$size": "$documents"},
            "docs_done": {"$size": {"$filter": {"input": "$documents", "cond": "$$this.done"}}},
            "days_left": {"$cond": [{"$eq": [{"$ifNull": ["$deadline", None]}, None]}, None,
                                    {"$dateDiff": {"startDate": "$$NOW", "endDate": "$deadline", "unit": "day"}}]},
        }},
    ]


def list_for(db, user_id) -> list[dict]:
    pipeline = _with_progress({"user_id": user_id}) + [
        # Open applications with the nearest deadline first; no deadline after; finished ones last.
        {"$addFields": {"_open": {"$in": ["$status", OPEN_STATUSES]},
                        "_dl": {"$ifNull": ["$deadline", datetime(9999, 1, 1, tzinfo=timezone.utc)]}}},
        {"$sort": {"_open": -1, "_dl": 1, "updated_at": -1}},
        {"$project": {"_id": 0, "user_id": 0, "_open": 0, "_dl": 0}},
    ]
    return list(db.applications.aggregate(pipeline))


def reminders(db, user_id) -> dict:
    """Deadlines inside each application's own reminder window, overdue ones, and this week's count."""
    pipeline = _with_progress({"user_id": user_id, "status": {"$in": OPEN_STATUSES}, "deadline": {"$ne": None}}) + [
        {"$facet": {
            "due_soon": [{"$match": {"$expr": {"$and": [{"$gte": ["$days_left", 0]}, {"$lte": ["$days_left", "$reminder_days"]}]}}},
                         {"$sort": {"deadline": 1}},
                         {"$project": {"_id": 0, "scheme_slug": 1, "scheme_name": 1, "deadline": 1, "days_left": 1,
                                       "docs_done": 1, "docs_total": 1}}],
            "overdue": [{"$match": {"days_left": {"$lt": 0}}}, {"$sort": {"deadline": 1}},
                        {"$project": {"_id": 0, "scheme_slug": 1, "scheme_name": 1, "deadline": 1, "days_left": 1}}],
            "this_week": [{"$match": {"days_left": {"$gte": 0, "$lte": 7}}}, {"$count": "n"}],
        }},
    ]
    r = next(db.applications.aggregate(pipeline))
    r["this_week"] = r["this_week"][0]["n"] if r["this_week"] else 0
    return r


def parse_deadline(value: str | None):
    if not value:
        return None
    d = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if not (datetime(2000, 1, 1, tzinfo=timezone.utc) <= d <= datetime.now(timezone.utc) + timedelta(days=3650)):
        raise ValueError("deadline out of range")
    return d + timedelta(hours=23, minutes=59)  # end of the chosen day
