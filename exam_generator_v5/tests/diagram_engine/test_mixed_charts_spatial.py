import math

import numpy as np
import pytest
from helpers import pts, run

from diagram_engine.spatial import voxel as V
from diagram_engine.schemas import VoxelSpec


def semicircle_rectangle(R=5.0, observed=None):
    """Prompt A04: y = sqrt(R^2 - x^2), rectangle ABDC: A,B on the curve, C,D on the x-axis, AB ∥ x-axis, AC ⟂ x-axis."""
    return {"diagram_type": "mixed_graph_geometry", "confidence": 0.95, "labels": [{"text": t, "confidence": 0.99} for t in "ABCD"],
            "mixed": {"graph": {"axes": {"x_min": -6, "x_max": 6, "y_min": -1, "y_max": 6, "show_numbers": False, "show_grid": False},
                                "curves": [{"id": "f", "expression": f"sqrt({R ** 2:g}-x^2)", "source": "text"}]},
                      "geometry": {"points": [{"id": "A", "x": -3.1, "y": 3.9}, {"id": "B", "x": 2.9, "y": 4.1},
                                              {"id": "C", "x": -3, "y": 0.1}, {"id": "D", "x": 3.1, "y": -0.1}],
                                   "segments": [{"a": "A", "b": "B"}, {"a": "A", "b": "C"}, {"a": "B", "b": "D"}],
                                   "constraints": [{"type": "on_curve", "points": ["A"], "curve": "f", "source": "text"},
                                                   {"type": "on_curve", "points": ["B"], "curve": "f", "source": "text"},
                                                   {"type": "on_x_axis", "points": ["C"], "source": "text"},
                                                   {"type": "on_x_axis", "points": ["D"], "source": "text"},
                                                   {"type": "parallel_to_x_axis", "points": ["A", "B"], "source": "text"},
                                                   {"type": "perpendicular_to_x_axis", "points": ["A", "C"], "source": "text"},
                                                   {"type": "perpendicular_to_x_axis", "points": ["B", "D"], "source": "text"}]}},
            "observed": observed or {"num_points": 4, "point_labels": list("ABCD"), "num_curves": 1}}


def test_mixed_semicircle_rectangle():
    r = run(semicircle_rectangle(), "נתונה הפונקצייה $y=\\sqrt{25-x^2}$")
    assert r.validation.ok and not r.comparison.critical, (r.validation.errors, r.comparison.critical)
    P = pts(r)
    for k in "AB":
        assert P[k][1] == pytest.approx(math.sqrt(25 - P[k][0] ** 2), abs=1e-6)
    assert P["C"][1] == pytest.approx(0) and P["D"][1] == pytest.approx(0) and P["A"][1] == pytest.approx(P["B"][1])
    assert P["A"][0] == pytest.approx(P["C"][0]) and r.manifest["curves"] == ["f"]


def test_mixed_on_curve_unknown_curve_invalid():
    s = semicircle_rectangle()
    s["mixed"]["geometry"]["constraints"][0]["curve"] = "g"
    assert not run(s).validation.ok


def test_normal_distribution_counts():
    pct = ["2%", "14%", "34%", "34%", "14%", "2%"]
    r = run({"diagram_type": "chart", "subtype": "normal_distribution_schematic", "confidence": 0.93, "labels": [],
             "normal": {"percentages": pct, "answer_boxes": 5}, "observed": {"num_regions": 6, "region_labels": pct, "num_answer_boxes": 5}})
    assert r.validation.ok and r.manifest["lines"] == 5 and r.manifest["boxes"] == 5 and r.manifest["symmetric_labels"]
    bad = run({"diagram_type": "chart", "subtype": "normal_distribution_schematic", "confidence": 0.93,
               "normal": {"percentages": pct, "answer_boxes": 3}})
    assert not bad.validation.ok


def test_table_validation_and_cells():
    t = {"diagram_type": "table", "confidence": 0.93, "table": {"rows": [[{"text": "a"}, {"text": "1"}], [{"text": "b"}]]}}
    assert not run(t).validation.ok
    t2 = {"diagram_type": "table", "confidence": 0.93, "table": {"rows": [[{"text": "x"}, {"text": "5", "value": 6}]]}}
    assert not run(t2).validation.ok


def test_generic_dimension_attached_to_missing_label_invalid():
    g = {"diagram_type": "generic", "confidence": 0.9, "generic": {"width": 100, "height": 50,
         "shapes": [{"kind": "rect", "x": 5, "y": 5, "w": 20, "h": 20, "text": "a"}], "labels": [{"text": "A", "x": 5, "y": 28}],
         "dimensions": [{"x1": 5, "y1": 30, "x2": 25, "y2": 30, "text": "8 מטרים", "attach": ["A", "G"]}]}}
    assert not run(g).validation.ok


def test_voxel_counts_top_view_and_hidden_top():
    v = VoxelSpec(columns=[{"x": 0, "y": 0, "height": 3}, {"x": 1, "y": 1, "height": 1}, {"x": 2, "y": 0, "height": 2}])
    assert V.total(v) == 6 and V.top_view(v, 3, 2) == [[False, True, False], [True, False, True]]
    hidden = VoxelSpec(columns=[{"x": 0, "y": 0, "height": 4}, {"x": 1, "y": 1, "height": 1}])   # short column hidden behind
    assert V.visibility(hidden)["hidden_tops"] == [(1, 1)]
    r = run({"diagram_type": "spatial", "subtype": "voxel_structure", "confidence": 0.9,
             "spatial": {"voxel": {"columns": [c.model_dump() for c in hidden.columns]}}})
    assert r.decision.action == "original" and any("ממציאים" in c for c in r.comparison.critical)


def test_voxel_visible_structure_reconstructs():
    r = run({"diagram_type": "spatial", "subtype": "voxel_structure", "confidence": 0.95,
             "spatial": {"voxel": {"columns": [{"x": 0, "y": 0, "height": 2}, {"x": 1, "y": 0, "height": 1}], "plate": [2, 2]}},
             "observed": {"visible_cubes": 3}})
    assert r.validation.ok and r.decision.action != "original" and r.manifest["total_cubes"] == 3


def test_solids_radius_vs_diameter_and_relations():
    base = {"diagram_type": "spatial", "subtype": "cylinder_in_box", "confidence": 0.93,
            "spatial": {"solids": [{"id": "box", "kind": "cuboid", "dims": {"width": 60, "depth": 30, "height": 40}},
                                   {"id": "cyl", "kind": "cylinder", "dims": {"radius": 3, "height": 18}, "origin": [20, 10, 0]}],
                        "dimensions": [{"solid": "box", "measure": "width", "text": "60 ס\"מ"}, {"solid": "box", "measure": "depth", "text": "30 ס\"מ"},
                                       {"solid": "box", "measure": "height", "text": "40 ס\"מ"}, {"solid": "cyl", "measure": "diameter", "text": "6 ס\"מ"},
                                       {"solid": "cyl", "measure": "height", "text": "18 ס\"מ"}],
                        "relations": [{"type": "inside", "a": "cyl", "b": "box"}, {"type": "touching_base", "a": "cyl", "b": "box"}]},
            "observed": {"num_solids": 2, "dimension_texts": ["60 ס\"מ", "30 ס\"מ", "40 ס\"מ", "6 ס\"מ", "18 ס\"מ"]}}
    r = run(base)
    assert r.validation.ok and not r.comparison.critical
    assert ["cyl", "diameter", "6 ס\"מ"] in r.manifest["dimensions"] and ["inside", "cyl", "box"] in r.manifest["relations"]
    bad = run({**base, "spatial": {**base["spatial"], "dimensions": [{"solid": "box", "measure": "radius", "text": "3"}]}})
    assert not bad.validation.ok                                           # a radius on a box is meaningless


def test_vector_box_prompt_example():
    """Box ABCDA'B'C'D': F midpoint of BC, E on A'C' with A'E = 3/4 A'C', AB=u, BC=v, AA'=w."""
    from diagram_engine.spatial.solids import box_vertices
    from diagram_engine.schemas import Solid
    verts = box_vertices(Solid(id="b", kind="cuboid", dims={"width": 4, "depth": 3, "height": 3}))
    spec = {"diagram_type": "spatial", "subtype": "vector_box", "confidence": 0.93, "labels": [],
            "spatial": {"solids": [{"id": "b", "kind": "cuboid", "vertices": verts, "hidden_edges": [["A", "B"], ["A", "D"], ["A", "A'"]]}],
                        "points_on_edges": [{"id": "F", "a": "B", "b": "C", "ratio": 0.5}, {"id": "E", "a": "A'", "b": "C'", "ratio": 0.75}],
                        "vectors": [{"from": "A", "to": "B", "label": "u"}, {"from": "B", "to": "C", "label": "v"}, {"from": "A", "to": "A'", "label": "w"}]},
            "observed": {"num_solids": 1, "point_labels": sorted(list(verts) + ["E", "F"])}}
    r = run(spec)
    assert r.validation.ok and not r.comparison.critical, (r.validation.errors, r.comparison.critical)
    assert ["F", "B", "C", 0.5] in r.manifest["points_on_edges"] and ["E", "A'", "C'", 0.75] in r.manifest["points_on_edges"]
    assert sorted(v[2] for v in r.manifest["vectors"]) == ["u", "v", "w"] and r.manifest["hidden_edges"] == 3
    bad = run({**spec, "spatial": {**spec["spatial"], "points_on_edges": [{"id": "E", "a": "A'", "b": "C'", "ratio": 1.3}]}})
    assert not bad.validation.ok
