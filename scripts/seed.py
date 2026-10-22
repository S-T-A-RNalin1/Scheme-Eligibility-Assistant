"""Seed MongoDB from the Hugging Face PDFs: parse → schemes (draft) → rule proposals
(ingestion_jobs, in_review) → publish hand-reviewed rules (transactions) → chunk + embed.

    python scripts/seed.py            # idempotent; re-running updates in place
    python scripts/seed.py --reset    # drop the database first
"""
import json
import secrets
import sys
import time
from pathlib import Path

ROOT = Path(__file__).absolute().parent.parent
sys.path.insert(0, str(ROOT))

from pymongo import UpdateOne  # noqa: E402

from api import config  # noqa: E402
from api.db import client, get_db, init_db  # noqa: E402
from api.engine.attributes import ATTRIBUTES  # noqa: E402
from api.engine.validate import validate_tree  # noqa: E402
from api.ingest.extract import propose  # noqa: E402
from api.ingest.parse import parse_all  # noqa: E402
from api.rag import embed  # noqa: E402
from api.rag.chunk import chunk_scheme  # noqa: E402
from api.rag.retrieve import load_matrix  # noqa: E402
from api.security import hash_password  # noqa: E402
from api.services import PublishError, now, publish_version  # noqa: E402


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main(reset=False):
    if reset:
        client().drop_database(config.DB_NAME)
        log(f"dropped database {config.DB_NAME}")
    db = init_db(get_db())

    db.attribute_registry.bulk_write([UpdateOne({"key": a["key"]}, {"$set": {**a, "order": i}}, upsert=True)
                                      for i, a in enumerate(ATTRIBUTES)])
    log(f"attribute_registry: {len(ATTRIBUTES)} attributes")

    parsed_path = ROOT / "data" / "schemes_parsed.json"
    if parsed_path.exists():
        schemes = json.loads(parsed_path.read_text(encoding="utf-8"))
    else:
        schemes = parse_all(ROOT / "data" / "raw_pdfs")
        parsed_path.write_text(json.dumps(schemes, ensure_ascii=False), encoding="utf-8")
    log(f"parsed {len(schemes)} schemes")

    ts = now()
    ops, jobs = [], []
    for s in schemes:
        ops.append(UpdateOne({"slug": s["slug"]}, {
            "$set": {"name": s["name"], "level": s["level"], "state": s["state"], "tags": s["tags"],
                     "sections": s["sections"], "description": s["sections"].get("description", "")[:600],
                     "source_url": s["source_url"], "source_hash": s["source_hash"], "updated_at": ts},
            "$setOnInsert": {"status": "in_review", "current_version": None, "eligibility": None,
                             "last_verified_at": None, "created_at": ts}}, upsert=True))
        p = propose(s)
        errors = validate_tree(p["eligibility"], " ".join(s["sections"].values()))
        jobs.append(UpdateOne({"scheme_slug": s["slug"], "source_hash": s["source_hash"]}, {
            "$set": {"source_url": s["source_url"], "proposed_eligibility": p["eligibility"],
                     "unmapped_conditions": p["unmapped_conditions"], "extracted_by": p["extracted_by"],
                     "validation_errors": errors, "updated_at": ts},
            "$setOnInsert": {"stage": "in_review", "attempts": 1, "error": None, "created_at": ts}}, upsert=True))
    db.schemes.bulk_write(ops, ordered=False)
    db.ingestion_jobs.bulk_write(jobs, ordered=False)
    log(f"schemes upserted; {len(jobs)} ingestion jobs with rule proposals")

    curated = json.loads((ROOT / "data" / "curated_rules.json").read_text(encoding="utf-8"))["schemes"]
    by_slug = {s["slug"]: s for s in schemes}
    published = 0
    for slug, c in curated.items():
        if slug not in by_slug:
            log(f"  skip {slug}: not in dataset")
            continue
        current = db.schemes.find_one({"slug": slug}, {"eligibility": 1})
        if current.get("eligibility") == c["eligibility"]:
            published += 1
            continue  # unchanged: don't create a redundant version
        try:
            v = publish_version(db, slug, c["eligibility"], reviewed_by="reviewer:curator", change_note=c["change_note"],
                                extracted_by="human", unmapped_conditions=c.get("unmapped_conditions", []),
                                source_text=" ".join(by_slug[slug]["sections"].values()))
            db.ingestion_jobs.update_many({"scheme_slug": slug}, {"$set": {"stage": "published", "approved_unedited": False}})
            published += 1
            log(f"  published {slug} v{v}")
        except PublishError as e:
            log(f"  REJECTED {slug}: {e}")
    log(f"{published} curated schemes published")
    from api import analytics
    log(f"coverage analytics: {analytics.backfill(db)} schemes tagged with beneficiary groups; {len(analytics.REGIONS)} regions loaded")

    chunks = [c for s in schemes for c in chunk_scheme(s)]
    embed.fit([c["embed_text"] for c in chunks])
    vecs = embed.embed([c["embed_text"] for c in chunks])
    db.document_chunks.delete_many({})
    status = {d["slug"]: d.get("current_version") for d in db.schemes.find({}, {"slug": 1, "current_version": 1})}
    for c, v in zip(chunks, vecs):
        c["embedding"] = [round(float(x), 6) for x in v]
        c["embedding_model"] = embed.EMBEDDING_MODEL
        c["scheme_version"] = status.get(c["scheme_slug"])
    for i in range(0, len(chunks), 500):
        db.document_chunks.insert_many(chunks[i:i + 500], ordered=False)
    load_matrix(db, force=True)
    log(f"document_chunks: {len(chunks)} chunks embedded ({embed.DIMS}-d, {embed.EMBEDDING_MODEL})")

    creds = {}
    for email, role in (("admin@example.org", "admin"), ("user@example.org", "user")):
        if not db.users.find_one({"email": email}):
            pw = secrets.token_urlsafe(9)
            db.users.insert_one({"email": email, "name": role.title() + " Demo", "password_hash": hash_password(pw),
                                 "role": role, "auth_provider": "password", "created_at": now()})
            creds[email] = pw
    if creds:
        env = ROOT / ".env.demo"
        env.write_text("".join(f"{e}={p}\n" for e, p in creds.items()), encoding="utf-8")
        log(f"demo users created; passwords written to {env.name} (local demo only)")
    log("done")


if __name__ == "__main__":
    main(reset="--reset" in sys.argv)
