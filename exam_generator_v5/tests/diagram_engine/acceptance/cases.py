"""Acceptance cases built from the six supplied Bagrut questionnaires (14-19).

Each case = source crop (fixtures/, extracted from the vector PDFs) + question text + the structured extraction an
ideal vision model would return (hand-authored from the PDF) + required facts. The ENGINE (not Gemini) is under test.
`expect` = "reconstruct" (valid, no critical, needs teacher) or "original" (safe fallback by design)."""
from __future__ import annotations

import copy
import math

L = lambda *t: [{"text": x, "confidence": 0.98} for x in t]  # noqa: E731
AX0 = {"show_numbers": False, "show_grid": False}


def _topo(fl, xmn, xmx, ymn, ymx, lms, asy, branches):
    return {"function_label": fl, "axes": {"x_min": xmn, "x_max": xmx, "y_min": ymn, "y_max": ymx, **AX0},
            "landmarks": lms, "asymptotes": asy, "branches": branches}


def _rational_option(v=2.0, h=1.0, left_side="minus_inf"):
    """Two branches around a vertical asymptote x=v, both ends toward y=h (layout units). Where the branch must cross
    the x-axis (asymptote h on one side of it, +/-inf on the other) the crossing is a MARKED x-intercept, as in the source."""
    y_left = h - 0.6 if left_side == "minus_inf" else h + 0.6      # monotone toward the asymptote side (no invented extremum)
    lms = [{"x": v - 1.5, "y": y_left, "kind": "marked", "style": "none"}, {"x": v + 1.5, "y": h + 1.2, "kind": "marked", "style": "none"}]
    left_idx, right_idx = [0], [1]
    if (h > 0 and left_side == "minus_inf") or (h < 0 and left_side == "plus_inf"):
        if y_left * h > 0:                         # the crossing lies between the landmark and the asymptote
            lms.append({"x": v - 0.4, "y": 0, "kind": "x_intercept", "style": "none"})
            left_idx = [0, len(lms) - 1]
    if h < 0:
        lms.append({"x": v + 0.6, "y": 0, "kind": "x_intercept", "style": "none"})
        right_idx = [len(lms) - 1, 1]
        lms[1]["y"] = h * 0.5                      # between the crossing (0) and the asymptote h < 0: monotone
    return _topo("g(x)", -4, 6, -4, 5, lms,
                 [{"kind": "vertical", "value": v}, {"kind": "horizontal", "value": h}],
                 [{"landmarks": left_idx, "left": {"toward": "asymptote", "value": h}, "right": {"toward": left_side, "value": v}},
                  {"landmarks": right_idx, "left": {"toward": "plus_inf", "value": v}, "right": {"toward": "asymptote", "value": h}}])


CASES: dict[str, dict] = {}

# ---------------------------------------------------------------- A01 qualitative graph (q14 p2)
CASES["A01_qualitative"] = dict(
    fixture="q14_p2_8.png", expect="reconstruct",
    text="בסרטוט מתואר גרף הפונקצייה f(x) המוגדרת לכל x. לפונקצייה יש אסימפטוטה אחת בלבד, y = 0, ונקודת חיתוך אחת בלבד עם ציר x, (12 , 0). a הוא פרמטר גדול מ-1.",
    spec={"diagram_type": "graph", "subtype": "qualitative_graph", "confidence": 0.92,
          "labels": L("(6 , a)", "(12 , 0)", "(18, −2a)", "f(x)", "x"),
          "graph_topology": _topo("f(x)", -12, 34, -4, 3,
                                  [{"x": 6, "y": 1, "label": "(6 , a)", "kind": "max"},
                                   {"x": 12, "y": 0, "label": "(12 , 0)", "kind": "x_intercept"},
                                   {"x": 18, "y": -2, "label": "(18, −2a)", "kind": "min"}],
                                  [{"kind": "horizontal", "value": 0}],
                                  [{"landmarks": [0, 1, 2], "left": {"toward": "asymptote", "value": 0}, "right": {"toward": "asymptote", "value": 0}}]),
          "observed": {"num_branches": 1, "num_maxima": 1, "num_minima": 1, "x_intercepts": [12], "horizontal_asymptotes": [0],
                       "point_labels": ["(6 , a)", "(12 , 0)", "(18, −2a)"]}})

# ---------------------------------------------------------------- A02 formula + four derivative graphs (q16 p7)
f_prime_like = _topo("y", -1, 12, -6, 4, [{"x": 8.2, "y": 0, "label": "", "kind": "x_intercept", "style": "none"}],
                     [{"kind": "vertical", "value": 3.2}, {"kind": "horizontal", "value": 2}],
                     [{"landmarks": [0], "left": {"toward": "minus_inf", "value": 3.2}, "right": {"toward": "asymptote", "value": 2}}])
decreasing = _topo("y", -1, 12, -2, 6, [{"x": 6, "y": 2.5, "label": "", "kind": "marked", "style": "none"}],
                   [{"kind": "vertical", "value": 3.2}, {"kind": "horizontal", "value": 2}],
                   [{"landmarks": [0], "left": {"toward": "plus_inf", "value": 3.2}, "right": {"toward": "asymptote", "value": 2}}])
CASES["A02_formula_options"] = dict(
    fixture="q16_p7_3.png", expect="reconstruct", formula="2x-4sqrt(5x-16)",
    text="נתונה הפונקצייה $f(x)=2x-4\\sqrt{5x-16}$. קבעו איזה מן הגרפים I–IV שבסוף השאלה מתאר את פונקציית הנגזרת f'(x).",
    spec={"diagram_type": "graph", "subtype": "multi_choice_graphs", "confidence": 0.9, "labels": L("I", "II", "III", "IV"),
          "multi_graph": {"options": [{"label": "I", "topology": decreasing}, {"label": "II", "topology": f_prime_like},
                                      {"label": "III", "topology": _rational_option(3.2, 2.0, "plus_inf")},
                                      {"label": "IV", "topology": _rational_option(3.2, -1.0)}]},
          "observed": {"num_options": 4, "option_labels": ["I", "II", "III", "IV"]}})

# ---------------------------------------------------------------- A03 rational function + I-IV (q14 p3)
CASES["A03_rational_options"] = dict(
    fixture="q14_p3_4.png", expect="reconstruct",
    text="אחד מן הגרפים I–IV שלפניכם מתאר פונקצייה g(x) המקיימת תנאים אלה.",
    spec={"diagram_type": "graph", "subtype": "multi_choice_graphs", "confidence": 0.9, "labels": L("I", "II", "III", "IV", "g(x)"),
          "multi_graph": {"options": [{"label": l, "topology": _rational_option(1.5, 1.0 if l in ("I", "II") else -1.0,
                                                                                "minus_inf" if l in ("I", "III") else "plus_inf")}
                                      for l in ("I", "II", "III", "IV")]},
          "observed": {"num_options": 4, "option_labels": ["I", "II", "III", "IV"]}})

# ---------------------------------------------------------------- A04 formula graph (q14 p7): only f is drawn in the source
CASES["A04_formula_no_construction"] = dict(
    fixture="q14_p7_3.png", expect="reconstruct",
    text="נתונה הפונקצייה $f(x)=2\\sqrt{x^2-1}$ והישר $y=3x-3$. הנקודה A נמצאת על גרף הפונקצייה. דרך A מעבירים ישר המקביל לציר ה-y וחותך את הישר בנקודה B.",
    spec={"diagram_type": "graph", "subtype": "formula_graph", "confidence": 0.9, "labels": L("x", "y"),
          "graph": {"axes": {"x_min": -4, "x_max": 4, "y_min": -1, "y_max": 7, "show_numbers": False, "show_grid": False},
                    "curves": [{"id": "f", "label": "", "expression": "2sqrt(x^2-1)"}]},
          "observed": {"num_curves": 1, "x_intercepts": [-1, 1], "num_branches": 2}})

# ---------------------------------------------------------------- A05 scatter (q16 p3)
SCATTER = [[5, 50], [10, 40], [15, 30], [15, 20], [20, 30], [25, 10]]
CASES["A05_scatter"] = dict(
    fixture="q16_p3_2.png", expect="reconstruct",
    text="בדיאגרמת הפיזור מוצגים שטח השטחים הירוקים (x) ורמת זיהום האוויר AQI (y).",
    spec={"diagram_type": "chart", "subtype": "scatter_plot", "confidence": 0.9, "labels": L("0", "5", "10", "60"),
          "scatter": {"axes": {"x_min": 0, "x_max": 30, "y_min": 0, "y_max": 60, "x_step": 5, "y_step": 10, "show_grid": True},
                      "points": SCATTER},
          "observed": {"num_scatter_points": 6}})

# ---------------------------------------------------------------- A06 generic plan (q16 p8)
CASES["A06_generic_plan"] = dict(
    fixture="q16_p8_2.png", expect="reconstruct",
    text="ABCD מבואה – המלבן. BEFC שביל גישה – המלבן. EGHK גן פסלים – הריבוע. הנקודות A, B, E, G נמצאות על ישר אחד. אורך הקטע AG הוא 8 מטרים.",
    spec={"diagram_type": "generic", "confidence": 0.9, "labels": L(*"ABCDEFGHK", "8 מטרים"),
          "generic": {"width": 100, "height": 62,
                      "shapes": [{"kind": "rect", "x": 2, "y": 30, "w": 10, "h": 16, "text": "מבואה"},
                                 {"kind": "rect", "x": 12, "y": 30, "w": 58, "h": 16, "text": "שביל גישה"},
                                 {"kind": "rect", "x": 70, "y": 16, "w": 28, "h": 30, "text": "גן פסלים"}],
                      "labels": [{"text": "A", "x": 1, "y": 49}, {"text": "B", "x": 12, "y": 49}, {"text": "E", "x": 70, "y": 49},
                                 {"text": "G", "x": 98.5, "y": 49}, {"text": "D", "x": 1, "y": 27}, {"text": "C", "x": 12, "y": 27},
                                 {"text": "F", "x": 70, "y": 27}, {"text": "K", "x": 70, "y": 13}, {"text": "H", "x": 98.5, "y": 13}],
                      "dimensions": [{"x1": 2, "y1": 54, "x2": 98, "y2": 54, "text": "8 מטרים", "attach": ["A", "G"]}]},
          "observed": {"num_shapes": 3, "shape_labels": ["מבואה", "שביל גישה", "גן פסלים"], "point_labels": list("ABCDEFGHK"),
                       "dimension_texts": ["8 מטרים"]}},
    adjacency=[["גן פסלים", "שביל גישה"], ["מבואה", "שביל גישה"]])

# ---------------------------------------------------------------- A07 tables (q18 p12, q19 p4)
T18 = [["סוג התספורת", "ילדים", "שיער קצר", "שיער ארוך", "מיוחדת"], ["המחיר (בשקלים)", "60", "150", "180", "210"],
       ["מספר הלקוחות", "5", "21", "9", "10"]]
T19 = [["סוג העוגה", "זמן הכנת התערובת (בדקות)", "זמן האפייה (בדקות)", "הרווח (בשקלים)"],
       ["עוגת שוקולד", "4", "20", "47"], ["עוגת גבינה", "4", "60", "60"]]


def _table(rows):
    return {"diagram_type": "table", "subtype": "numeric_table", "confidence": 0.93, "labels": [],
            "table": {"header_rows": 1, "header_columns": 1, "rows": [[{"text": c} for c in r] for r in rows]},
            "observed": {"table_shape": [len(rows), len(rows[0])], "table_cells": rows}}


CASES["A07_table_haircuts"] = dict(fixture="q18_p12_4.png", expect="reconstruct", text="בטבלה שלפניכם מוצגים סוגי התספורות.", spec=_table(T18))
CASES["A07b_table_cakes"] = dict(fixture="q19_p4_6.png", expect="reconstruct", text="בטבלה מוצגים הזמנים והרווח.", spec=_table(T19))

# ---------------------------------------------------------------- A08 circle on the coordinate plane + tangent (q16 p5)
CASES["A08_coordinate_circle"] = dict(
    fixture="q16_p5_2.png", expect="reconstruct",
    text="בסרטוט שלפניכם מעגל. מרכז המעגל M נמצא על ציר ה-x. הנקודה A נמצאת על המעגל. המשך הקטע MA חותך את ציר ה-y בנקודה B. "
         "נתון: B(0 , 18), A(−16 , 6). דרך הנקודה A מעבירים משיק למעגל החותך את ציר ה-y בנקודה D. הנקודה C נמצאת על המעגל כך ש-AC הוא קוטר במעגל.",
    spec={"diagram_type": "geometry", "subtype": "analytic_geometry", "confidence": 0.93, "labels": L(*"ABCDM", "x", "y"),
          "geometry": {"points": [{"id": "M", "x": -23, "y": 0.5}, {"id": "A", "x": -16, "y": 6}, {"id": "B", "x": 0, "y": 18},
                                  {"id": "C", "x": -31, "y": -5}, {"id": "D", "x": 0.5, "y": -14}],
                       "segments": [{"a": "C", "b": "B"}, {"a": "A", "b": "D"}, {"a": "C", "b": "D"}],
                       "circles": [{"id": "c1", "center": "M", "through": "A"}],
                       "constraints": [{"type": "on_y_axis", "points": ["D"], "source": "text"}]},
          "observed": {"num_points": 5, "point_labels": list("ABCDM"), "num_circles": 1, "num_segments": 3,
                       "point_orders": [["M", "A", "B"], ["C", "M", "A"]], "tangent_points": ["A"]}},
    exact={"M": (-24, 0), "C": (-32, -6), "D": (0, 6 - 64 / 3)})

# ---------------------------------------------------------------- A09 box + pyramid with vectors (q15 p2, q17 p3)
BOX_V = {"A": [0, 3, 0], "B": [4, 3, 0], "C": [4, 0, 0], "D": [0, 0, 0], "A'": [0, 3, 3.2], "B'": [4, 3, 3.2], "C'": [4, 0, 3.2], "D'": [0, 0, 3.2]}
CASES["A09_box"] = dict(
    fixture="q15_p2_6.png", expect="reconstruct", text="בסרטוט שלפניכם תיבה ABCDA'B'C'D'.",
    spec={"diagram_type": "spatial", "subtype": "cuboid", "confidence": 0.93, "labels": L(*BOX_V),
          "spatial": {"solids": [{"id": "box", "kind": "cuboid", "vertices": BOX_V,
                                  "edges": [["A", "B"], ["B", "C"], ["C", "D"], ["D", "A"], ["A'", "B'"], ["B'", "C'"], ["C'", "D'"], ["D'", "A'"],
                                            ["A", "A'"], ["B", "B'"], ["C", "C'"], ["D", "D'"]],
                                  "hidden_edges": [["A", "B"], ["A", "D"], ["A", "A'"]]}]},
          "observed": {"num_solids": 1, "point_labels": sorted(BOX_V), "num_segments": 12}})
PYR = {"S": [0, 0, 4], "A": [0, 0, 0], "B": [-1.5, -3, 0], "C": [4, 0, 0]}   # A behind the front edge BC, as in the source
CASES["A09b_pyramid_vectors"] = dict(
    fixture="q17_p3_2.png", expect="reconstruct",
    text="בסרטוט שלפניכם פירמידה SABC. הנקודה F נמצאת על המקצוע BC כך ש-BF = 2/3 BC. E אמצע המקצוע BS. AB = u, AC = v, AS = w.",
    spec={"diagram_type": "spatial", "subtype": "vector_box", "confidence": 0.92, "labels": L("S", "A", "B", "C", "E", "F", "u", "v", "w"),
          "spatial": {"solids": [{"id": "pyr", "kind": "polyhedron", "vertices": PYR,
                                  "edges": [["S", "A"], ["S", "B"], ["S", "C"], ["A", "B"], ["A", "C"], ["B", "C"]],
                                  "hidden_edges": [["S", "A"], ["A", "C"]]}],
                      "vectors": [{"from": "A", "to": "B", "label": "u"}, {"from": "A", "to": "C", "label": "v"}, {"from": "A", "to": "S", "label": "w"}],
                      "points_on_edges": [{"id": "E", "a": "B", "b": "S", "ratio": 0.5}, {"id": "F", "a": "B", "b": "C", "ratio": 2 / 3}]},
          "observed": {"num_solids": 1, "point_labels": ["A", "B", "C", "E", "F", "S"], "num_segments": 6}})

# ---------------------------------------------------------------- A10 log graphs I-IV (q15 p5)
def _log_option(n_branches):
    lms, brs, asy = [], [], []
    for i in range(n_branches):
        v = -2 + 1.5 * i
        asy.append({"kind": "vertical", "value": v})
        lms.append({"x": v + 0.3, "y": 0, "kind": "x_intercept", "style": "none"})          # log branch crosses the x-axis
        lms.append({"x": v + 0.7, "y": 0.8 - 0.2 * i, "kind": "marked", "style": "none"})
        brs.append({"landmarks": [2 * i, 2 * i + 1], "left": {"toward": "minus_inf", "value": v}, "right": {"toward": "stop"},
                    "x_to": v + 1.4 if i < n_branches - 1 else None})
    return _topo("y", -3, 4, -3, 3, lms, asy, brs)


CASES["A10_log_options"] = dict(
    fixture="q15_p5_5.png", expect="reconstruct",
    text="אחד מן הגרפים I–IV שלפניכם מתאר את הפונקצייה h(x). קבעו איזה.",
    spec={"diagram_type": "graph", "subtype": "multi_choice_graphs", "confidence": 0.9, "labels": L("I", "II", "III", "IV"),
          "multi_graph": {"options": [{"label": "I", "topology": _log_option(3)}, {"label": "II", "topology": _log_option(3)},
                                      {"label": "III", "topology": _log_option(2)}, {"label": "IV", "topology": _log_option(1)}]},
          "observed": {"num_options": 4, "option_labels": ["I", "II", "III", "IV"]}})

# ---------------------------------------------------------------- A11 normal distribution (q19 p8)
PCT = ["0.5%", "1.5%", "5%", "9%", "15%", "19%", "19%", "15%", "9%", "5%", "1.5%", "0.5%"]
CASES["A11_normal"] = dict(
    fixture="q19_p8_4.png", expect="reconstruct", text="לפניכם עקומה נורמלית. השלימו בתיבות את הערכים.",
    spec={"diagram_type": "chart", "subtype": "normal_distribution_schematic", "confidence": 0.93, "labels": L(*sorted(set(PCT))),
          "normal": {"percentages": PCT, "boxed_regions": [0, 1, 10, 11], "answer_boxes": 11, "axis_label": "x"},
          "observed": {"num_regions": 12, "region_labels": PCT, "num_answer_boxes": 11}})

# ---------------------------------------------------------------- A12 cube structure (q19 p12): hidden columns -> original
CASES["A12_voxel"] = dict(
    fixture="q19_p12_2.png", expect="original",
    text="במבנה שלפניכם קוביות זהות מונחות על לוח. החץ מראה את כיוון המבט.",
    spec={"diagram_type": "spatial", "subtype": "voxel_structure", "confidence": 0.8, "labels": [],
          "spatial": {"voxel": {"plate": [4, 4], "arrow": [1.5, -1.2, 0.3, 0.7], "ambiguous": True,
                                "columns": [{"x": 0, "y": 0, "height": 1}, {"x": 1, "y": 0, "height": 2}, {"x": 3, "y": 0, "height": 1},
                                            {"x": 0, "y": 1, "height": 2}, {"x": 2, "y": 2, "height": 3}, {"x": 3, "y": 3, "height": 4},
                                            {"x": 3, "y": 1, "height": 2}]}},
          "observed": {"visible_cubes": 14}})

# ---------------------------------------------------------------- A13 milk carton + cup (q19 p14)
CASES["A13_carton_cup"] = dict(
    fixture="q19_p14_2.png", expect="reconstruct",
    text="גובה הקרטון הוא 24 ס\"מ ואורך צלע הבסיס שלו הוא 6.5 ס\"מ. רדיוס הבסיס של כל כוס הוא 3 ס\"מ.",
    spec={"diagram_type": "spatial", "subtype": "cylinder_in_box", "confidence": 0.93, "labels": L("24 ס\"מ", "6.5 ס\"מ", "3 ס\"מ", "חלב"),
          "spatial": {"solids": [{"id": "carton", "kind": "cuboid", "dims": {"width": 6.5, "depth": 6.5, "height": 24}, "face_text": "חלב"},
                                 {"id": "cup", "kind": "cylinder", "dims": {"radius": 3, "height": 8}, "origin": [16, 0, 0]}],
                      "dimensions": [{"solid": "carton", "measure": "height", "text": "24 ס\"מ", "value": 24},
                                     {"solid": "carton", "measure": "width", "text": "6.5 ס\"מ", "value": 6.5},
                                     {"solid": "carton", "measure": "depth", "text": "6.5 ס\"מ", "value": 6.5},
                                     {"solid": "cup", "measure": "radius", "text": "3 ס\"מ", "value": 3}],
                      "relations": [{"type": "separate", "a": "carton", "b": "cup"}]},
          "observed": {"num_solids": 2, "dimension_texts": ["24 ס\"מ", "6.5 ס\"מ", "6.5 ס\"מ", "3 ס\"מ"]}})

# ---------------------------------------------------------------- A14 circle, diameter, kite (q14 p5)
CASES["A14_circle_kite"] = dict(
    fixture="q14_p5_2.png", expect="reconstruct",
    text="בסרטוט שלפניכם מעגל שמרכזו O. AB הוא קוטר במעגל. הנקודה C נמצאת על המעגל. הנקודה M נמצאת מחוץ למעגל, כך שהקטע AM חותך את הקטע CO בנקודה K. "
         "הנקודה E נמצאת על הקטע BO כך שהמרובע EMKO הוא דלתון (MK=ME , OK=OE).",
    spec={"diagram_type": "geometry", "subtype": "circle_geometry", "confidence": 0.93, "labels": L(*"ABCEKMO"),
          "geometry": {"points": [{"id": "O", "x": 0, "y": 0}, {"id": "A", "x": -2.45, "y": -2.06}, {"id": "B", "x": 2.45, "y": 2.06},
                                  {"id": "C", "x": 2.45, "y": -2.06}, {"id": "M", "x": 7.5, "y": 0}, {"id": "K", "x": 1.2, "y": -1.0},
                                  {"id": "E", "x": 1.1, "y": 0.95}],
                       "segments": [{"a": "A", "b": "B"}, {"a": "A", "b": "C"}, {"a": "O", "b": "C"}, {"a": "O", "b": "M"},
                                    {"a": "E", "b": "M"}, {"a": "A", "b": "M"}],
                       "circles": [{"id": "c1", "center": "O", "through": "A"}],
                       "constraints": [{"type": "outside_circle", "points": ["M"], "circle": "c1", "source": "text"}]},
          "observed": {"num_points": 7, "point_labels": list("ABCEKMO"), "num_circles": 1, "num_segments": 6,
                       "point_orders": [["A", "O", "E", "B"], ["A", "K", "M"], ["O", "K", "C"]]}})


def variant(case: dict, mutate) -> dict:
    c = copy.deepcopy(case)
    mutate(c["spec"])
    return c


def dist(a, b) -> float:
    return math.dist(a, b)
