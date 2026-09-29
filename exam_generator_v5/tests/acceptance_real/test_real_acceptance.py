"""Real-image acceptance A01–A14 (+A07b, A09b) and adversarial correlated-failure tests."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from harness import CASES, MANIFESTS, evaluate, load, run_case  # noqa: E402

IDS = [p.name.split("_")[0] for p in MANIFESTS]


@pytest.mark.parametrize("mid", IDS)
def test_real_image_case(mid):
    row = evaluate(mid)
    assert row["result"] in ("PASS", "SAFE FALLBACK PASS"), row
    assert row["export_before_approval"] is False                      # never exported without the teacher
    if row["result"] == "PASS":
        assert row["export_after_approval"] is True


def _drop_point(spec: dict, pid: str) -> dict:
    s = copy.deepcopy(spec)
    g = s["geometry"]
    g["points"] = [p for p in g["points"] if p["id"] != pid]
    g["segments"] = [x for x in g["segments"] if pid not in (x["a"], x["b"])]
    g["constraints"] = [c for c in g.get("constraints", []) if pid not in c["points"]]
    s["labels"] = [l for l in s["labels"] if l["text"] != pid]
    return s


def test_A14_E_omitted_by_proposal_AND_observed_is_still_blocked():
    """THE V5.5 blocker: the same AI drops E from the spec and from its own 'observed' block."""
    spec = _drop_point(CASES["A14_circle_kite"]["spec"], "E")
    spec["observed"] = {"num_points": 6, "point_labels": list("ABCKMO"), "num_circles": 1, "num_segments": 5,
                        "point_orders": [["A", "K", "M"], ["O", "K", "C"]]}
    rec, _ = run_case(CASES["A14_circle_kite"], spec)
    assert "missing_required_point_E" in rec.missing_required
    assert rec.comparison.critical and rec.decision.action == "original"
    import diagram_engine as de
    assert not de.usable_in_document(rec) and not de.approve(rec)
    row = evaluate("A14", spec_override=spec, save=False)
    assert row["result"] != "PASS" and any("E" in f for f in row["manifest_failures"] + row["critical"])


@pytest.mark.parametrize("pid", list("ABCKMO"))
def test_A14_any_required_point_omitted_is_blocked(pid):
    spec = _drop_point(CASES["A14_circle_kite"]["spec"], pid)
    spec["observed"] = {}
    rec, _ = run_case(CASES["A14_circle_kite"], spec)
    assert f"missing_required_point_{pid}" in rec.missing_required and rec.decision.action == "original"


def test_A05_correlated_missing_scatter_point_caught_by_cv():
    spec = copy.deepcopy(CASES["A05_scatter"]["spec"])
    spec["scatter"]["points"].pop()
    spec["observed"] = {"num_scatter_points": 5}                           # the AI is consistently wrong
    rec, _ = run_case(CASES["A05_scatter"], spec)
    assert rec.decision.action == "original" and rec.comparison.critical


def test_A08_correlated_wrong_order_caught_by_text():
    spec = copy.deepcopy(CASES["A08_coordinate_circle"]["spec"])
    spec["observed"].pop("point_orders", None)
    spec["geometry"]["points"][0] = {"id": "M", "x": 3, "y": 0.5}          # proposal puts M beyond B
    rec, _ = run_case(CASES["A08_coordinate_circle"], spec)
    assert rec.decision.action == "original"


def test_A13_radius_turned_into_diameter_blocked_even_if_observed_agrees():
    spec = copy.deepcopy(CASES["A13_carton_cup"]["spec"])
    spec["spatial"]["dimensions"][3]["measure"] = "diameter"
    rec, _ = run_case(CASES["A13_carton_cup"], spec)
    assert rec.decision.action == "original" and any("רדיוס/קוטר" in c for c in rec.comparison.critical)


def test_A07_correlated_wrong_table_number_caught_by_independent_ocr():
    """The AI writes 15 instead of 150 in BOTH the proposal and its observed block. V5.7: the independent OCR channel
    reads 150 from the real image -> unresolved conflict -> blocked for the teacher (with an explicit Hebrew question)."""
    from diagram_engine import ocr
    spec = copy.deepcopy(CASES["A07_table_haircuts"]["spec"])
    spec["table"]["rows"][1][2]["text"] = "15"
    spec["observed"]["table_cells"][1][2] = "15"
    rec, _ = run_case(CASES["A07_table_haircuts"], spec)
    if not ocr.available():
        pytest.skip("Tesseract not installed - independent OCR channel unavailable")
    assert rec.decision.action == "original"
    assert any("150" in c and "15" in c and "OCR" in c for c in rec.contradictions)
    import diagram_engine as de
    assert not de.usable_in_document(rec)


def test_manifests_are_hand_authored_and_complete():
    for p in MANIFESTS:
        mf = load(p.name.split("_")[0])
        for k in ("diagram_type", "subtype", "required_labels", "critical_facts", "required_values", "forbidden_objects", "expected"):
            assert k in mf, (p.name, k)
