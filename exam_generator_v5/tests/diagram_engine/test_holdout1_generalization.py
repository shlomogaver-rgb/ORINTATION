"""Generic fixes exposed by teacher holdout #1 - tested on OTHER numbers / letters / shapes than the images."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import diagram_engine as de  # noqa: E402


@pytest.mark.parametrize("lo,hi", [(-40, 80), (0, 500), (-1000, 1000), (-0.5, 250)])
def test_large_value_range_gets_an_automatic_readable_tick_step(lo, hi):
    s = {"diagram_type": "graph", "confidence": 0.9, "labels": [],
         "graph": {"axes": {"x_min": -1, "x_max": 10, "y_min": lo, "y_max": hi}, "curves": [{"id": "f", "expression": "x^2"}]},
         "observed": {"num_curves": 1}}
    r = de.process("t", json.dumps(s), "", None)
    assert r.validation.ok and (hi - lo) / r.spec.graph.axes.y_step <= 60


def test_explicitly_invalid_tick_step_is_still_an_error():
    s = {"diagram_type": "graph", "confidence": 0.9, "labels": [],
         "graph": {"axes": {"x_min": -1, "x_max": 10, "y_min": 0, "y_max": 5, "y_step": -2}, "curves": [{"id": "f", "expression": "x"}]}}
    assert not de.process("t", json.dumps(s), "", None).validation.ok


@pytest.mark.parametrize("value,ok", [(0, True), (2.5, False)])
def test_branch_toward_x_axis_needs_no_declared_asymptote(value, ok):
    topo = {"function_label": "", "axes": {"x_min": -3, "x_max": 6, "y_min": -1, "y_max": 8},
            "landmarks": [{"x": -1, "y": 0, "kind": "endpoint", "style": "none"}, {"x": 0.5, "y": 6, "kind": "max", "style": "none"}],
            "branches": [{"landmarks": [0, 1], "left": {"toward": "stop"}, "right": {"toward": "asymptote", "value": value}}], "asymptotes": []}
    s = {"diagram_type": "graph", "subtype": "multi_choice_graphs", "confidence": 0.9, "labels": [],
         "multi_graph": {"options": [{"label": "I", "topology": topo}, {"label": "II", "topology": topo}]}, "observed": {"num_options": 2}}
    r = de.process("t", json.dumps(s), "", None)
    assert r.validation.ok == ok, r.validation.errors


def test_spatial_label_inventory_includes_points_on_edges_and_diagonals():
    from diagram_engine import ocr
    if not ocr.available():
        pytest.skip("no Tesseract")
    spec = {"diagram_type": "spatial", "subtype": "cuboid", "confidence": 0.9,
            "labels": [{"text": t, "confidence": 0.98} for t in ["P", "Q", "R", "S", "K", "M"]],
            "spatial": {"solids": [{"id": "b", "kind": "cuboid", "dims": {"width": 5, "depth": 3, "height": 3}}],
                        "points_on_edges": [{"id": "K", "a": "A", "b": "B", "ratio": 0.3}],
                        "points_on_diagonals": [{"id": "M", "a": "A'", "b": "C'", "ratio": 0.6}]}}
    src = de.render_spec(de.process("s", json.dumps(spec), "", None).spec)[1]
    r = de.process("t", json.dumps(spec), "", src)
    assert not [x for x in r.contradictions if "MISSING_FROM_SPEC:K" in x or "MISSING_FROM_SPEC:M" in x], r.contradictions


@pytest.mark.parametrize("latex", ["\\underline{a}+\\underline{b}", "\\overrightarrow{PQ}\\cdot\\underline{w}=0", "\\overline{KL}=5",
                                   "\\vec{r}=t\\vec{d}", "|\\overrightarrow{MN}|=\\sqrt{29}"])
def test_vector_notations_parse_and_become_native_word_math(latex):
    import re

    from lxml import etree

    import exam_core as c
    from diagram_engine import formula_pipeline as fp
    assert fp.analyse(latex)["status"] == "OK"
    xml = etree.tostring(c.latex_to_omml(latex), encoding="unicode")
    assert not re.search(r"<m:limUpp>|<m:limLow>", xml) and re.search(r"<m:(acc|bar)>", xml)
