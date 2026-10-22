"""Property-based tests (Hypothesis) over randomly generated rule trees and profiles."""
from hypothesis import given, settings
from hypothesis import strategies as st

from api.engine.evaluate import R, evaluate

ATTRS = ["a", "b", "c"]
leaf = st.builds(lambda a, op, v, i: {"id": f"r{i}", "attribute": a, "operator": op, "value": v},
                 st.sampled_from(ATTRS), st.sampled_from(["<", "<=", ">", ">=", "==", "!="]),
                 st.integers(0, 10), st.integers(0, 999))
tree = st.recursive(leaf, lambda kids: st.one_of(
    st.builds(lambda c: {"op": "AND", "children": c}, st.lists(kids, min_size=1, max_size=3)),
    st.builds(lambda c: {"op": "OR", "children": c}, st.lists(kids, min_size=1, max_size=3)),
    st.builds(lambda c: {"op": "NOT", "children": [c]}, kids)), max_leaves=8)
profile = st.dictionaries(st.sampled_from(ATTRS), st.integers(0, 10))


@settings(max_examples=300, deadline=None)
@given(tree, profile)
def test_double_negation(t, p):
    assert evaluate({"op": "NOT", "children": [{"op": "NOT", "children": [t]}]}, p).result == evaluate(t, p).result


@settings(max_examples=300, deadline=None)
@given(tree, profile, st.sampled_from(ATTRS), st.integers(0, 10))
def test_answering_a_question_never_undoes_a_decision(t, p, attr, value):
    """Adding a missing answer can resolve UNKNOWN, but never turns PASS/FAIL into UNKNOWN."""
    if attr in p:
        return
    before = evaluate(t, p).result
    after = evaluate(t, {**p, attr: value}).result
    if before != R.UNKNOWN:
        assert after == before


@settings(max_examples=300, deadline=None)
@given(tree, profile)
def test_missing_attributes_only_when_unknown(t, p):
    out = evaluate(t, p)
    assert (out.result == R.UNKNOWN) == bool(out.missing)
    assert out.missing <= set(ATTRS) - set(p)
