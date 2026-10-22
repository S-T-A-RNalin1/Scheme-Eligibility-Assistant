"""Deterministic rules engine: a small recursive interpreter over a rule tree.

A node is either a group  {"op": "AND"|"OR"|"NOT", "children": [...]}
or a leaf                 {"id", "attribute", "operator", "value", "description"}.

Three-valued logic: a missing profile answer is UNKNOWN, never FAIL.
The engine is pure (no database access), so it is trivially unit-testable.
"""
from dataclasses import dataclass, field
from enum import Enum

ENGINE_VERSION = "rules-engine@1.0.0"


class R(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


VERDICT = {R.PASS: "ELIGIBLE", R.FAIL: "INELIGIBLE", R.UNKNOWN: "NEEDS_MORE_INFO"}


@dataclass
class Outcome:
    result: R
    reasons: list = field(default_factory=list)
    missing: set = field(default_factory=set)


def _norm(x):
    return x.lower() if isinstance(x, str) else x


def _in(a, v):
    a = _norm(a)
    return a in [_norm(i) for i in v]


OPS = {
    "==": lambda a, v: _norm(a) == _norm(v),
    "!=": lambda a, v: _norm(a) != _norm(v),
    "<": lambda a, v: a < v,
    "<=": lambda a, v: a <= v,
    ">": lambda a, v: a > v,
    ">=": lambda a, v: a >= v,
    "in": _in,
    "not_in": lambda a, v: not _in(a, v),
    "between": lambda a, v: v[0] <= a <= v[1],
    "exists": lambda a, v: (a is not None) == bool(v),
}
GROUP_OPS = {"AND", "OR", "NOT"}


def _fmt(v):
    if isinstance(v, list):
        return "[" + ", ".join(map(str, v)) + "]"
    return str(v)


def eval_leaf(node: dict, profile: dict) -> Outcome:
    attr = node["attribute"]
    rid = node.get("id", attr)
    if node["operator"] != "exists" and profile.get(attr) is None:
        return Outcome(R.UNKNOWN, [{"rule_id": rid, "attribute": attr, "result": "UNKNOWN",
                                    "detail": f"Need your {attr.replace('_', ' ')}: {node.get('description', '')}"}], {attr})
    actual = profile.get(attr)
    try:
        ok = OPS[node["operator"]](actual, node["value"])
    except TypeError:  # e.g. comparing a string with a number: treat as not satisfied
        ok = False
    verb = "satisfies" if ok else "does not satisfy"
    return Outcome(R.PASS if ok else R.FAIL, [{
        "rule_id": rid, "attribute": attr, "result": "PASS" if ok else "FAIL",
        "detail": f"{attr} = {_fmt(actual)} {verb} {node['operator']} {_fmt(node['value'])} ({node.get('description', '')})",
    }])


def evaluate(node: dict, profile: dict) -> Outcome:
    if "attribute" in node:
        return eval_leaf(node, profile)
    op = node.get("op")
    if op not in GROUP_OPS:
        raise ValueError(f"Unknown group op {op!r}")
    kids = [evaluate(c, profile) for c in node.get("children", [])]
    results = [k.result for k in kids]
    reasons = [r for k in kids for r in k.reasons]
    missing = set().union(*(k.missing for k in kids)) if kids else set()
    if op == "AND":
        res = R.FAIL if R.FAIL in results else R.UNKNOWN if R.UNKNOWN in results else R.PASS
    elif op == "OR":
        res = R.PASS if R.PASS in results else R.UNKNOWN if R.UNKNOWN in results else R.FAIL
    else:  # NOT
        if len(kids) != 1:
            raise ValueError("NOT takes exactly one child")
        res = {R.PASS: R.FAIL, R.FAIL: R.PASS, R.UNKNOWN: R.UNKNOWN}[results[0]]
        # A NOT flips the meaning of its child's reasons for the end user.
        for r in reasons:
            if r["result"] in ("PASS", "FAIL"):
                r["result"] = "FAIL" if r["result"] == "PASS" else "PASS"
                r["detail"] = "Exclusion: " + r["detail"]
    if res != R.UNKNOWN:
        missing = set()  # outcome decided; don't ask questions that can't change it
    return Outcome(res, reasons, missing)


def check(eligibility: dict, profile: dict) -> dict:
    """Evaluate one scheme's rule tree and map the result to a verdict."""
    out = evaluate(eligibility, profile)
    return {"verdict": VERDICT[out.result], "reasons": out.reasons,
            "missing_attributes": sorted(out.missing)}


def next_best_question(results: list[dict]) -> str | None:
    """The missing attribute that appears in the most NEEDS_MORE_INFO verdicts."""
    counts: dict[str, int] = {}
    for r in results:
        if r["verdict"] == "NEEDS_MORE_INFO":
            for a in r["missing_attributes"]:
                counts[a] = counts.get(a, 0) + 1
    return max(counts, key=lambda a: (counts[a], a)) if counts else None
