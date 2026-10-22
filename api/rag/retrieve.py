"""Hybrid retrieval: vector similarity + keyword search, merged with Reciprocal Rank Fusion."""
import threading

import numpy as np

from .. import config
from . import embed

RRF_K = 60
_cache = {"ids": None, "matrix": None, "meta": None}
_lock = threading.Lock()


def _scope_filter(state: str | None) -> dict:
    return {"$or": [{"level": "central"}, {"state": state}]} if state else {}


def atlas_available(db) -> bool:
    if config.USE_ATLAS_SEARCH in ("true", "false"):
        return config.USE_ATLAS_SEARCH == "true"
    try:
        return any(ix.get("name") == "chunks_vector" for ix in db.document_chunks.list_search_indexes())
    except Exception:
        return False


def load_matrix(db, force=False):
    """In-memory vector index used when Atlas Vector Search is unavailable (self-hosted Mongo)."""
    with _lock:
        if _cache["matrix"] is None or force:
            docs = list(db.document_chunks.find({}, {"embedding": 1, "level": 1, "state": 1}))
            _cache["ids"] = [d["_id"] for d in docs]
            _cache["matrix"] = np.array([d["embedding"] for d in docs], dtype=np.float32) if docs else np.zeros((0, embed.DIMS))
            _cache["meta"] = [(d["level"], d.get("state")) for d in docs]
    return _cache


def vector_search(db, question: str, state: str | None = None, limit: int = 20) -> list[dict]:
    q = embed.embed([question])[0]
    if atlas_available(db):
        stage = {"index": "chunks_vector", "path": "embedding", "queryVector": q.tolist(),
                 "numCandidates": 200, "limit": limit}
        if state:
            stage["filter"] = {"$or": [{"level": "central"}, {"state": state}]}
        return list(db.document_chunks.aggregate([{"$vectorSearch": stage},
                                                  {"$project": {"embedding": 0, "embed_text": 0},
                                                   }, {"$addFields": {"score": {"$meta": "vectorSearchScore"}}}]))
    c = load_matrix(db)
    if not len(c["ids"]):
        return []
    sims = c["matrix"] @ q
    if state:
        mask = np.array([lvl == "central" or st == state for lvl, st in c["meta"]])
        sims = np.where(mask, sims, -1.0)
    top = np.argsort(-sims)[:limit]
    ids = [c["ids"][i] for i in top]
    docs = {d["_id"]: d for d in db.document_chunks.find({"_id": {"$in": ids}}, {"embedding": 0, "embed_text": 0})}
    out = []
    for i in top:
        d = docs.get(c["ids"][i])
        if d:
            d["score"] = float(sims[i])
            out.append(d)
    return out


def keyword_search(db, question: str, state: str | None = None, limit: int = 20) -> list[dict]:
    if atlas_available(db):
        pipeline = [{"$search": {"index": "chunks_search", "text": {"query": question, "path": ["text", "scheme_name", "scheme_slug"]}}},
                    {"$limit": limit}, {"$project": {"embedding": 0, "embed_text": 0}},
                    {"$addFields": {"score": {"$meta": "searchScore"}}}]
        return list(db.document_chunks.aggregate(pipeline))
    query = {"$text": {"$search": question}, **_scope_filter(state)}
    return list(db.document_chunks.find(query, {"score": {"$meta": "textScore"}, "embedding": 0, "embed_text": 0})
                .sort([("score", {"$meta": "textScore"})]).limit(limit))


def rrf(*ranked_lists: list[dict], k: int = RRF_K) -> list[dict]:
    scores, docs = {}, {}
    for lst in ranked_lists:
        for rank, d in enumerate(lst):
            scores[d["_id"]] = scores.get(d["_id"], 0.0) + 1.0 / (k + rank + 1)
            docs.setdefault(d["_id"], d)
    order = sorted(scores, key=scores.get, reverse=True)
    return [{**docs[i], "rrf": scores[i]} for i in order]


def hybrid_search(db, question: str, state: str | None = None, top_k: int = 6, mode: str = "hybrid") -> list[dict]:
    vec = vector_search(db, question, state) if mode in ("hybrid", "vector") else []
    kw = keyword_search(db, question, state) if mode in ("hybrid", "keyword") else []
    fused = rrf(vec, kw)
    for d in fused:
        d["_vector_hit"] = any(v["_id"] == d["_id"] for v in vec[:10])
        d["_keyword_hit"] = any(x["_id"] == d["_id"] for x in kw)
    best_vec = vec[0]["score"] if vec else 0.0
    return fused[:top_k], {"best_vector_score": best_vec, "keyword_hits": len(kw)}
