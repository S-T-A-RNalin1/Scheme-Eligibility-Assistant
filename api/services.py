"""Domain services that touch the database: publishing versions, running checks, replay."""
import hashlib
import json
import uuid
from datetime import datetime, timezone

from bson import ObjectId

from .db import client, supports_transactions
from .engine.evaluate import ENGINE_VERSION, check, next_best_question
from .engine.validate import validate_tree


def now():
    # BSON dates have millisecond precision; truncate so checksums survive a round trip.
    t = datetime.now(timezone.utc)
    return t.replace(microsecond=t.microsecond // 1000 * 1000)


class PublishError(ValueError):
    pass


def publish_version(db, slug: str, eligibility: dict, *, reviewed_by: str, change_note: str,
                    extracted_by: str = "human", unmapped_conditions=None, source_text: str | None = None) -> int:
    """Validate, then insert a new immutable scheme_version and point the scheme at it — atomically."""
    errors = validate_tree(eligibility, source_text)
    if errors:
        raise PublishError("; ".join(errors))
    scheme = db.schemes.find_one({"slug": slug}, {"current_version": 1, "source_hash": 1})
    if not scheme:
        raise PublishError(f"unknown scheme {slug}")

    def _write(session=None):
        last = db.scheme_versions.find_one({"scheme_slug": slug}, sort=[("version", -1)], session=session)
        version = (last["version"] + 1) if last else 1
        ts = now()
        db.scheme_versions.insert_one({
            "scheme_slug": slug, "version": version, "eligibility": eligibility,
            "unmapped_conditions": unmapped_conditions or [], "effective_from": ts,
            "source_snapshot_hash": scheme.get("source_hash"), "extracted_by": extracted_by,
            "reviewed_by": reviewed_by, "change_note": change_note, "created_at": ts,
        }, session=session)
        db.schemes.update_one({"slug": slug}, {"$set": {
            "eligibility": eligibility, "unmapped_conditions": unmapped_conditions or [],
            "current_version": version, "status": "published", "last_verified_at": ts, "updated_at": ts,
        }}, session=session)
        db.ingestion_jobs.update_many({"scheme_slug": slug}, {"$set": {"stage": "published", "updated_at": ts}}, session=session)
        return version

    if supports_transactions():
        with client().start_session() as s:
            return s.with_transaction(lambda sess: _write(sess))
    return _write()


def _checksum(doc: dict) -> str:
    payload = {k: doc[k] for k in ("run_id", "scheme_slug", "scheme_version", "engine_version",
                                   "profile_snapshot", "rules_snapshot", "verdict", "reasons", "missing_attributes")}
    payload["evaluated_at"] = doc["evaluated_at"].isoformat()
    raw = json.dumps(payload, sort_keys=True, default=str).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def candidate_filter(profile: dict) -> dict:
    """Cheap pre-filter in Mongo: published schemes that are central or from the user's state."""
    f = {"status": "published"}
    if profile.get("state"):
        f["$or"] = [{"level": "central"}, {"state": profile["state"]}]
    return f


def run_check(db, profile: dict, user_id: ObjectId | None = None, slugs: list[str] | None = None,
              write_audit: bool = True) -> dict:
    """Evaluate every candidate scheme, write the audit log, return grouped results."""
    profile = {k: v for k, v in profile.items() if v is not None and v != ""}
    query = candidate_filter(profile)
    if slugs:
        query["slug"] = {"$in": slugs}
    schemes = list(db.schemes.find(query, {"slug": 1, "name": 1, "level": 1, "state": 1, "eligibility": 1,
                                           "current_version": 1, "unmapped_conditions": 1, "source_url": 1,
                                           "last_verified_at": 1, "tags": 1}))
    run_id = "run_" + uuid.uuid4().hex[:20]
    ts = now()
    results, audit = [], []
    for s in schemes:
        res = check(s["eligibility"], profile)
        used = {k: profile[k] for k in _attributes(s["eligibility"]) if k in profile}
        doc = {
            "user_id": user_id, "run_id": run_id, "scheme_slug": s["slug"], "scheme_version": s["current_version"],
            "engine_version": ENGINE_VERSION, "evaluated_at": ts, "profile_snapshot": used,
            "rules_snapshot": s["eligibility"], **res,
        }
        doc["checksum"] = _checksum(doc)
        audit.append(doc)
        results.append({"slug": s["slug"], "name": s["name"], "level": s["level"], "state": s.get("state"),
                        "source_url": s.get("source_url"), "scheme_version": s["current_version"],
                        "unmapped_conditions": s.get("unmapped_conditions", []),
                        "last_verified_at": s.get("last_verified_at"), "tags": s.get("tags", []), **res})
    if audit and write_audit:  # previews (e.g. ranking) skip the audit log; real checks always write it
        db.evaluations.insert_many(audit, ordered=False)
    group = lambda v: [r for r in results if r["verdict"] == v]
    return {
        "run_id": run_id, "evaluated": len(results), "eligible": group("ELIGIBLE"),
        "needs_more_info": group("NEEDS_MORE_INFO"), "ineligible": group("INELIGIBLE"),
        "next_question": next_best_question(results),
    }


def replay(db, evaluation_id: str) -> dict:
    """Re-run a stored evaluation from its own snapshots and check tamper-evidence."""
    doc = db.evaluations.find_one({"_id": ObjectId(evaluation_id)})
    if not doc:
        raise KeyError(evaluation_id)
    res = check(doc["rules_snapshot"], doc["profile_snapshot"])
    stored = {k: doc[k] for k in doc if k != "_id"}
    return {"evaluation_id": evaluation_id, "stored_verdict": doc["verdict"], "replayed_verdict": res["verdict"],
            "verdict_matches": res["verdict"] == doc["verdict"],
            "checksum_valid": _checksum(stored) == doc["checksum"], "scheme_version": doc["scheme_version"]}


def _attributes(node) -> set:
    if "attribute" in node:
        return {node["attribute"]}
    return set().union(*(_attributes(c) for c in node.get("children", []))) if node.get("children") else set()
