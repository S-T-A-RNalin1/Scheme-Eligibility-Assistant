import itertools

import pytest

from api.engine.evaluate import R, check, evaluate, next_best_question

# Leaves that deterministically produce PASS / FAIL / UNKNOWN for the profile {"x": 1}
LEAF = {
    R.PASS: {"id": "p", "attribute": "x", "operator": "==", "value": 1},
    R.FAIL: {"id": "f", "attribute": "x", "operator": "==", "value": 2},
    R.UNKNOWN: {"id": "u", "attribute": "missing", "operator": "==", "value": 1},
}
PROFILE = {"x": 1}

AND_TABLE = {(R.PASS, R.PASS): R.PASS, (R.PASS, R.FAIL): R.FAIL, (R.PASS, R.UNKNOWN): R.UNKNOWN,
             (R.FAIL, R.FAIL): R.FAIL, (R.FAIL, R.UNKNOWN): R.FAIL, (R.UNKNOWN, R.UNKNOWN): R.UNKNOWN}
OR_TABLE = {(R.PASS, R.PASS): R.PASS, (R.PASS, R.FAIL): R.PASS, (R.PASS, R.UNKNOWN): R.PASS,
            (R.FAIL, R.FAIL): R.FAIL, (R.FAIL, R.UNKNOWN): R.UNKNOWN, (R.UNKNOWN, R.UNKNOWN): R.UNKNOWN}


@pytest.mark.parametrize("a,b", list(itertools.product(LEAF, LEAF)))
def test_and_truth_table(a, b):
    expected = AND_TABLE.get((a, b)) or AND_TABLE[(b, a)]
    assert evaluate({"op": "AND", "children": [LEAF[a], LEAF[b]]}, PROFILE).result == expected


@pytest.mark.parametrize("a,b", list(itertools.product(LEAF, LEAF)))
def test_or_truth_table(a, b):
    expected = OR_TABLE.get((a, b)) or OR_TABLE[(b, a)]
    assert evaluate({"op": "OR", "children": [LEAF[a], LEAF[b]]}, PROFILE).result == expected


@pytest.mark.parametrize("a,expected", [(R.PASS, R.FAIL), (R.FAIL, R.PASS), (R.UNKNOWN, R.UNKNOWN)])
def test_not(a, expected):
    assert evaluate({"op": "NOT", "children": [LEAF[a]]}, PROFILE).result == expected


def test_fail_short_circuits_missing_questions():
    out = evaluate({"op": "AND", "children": [LEAF[R.FAIL], LEAF[R.UNKNOWN]]}, PROFILE)
    assert out.result == R.FAIL and out.missing == set()


def test_unknown_reports_missing_attribute():
    res = check({"op": "AND", "children": [LEAF[R.PASS], LEAF[R.UNKNOWN]]}, PROFILE)
    assert res["verdict"] == "NEEDS_MORE_INFO" and res["missing_attributes"] == ["missing"]


def test_every_rule_returns_a_reason():
    tree = {"op": "AND", "children": [LEAF[R.PASS], {"op": "NOT", "children": [LEAF[R.FAIL]]}]}
    res = check(tree, PROFILE)
    assert res["verdict"] == "ELIGIBLE"
    assert [r["rule_id"] for r in res["reasons"]] == ["p", "f"]
    assert res["reasons"][1]["detail"].startswith("Exclusion")


@pytest.mark.parametrize("op,value,actual,ok", [
    ("<", 5, 4, True), ("<=", 5, 5, True), (">", 5, 5, False), (">=", 5, 5, True), ("!=", "a", "b", True),
    ("in", ["SC", "ST"], "sc", True), ("not_in", ["SC"], "OBC", True), ("between", [18, 40], 41, False),
    ("between", [18, 40], 18, True), ("==", "Female", "female", True),
])
def test_operators(op, value, actual, ok):
    leaf = {"id": "r", "attribute": "a", "operator": op, "value": value}
    assert evaluate(leaf, {"a": actual}).result == (R.PASS if ok else R.FAIL)


def test_type_mismatch_is_fail_not_crash():
    assert evaluate({"id": "r", "attribute": "a", "operator": "<", "value": 5}, {"a": "abc"}).result == R.FAIL


def test_unknown_group_op_raises():
    with pytest.raises(ValueError):
        evaluate({"op": "XOR", "children": [LEAF[R.PASS]]}, PROFILE)


def test_next_best_question_picks_most_frequent():
    results = [{"verdict": "NEEDS_MORE_INFO", "missing_attributes": ["age", "income"]},
               {"verdict": "NEEDS_MORE_INFO", "missing_attributes": ["age"]},
               {"verdict": "ELIGIBLE", "missing_attributes": []}]
    assert next_best_question(results) == "age"
    assert next_best_question([]) is None
