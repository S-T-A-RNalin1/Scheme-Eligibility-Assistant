"""Per-scheme fixture tests: curated rule trees must give the expected verdict for each fixture profile."""
import json
from pathlib import Path

import pytest

from api.engine.evaluate import check
from api.engine.validate import validate_tree

ROOT = Path(__file__).absolute().parent.parent
CURATED = json.loads((ROOT / "data" / "curated_rules.json").read_text(encoding="utf-8"))["schemes"]
FIXTURES = json.loads((ROOT / "tests" / "fixtures" / "profiles.json").read_text(encoding="utf-8"))
CASES = [(slug, i, case) for slug, cases in FIXTURES.items() if not slug.startswith("_") for i, case in enumerate(cases)]


@pytest.mark.parametrize("slug,i,case", CASES, ids=[f"{s}-{i}" for s, i, _ in CASES])
def test_fixture_verdict(slug, i, case):
    assert check(CURATED[slug]["eligibility"], case["profile"])["verdict"] == case["expected"]


@pytest.mark.parametrize("slug", sorted(CURATED))
def test_curated_trees_are_structurally_valid(slug):
    assert validate_tree(CURATED[slug]["eligibility"]) == []
