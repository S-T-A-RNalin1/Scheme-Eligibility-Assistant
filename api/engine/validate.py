"""Publish-time validation of rule trees (the integrity Postgres FKs would have given us)."""
import re

from .attributes import BY_KEY
from .evaluate import GROUP_OPS, OPS

NUMERIC_OPS = {"<", "<=", ">", ">=", "between"}
SET_OPS = {"in", "not_in"}


def _leaves(node):
    if "attribute" in node:
        yield node
    else:
        for c in node.get("children", []):
            yield from _leaves(c)


def validate_tree(tree: dict, source_text: str | None = None) -> list[str]:
    """Return a list of human-readable problems; empty list means the tree is publishable."""
    errors: list[str] = []

    def walk(node, path="root"):
        if "attribute" in node:
            attr, op, val = node.get("attribute"), node.get("operator"), node.get("value", None)
            spec = BY_KEY.get(attr)
            if not spec:
                errors.append(f"{path}: attribute '{attr}' is not in attribute_registry")
                return
            if op not in OPS:
                errors.append(f"{path}: unknown operator '{op}'")
                return
            if "value" not in node:
                errors.append(f"{path}: missing value")
                return
            t = spec["type"]
            if op in NUMERIC_OPS and t != "number":
                errors.append(f"{path}: operator '{op}' needs a number attribute, '{attr}' is {t}")
            if op == "between" and not (isinstance(val, list) and len(val) == 2 and val[0] <= val[1]):
                errors.append(f"{path}: 'between' needs [min, max] with min <= max")
            if op in SET_OPS and not isinstance(val, list):
                errors.append(f"{path}: '{op}' needs a list value")
            if t == "enum":
                options = {o.lower() for o in spec["options"]}
                vals = val if isinstance(val, list) else [val]
                bad = [v for v in vals if str(v).lower() not in options]
                if bad:
                    errors.append(f"{path}: {bad} not valid options for '{attr}'")
            if t == "boolean" and op in ("==", "!=") and not isinstance(val, bool):
                errors.append(f"{path}: '{attr}' is boolean, value must be true/false")
            if not node.get("id"):
                errors.append(f"{path}: leaf has no id")
            quote = node.get("source_quote")
            if source_text and quote:
                if _squash(quote) not in _squash(source_text):
                    errors.append(f"{path}: source_quote not found in source text (possible invented rule)")
                else:
                    for num in _numbers(val):
                        if num not in _numbers_in(quote):
                            errors.append(f"{path}: value {num} does not appear in its source_quote")
            return
        op = node.get("op")
        if op not in GROUP_OPS:
            errors.append(f"{path}: unknown group op '{op}'")
            return
        kids = node.get("children") or []
        if not kids:
            errors.append(f"{path}: {op} group has no children")
        if op == "NOT" and len(kids) != 1:
            errors.append(f"{path}: NOT must have exactly one child")
        for i, c in enumerate(kids):
            walk(c, f"{path}.{op}[{i}]")

    walk(tree)
    errors.extend(_contradictions(tree))
    return errors


def _contradictions(tree) -> list[str]:
    """Detect impossible numeric ranges among leaves directly under the top-level AND."""
    if tree.get("op") != "AND":
        return []
    lo, hi = {}, {}
    for leaf in tree.get("children", []):
        if "attribute" not in leaf:
            continue
        a, op, v = leaf["attribute"], leaf["operator"], leaf.get("value")
        if op in (">=", ">"):
            lo[a] = max(lo.get(a, float("-inf")), v)
        elif op in ("<=", "<"):
            hi[a] = min(hi.get(a, float("inf")), v)
        elif op == "between":
            lo[a] = max(lo.get(a, float("-inf")), v[0])
            hi[a] = min(hi.get(a, float("inf")), v[1])
    return [f"contradiction: {a} must be >= {lo[a]} and <= {hi[a]}" for a in lo if a in hi and lo[a] > hi[a]]


def _squash(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _numbers(val) -> list[float]:
    vals = val if isinstance(val, list) else [val]
    return [float(v) for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)]


def _numbers_in(quote: str) -> set[float]:
    nums = set()
    for m in re.finditer(r"\d[\d,]*(?:\.\d+)?", quote):
        n = float(m.group().replace(",", ""))
        nums.add(n)
        tail = quote[m.end():m.end() + 8].lower()
        if "lakh" in tail:
            nums.add(n * 100000)
        if "crore" in tail:
            nums.add(n * 10000000)
    return nums


def leaves(tree):
    return list(_leaves(tree))
