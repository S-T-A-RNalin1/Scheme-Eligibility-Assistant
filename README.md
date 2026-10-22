# Scheme Eligibility Assistant (MongoDB)

A web app that tells an Indian citizen which government schemes they qualify for, **why** (a reason for every rule), and answers free-form questions **only from official scheme text, with citations**. Built as a NoSQL database project on MongoDB.

> The language model never decides eligibility. A deterministic, versioned rules engine does, and every decision is stored as a self-contained, checksummed MongoDB document.

## Highlights
- **Document model**: one `schemes` document per scheme, with a nested AND/OR/NOT eligibility tree.
- **Immutable versions**: each published rule set is a `scheme_versions` document, written in a **multi-document transaction**.
- **Audit log**: each check is an `evaluations` document that embeds the profile and rule snapshots plus a SHA-256 checksum, so any change to it is detectable.
- **Integrity without foreign keys**: JSON Schema validators, unique and compound indexes, Pydantic validation, and a publish-time rule validator.
- **Three-valued engine**: PASS / FAIL / UNKNOWN become Eligible / Ineligible / Needs more info, plus the "next best question".
- **Hybrid retrieval**: vector similarity plus a MongoDB `$text` index, merged with Reciprocal Rank Fusion. `$vectorSearch` is used on Atlas.
- **Other MongoDB features**: TTL indexes (chat logs, rate limits), aggregation dashboards, and JWT auth with user/admin roles.

## Pages and roles
- `/` is the public site: eligibility check, Ask, scheme browser, and the Grievance Portal (filing a grievance needs a citizen login).
- `/login` is the sign-in page, with separate **Citizen** and **Admin** tabs. The server checks that the account's role matches the tab. Only citizens can register; admin accounts are created by `seed.py`.
- `/admin` is the officer dashboard: overview stats, **coverage gap analytics** and the grievance queue. Every admin API call also requires the admin role server-side.

## Application tracker (citizens)
- **Saving a scheme:** "Save to tracker" (on a recommendation, a result or a scheme page) creates one `applications` document per user and scheme. A unique index on `{user_id, scheme_slug}` prevents duplicates.
- **What's tracked:**
  - Your own status (Not started, Applied, Approved, Rejected), clearly labelled as **not** the official government status.
  - A deadline, and how many days before it you want a reminder.
  - Notes.
  - A documents checklist, seeded from the scheme's "Documents Required" text.
- **NoSQL:**
  - The checklist and the status history are embedded arrays.
  - Ticking an item uses `$set` with `arrayFilters`; adding uses `$push` and removing uses `$pull`.
  - Reminders come from one aggregation (`$dateDiff` + `$facet`: due soon, overdue, this week).
- **Privacy:** deleting your profile also deletes your tracker.

## Recommendation ranking
- **What decides what:** the rules engine decides what's possible, and ineligible schemes are never recommended. A MongoDB aggregation then ranks the rest:
  - **60%** share of conditions met,
  - **25%** match between the scheme's beneficiary groups and yours (`$setIntersection`),
  - **15%** how many users with a similar saved profile saved the scheme (`$lookup` on `applications`).
- **Explanations:** each result shows its score breakdown and plain "why" lines.
- **No audit noise:** ranking previews don't write audit records.

## Scheme coverage gap analytics
- **Supply:** each scheme is tagged with beneficiary groups (women, SC/ST, farmers, students and so on), using its text and its rule tree.
- **Demand:** Ask questions and scheme searches are logged in `search_logs` with their state, their groups and the number of matching schemes. These logs expire after 180 days through a TTL index.
- **Aggregations:**
  - `$facet` computes supply and demand by state and group in one pass.
  - `$bucket` puts states into bands by scheme count, and searches into bands by number of matches.
  - `$group` / `$unwind` build the state × group matrix and find unmet search topics.
- **Map:** states/UTs are stored as GeoJSON points in `regions` with a `2dsphere` index. "Nearby states" uses `$geoNear`. The map (Leaflet + OpenStreetMap) needs an internet connection; the tables work offline.
- **Regions are states/UTs**, because the myScheme dataset has no district-level schemes.
- **Demo data:** `python scripts/simulate_searches.py` adds flagged demo searches for the dashboard, and `--clear` removes them.

## Run it (Windows, local MongoDB 8.x)
```powershell
pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File scripts\start_mongo.ps1   # replica set rs0 on :27018
$env:HF_TOKEN="<token>"; python scripts\download_hf.py              # 601 PDFs from shrijayan/gov_myscheme
python scripts\seed.py                                              # parse, propose rules, publish curated, embed
uvicorn api.main:app --port 8000                                    # http://127.0.0.1:8000  (API docs: /docs)
pytest -q
```
Demo accounts are created by `seed.py`, and their passwords are written to `.env.demo` (local only, git-ignored).

## Layout
```
api/        FastAPI app (main.py), db.py (validators + indexes), services.py (publish txn, check, replay),
            analytics.py (coverage gaps: groups, regions, search logs, $facet/$bucket/$geoNear)
api/engine/ evaluate.py (rules engine), validate.py (publish gate), attributes.py (registry)
api/ingest/ parse.py (PDF -> sections), extract.py (rule proposals with source quotes)
api/rag/    chunk.py, embed.py (LSA 256-d), retrieve.py (vector + text + RRF), answer.py (routing, grounding)
web/        index.html (public site), login.html, admin.html; common.js shared by all three
scripts/    download_hf.py, seed.py, collect_results.py, screenshots.py, start_mongo.ps1
tests/      engine truth tables, Hypothesis properties, fixtures, validator, API end-to-end
docs/       report (.docx) and slides (.pptx) generators, diagrams, results.json
```

## Measured results
These come from `scripts/collect_results.py` and are stored in `docs/results.json`:
- 112 tests pass, and fixture verdict accuracy is 100% (35/35).
- A check across all published schemes takes about 15 ms (median), including the audit write.
- Indexed queries examine 15–347 documents instead of 5,295 (`FETCH ← IXSCAN`).
- Retrieval Recall@5 on named questions: hybrid 1.00, vector 0.97. On descriptive paraphrases: vector 0.81, hybrid 0.70.

Data source: myScheme (myscheme.gov.in) via the Hugging Face dataset `shrijayan/gov_myscheme`. This is an academic project, not an official service, so always verify results on the official portal.
