"""MongoDB connection, collection validators and indexes."""
from pymongo import ASCENDING, DESCENDING, MongoClient, TEXT
from pymongo.errors import OperationFailure

from . import config

_client: MongoClient | None = None


def client() -> MongoClient:
    global _client
    if _client is None:
        _client = MongoClient(config.MONGODB_URI, tz_aware=True, serverSelectionTimeoutMS=5000)
    return _client


def get_db():
    return client()[config.DB_NAME]


def supports_transactions() -> bool:
    hello = client().admin.command("hello")
    return bool(hello.get("setName") or hello.get("msg") == "isdbgrid")


# --- JSON Schema validators: the database itself rejects malformed documents ---------------

RULE_LEAF = {
    "bsonType": "object",
    "required": ["id", "attribute", "operator", "value"],
    "properties": {
        "id": {"bsonType": "string"},
        "attribute": {"bsonType": "string"},
        "operator": {"enum": ["==", "!=", "<", "<=", ">", ">=", "in", "not_in", "between", "exists"]},
        "description": {"bsonType": "string"},
    },
}

SCHEME_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["slug", "name", "level", "status", "source_url"],
        "properties": {
            "slug": {"bsonType": "string", "pattern": "^[a-z0-9()\\-]+$"},
            "name": {"bsonType": "string", "minLength": 3},
            "level": {"enum": ["central", "state"]},
            "state": {"bsonType": ["string", "null"]},
            "status": {"enum": ["draft", "in_review", "published", "retired"]},
            "current_version": {"bsonType": ["int", "null"]},
            "tags": {"bsonType": "array", "items": {"bsonType": "string"}},
            "eligibility": {
                "bsonType": ["object", "null"],
                "properties": {"op": {"enum": ["AND", "OR", "NOT"]}, "children": {"bsonType": "array"}},
            },
        },
    }
}

EVALUATION_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["run_id", "scheme_slug", "scheme_version", "engine_version", "evaluated_at",
                     "profile_snapshot", "rules_snapshot", "verdict", "reasons", "checksum"],
        "properties": {
            "verdict": {"enum": ["ELIGIBLE", "INELIGIBLE", "NEEDS_MORE_INFO"]},
            "scheme_version": {"bsonType": "int"},
            "checksum": {"bsonType": "string", "pattern": "^sha256:"},
            "reasons": {"bsonType": "array"},
        },
    }
}

PROFILE_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["user_id", "attributes", "consent"],
        "properties": {
            "attributes": {
                "bsonType": "object",
                "properties": {
                    "age": {"bsonType": ["double", "int", "null"], "minimum": 0, "maximum": 120},
                    "annual_income": {"bsonType": ["double", "int", "long", "null"], "minimum": 0},
                    "land_holding_hectares": {"bsonType": ["double", "int", "null"], "minimum": 0},
                },
            },
            "consent": {"bsonType": "object", "required": ["store_profile"]},
        },
    }
}

USER_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["email", "password_hash", "role"],
        "properties": {
            "email": {"bsonType": "string", "pattern": "^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$"},
            "role": {"enum": ["user", "admin"]},
        },
    }
}

GRIEVANCE_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["ticket", "user_id", "scheme_slug", "category", "subject", "description", "status", "timeline",
                     "created_at", "updated_at"],
        "properties": {
            "ticket": {"bsonType": "string", "pattern": "^GRV-[0-9]{4}-[0-9]{6}$"},
            "category": {"enum": ["eligibility_result", "application_status", "documents", "benefit_not_received",
                                  "wrong_information", "portal_issue", "other"]},
            "status": {"enum": ["open", "in_progress", "resolved", "closed"]},
            "priority": {"enum": ["low", "normal", "high"]},
            "subject": {"bsonType": "string", "minLength": 5, "maxLength": 120},
            "description": {"bsonType": "string", "minLength": 20, "maxLength": 3000},
            "run_id": {"bsonType": ["string", "null"]},
            "timeline": {"bsonType": "array", "minItems": 1, "items": {
                "bsonType": "object", "required": ["at", "by", "action"],
                "properties": {"by": {"enum": ["user", "admin"]},
                               "action": {"enum": ["filed", "comment", "status_change", "reopened"]}}}},
        },
    }
}

VALIDATORS = {
    "schemes": SCHEME_VALIDATOR,
    "evaluations": EVALUATION_VALIDATOR,
    "user_profiles": PROFILE_VALIDATOR,
    "users": USER_VALIDATOR,
    "grievances": GRIEVANCE_VALIDATOR,
}


def init_db(db=None):
    """Create collections with validators and all indexes. Idempotent."""
    db = db if db is not None else get_db()
    existing = set(db.list_collection_names())
    for name in ["schemes", "scheme_versions", "document_chunks", "users", "user_profiles",
                 "evaluations", "ingestion_jobs", "attribute_registry", "chat_logs", "rate_limits",
                 "grievances", "counters"]:
        validator = VALIDATORS.get(name)
        if name not in existing:
            db.create_collection(name, **({"validator": validator, "validationLevel": "strict"} if validator else {}))
        elif validator:
            db.command("collMod", name, validator=validator, validationLevel="strict")

    db.schemes.create_index([("slug", ASCENDING)], unique=True)
    db.schemes.create_index([("status", ASCENDING), ("level", ASCENDING), ("state", ASCENDING)])
    db.schemes.create_index([("tags", ASCENDING)])
    db.schemes.create_index([("name", TEXT), ("description", TEXT), ("tags", TEXT)],
                            weights={"name": 10, "tags": 5, "description": 1}, name="schemes_text")
    db.scheme_versions.create_index([("scheme_slug", ASCENDING), ("version", DESCENDING)], unique=True)
    db.evaluations.create_index([("user_id", ASCENDING), ("evaluated_at", DESCENDING)])
    db.evaluations.create_index([("run_id", ASCENDING)])
    db.evaluations.create_index([("scheme_slug", ASCENDING), ("scheme_version", ASCENDING)])
    db.document_chunks.create_index([("scheme_slug", ASCENDING), ("chunk_index", ASCENDING)], unique=True)
    db.document_chunks.create_index([("level", ASCENDING), ("state", ASCENDING)])
    db.document_chunks.create_index([("text", TEXT), ("scheme_name", TEXT)], weights={"scheme_name": 5, "text": 1},
                                    name="chunks_text")
    db.users.create_index([("email", ASCENDING)], unique=True)
    db.user_profiles.create_index([("user_id", ASCENDING)], unique=True)
    db.ingestion_jobs.create_index([("scheme_slug", ASCENDING), ("source_hash", ASCENDING)], unique=True)
    db.ingestion_jobs.create_index([("stage", ASCENDING), ("updated_at", DESCENDING)])
    db.attribute_registry.create_index([("key", ASCENDING)], unique=True)
    db.grievances.create_index([("ticket", ASCENDING)], unique=True)
    db.grievances.create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])
    db.grievances.create_index([("status", ASCENDING), ("updated_at", DESCENDING)])
    db.grievances.create_index([("scheme_slug", ASCENDING)])
    # TTL index: chat logs and rate-limit counters expire automatically (data minimisation).
    db.chat_logs.create_index([("created_at", ASCENDING)], expireAfterSeconds=30 * 24 * 3600)
    db.rate_limits.create_index([("expires_at", ASCENDING)], expireAfterSeconds=0)
    db.rate_limits.create_index([("key", ASCENDING), ("window", ASCENDING)], unique=True)
    return db


def create_atlas_search_indexes(db=None, dims: int = 256):
    """On MongoDB Atlas, create the vector + full-text search indexes from the build guide."""
    db = db if db is not None else get_db()
    try:
        db.command({"createSearchIndexes": "document_chunks", "indexes": [
            {"name": "chunks_vector", "type": "vectorSearch", "definition": {"fields": [
                {"type": "vector", "path": "embedding", "numDimensions": dims, "similarity": "cosine"},
                {"type": "filter", "path": "level"}, {"type": "filter", "path": "state"},
                {"type": "filter", "path": "scheme_slug"}]}},
            {"name": "chunks_search", "definition": {"mappings": {"dynamic": False, "fields": {
                "text": {"type": "string"}, "scheme_slug": {"type": "string"}, "scheme_name": {"type": "string"}}}}},
        ]})
        return True
    except OperationFailure:
        return False  # self-hosted server without mongot: app falls back automatically
