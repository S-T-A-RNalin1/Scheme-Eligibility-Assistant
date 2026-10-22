from api.engine.validate import validate_tree

SRC = "The applicant must be between 18 and 40 years of age. Family income should not exceed Rs. 2.5 lakh per annum."


def leaf(**kw):
    base = {"id": "r1", "attribute": "age", "operator": "between", "value": [18, 40], "description": "age"}
    return {**base, **kw}


def test_valid_tree_passes():
    tree = {"op": "AND", "children": [leaf(source_quote="must be between 18 and 40 years of age"),
                                      leaf(id="r2", attribute="annual_income", operator="<=", value=250000,
                                           source_quote="should not exceed Rs. 2.5 lakh per annum")]}
    assert validate_tree(tree, SRC) == []


def test_unknown_attribute_rejected():
    assert "not in attribute_registry" in validate_tree(leaf(attribute="shoe_size"))[0]


def test_unknown_operator_rejected():
    assert "unknown operator" in validate_tree(leaf(operator="~="))[0]


def test_operator_type_mismatch():
    assert any("needs a number" in e for e in validate_tree(leaf(attribute="gender", operator=">=", value=1)))


def test_bad_enum_value():
    assert any("not valid options" in e for e in validate_tree(leaf(attribute="category", operator="in", value=["Martian"])))


def test_invented_quote_rejected():
    errs = validate_tree(leaf(source_quote="applicants must own a yacht"), SRC)
    assert any("possible invented rule" in e for e in errs)


def test_number_must_appear_in_quote():
    errs = validate_tree(leaf(value=[18, 45], source_quote="must be between 18 and 40 years of age"), SRC)
    assert any("value 45.0 does not appear" in e for e in errs)


def test_contradiction_detected():
    tree = {"op": "AND", "children": [leaf(operator=">=", value=60), leaf(id="r2", operator="<=", value=18)]}
    assert any("contradiction" in e for e in validate_tree(tree))


def test_not_needs_one_child_and_groups_need_children():
    assert any("exactly one child" in e for e in validate_tree({"op": "NOT", "children": [leaf(), leaf(id="r2")]}))
    assert any("no children" in e for e in validate_tree({"op": "AND", "children": []}))
