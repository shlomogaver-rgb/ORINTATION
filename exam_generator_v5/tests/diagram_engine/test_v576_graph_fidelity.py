"""V5.7.6 graph SOURCE FIDELITY: real teacher/Bagrut crops + wrong-graph and swapped-option negatives."""
from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "diagram_engine" / "acceptance"))
import diagram_engine as de  # noqa: E402
from diagram_engine.graph import fidelity as F  # noqa: E402

FX = ROOT / "tests" / "diagram_engine" / "acceptance" / "fixtures"
H1 = ROOT / "tests" / "acceptance_real" / "teacher_holdout_1"
pytest.importorskip("cv2")


def _render(spec):
    return de.render_spec(de.process("s", json.dumps(spec, ensure_ascii=False), "", None).spec)[1]


def _crop(png, bbox):
    from PIL import Image
    im = Image.open(io.BytesIO(png))
    W, H = im.size
    y0, x0, y1, x1 = bbox
    b = io.BytesIO()
    im.crop((int(x0 / 1000 * W), int(y0 / 1000 * H), int(x1 / 1000 * W), int(y1 / 1000 * H))).save(b, format="PNG")
    return b.getvalue()


@pytest.mark.parametrize("case", ["A04_formula_no_construction", "A01_qualitative"])
def test_real_single_graphs_are_source_faithful(case):
    from cases import CASES
    src = (FX / CASES[case]["fixture"]).read_bytes()
    res = F.check(src, _render(CASES[case]["spec"]), 1)
    assert res["decision"] == "PASS", res


def test_real_teacher_option_group_I_to_IV_bound_and_faithful():
    spec_ = importlib.util.spec_from_file_location("h1", H1 / "content.py")
    H = importlib.util.module_from_spec(spec_)
    spec_.loader.exec_module(H)
    src = _crop((H1 / "h2_abs_options.png").read_bytes(), H.QUESTIONS[1]["figures"][0]["bbox"])
    res = F.check(src, _render(H.SPECS[2][0]), 4)
    assert res["source_panels"] == res["render_panels"] == 4
    assert [o["decision"] for o in res["per_option"]] == ["PASS"] * 4


def _fspec(expr):
    return {"diagram_type": "graph", "confidence": 0.95, "labels": [{"text": "x", "confidence": 1}, {"text": "y", "confidence": 1}],
            "graph": {"axes": {"x_min": -3, "x_max": 3, "y_min": -6, "y_max": 6, "show_grid": False, "show_numbers": False},
                      "curves": [{"id": "f", "expression": expr}]}, "observed": {"num_curves": 1}}


@pytest.mark.parametrize("src_expr,rec_expr", [("x^2+1", "-x^2-1"), ("x^3", "-x^3"), ("exp(x)", "-exp(x)"), ("1/x", "-1/x")])
def test_plausible_but_different_graph_is_blocked(src_expr, rec_expr):
    src = _render(_fspec(src_expr))
    r = de.process("g", json.dumps(_fspec(rec_expr)), "", src)
    assert r.audit["graph_fidelity"]["decision"] == "MISMATCH"
    assert any("GRAPH_SOURCE_MISMATCH" in m for m in r.comparison.critical) and not de.approve(r)
    ok = de.process("g", json.dumps(_fspec(src_expr)), "", src)
    assert ok.audit["graph_fidelity"]["decision"] == "PASS"


def _options(exprs, labels=("I", "II", "III", "IV")):
    return {"diagram_type": "graph", "subtype": "multi_choice_graphs", "confidence": 0.9, "labels": [],
            "multi_graph": {"columns": 2, "options": [{"label": l, "formula": {"axes": {"x_min": -3, "x_max": 3, "y_min": -6, "y_max": 6,
                                                                                         "show_grid": False, "show_numbers": False},
                                                                                "curves": [{"id": f"c{i}", "expression": e}]}}
                                                      for i, (l, e) in enumerate(zip(labels, exprs))]},
            "observed": {"num_options": len(exprs)}}


def test_swapped_options_are_caught_per_option():
    exprs = ["x^2+1", "-x^2-1", "x^3", "-x^3"]
    src = _render(_options(exprs))
    ok = de.process("o", json.dumps(_options(exprs)), "", src)
    assert ok.audit["graph_fidelity"]["decision"] == "PASS"
    swapped = de.process("o", json.dumps(_options([exprs[1], exprs[0], exprs[2], exprs[3]])), "", src)
    per = swapped.audit["graph_fidelity"]["per_option"]
    assert [o["decision"] for o in per][:2] == ["MISMATCH", "MISMATCH"] and [o["decision"] for o in per][2:] == ["PASS", "PASS"]
    assert any("(אפשרות I)" in m for m in swapped.comparison.critical) and not de.approve(swapped)


def test_undetectable_layout_is_review_never_a_silent_pass():
    from cases import CASES
    c10 = CASES["A10_log_options"]
    r = de.process("o", json.dumps(c10["spec"], ensure_ascii=False), c10["text"], (FX / c10["fixture"]).read_bytes())
    assert r.audit["graph_fidelity"]["decision"] in ("PASS", "LOW_CONFIDENCE")
    if r.audit["graph_fidelity"]["decision"] == "LOW_CONFIDENCE":
        assert any("GRAPH_SOURCE_FIDELITY_LOW_CONFIDENCE" in m for m in r.contradictions)
        assert r.decision.action != "high_confidence_preview"
