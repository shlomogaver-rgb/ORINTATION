"""Former holdout (23, 25) - now regression after the generic fixes their first blind run exposed."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from document import build_document  # noqa: E402

D = ROOT / "tests" / "documents" / "regression_ex_holdout"
EXP = json.loads((D / "expected_structure.json").read_text(encoding="utf-8"))
PDFS = [k for k in EXP if k.endswith(".pdf")]


@pytest.fixture(scope="module")
def models():
    return {n: build_document((D / n).read_bytes()) for n in PDFS}


@pytest.mark.parametrize("name", PDFS)
def test_structure(models, name):
    m, e = models[name], EXP[name]
    roles = {p.index: p.role.value for p in m.pages}
    assert [q.number for q in m.questions] == list(range(1, e["questions"] + 1)) and not m.warnings
    assert all(roles[p] == "RESPONSE_WORKSPACE" for p in e["workspace_pages"])
    assert all(roles[p] == "ADMINISTRATIVE" for p in e.get("admin_pages", []))
    for v in e["visuals"]:
        q = next(q for q in m.questions if q.number == v["question"])
        on = [o for o in q.visual_objects if o.page == v["page"]]
        assert on and all(o.visual_role.value != "DECORATIVE" for o in q.visual_objects)
        if v["kind"] == "OPTION_GROUP":
            assert any(o.semantic_model.get("type") == "GraphOptionGroup" and len(o.semantic_model["options"]) == v["options"] for o in on)
    for t in e.get("response_templates", []):
        q = next(q for q in m.questions if q.number == t["question"])
        assert any(r.page == t["page"] and r.visual_role.value in ("ANSWER_BOX", "RESPONSE_TEMPLATE") for r in q.response_regions)
