"""Findings of the first full conversion of an UNSEEN Bagrut PDF (35571, summer 2024) - tested generally."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import exam_core as c  # noqa: E402
import text_structure as ts  # noqa: E402


def test_required_facts_are_per_figure_subpart():
    ai = c.QuestionAI(topic="t", text="שאלות קצרות.", sections=[
        c.QuestionSection(section_id="ג", text="לפניכם שתי טענות.\nI. הפונקציות חיוביות.\nII. הישר חותך את $g(x)$.", points=10),
        c.QuestionSection(section_id="ד", text="במשולש $PQR$ הנקודה $M$ היא אמצע $PQ$.", points=10)],
        figures=[c.FigureRef(description="f", section_id="ד", bbox=[])])
    q = c.postprocess_question(ai, 1, 20, 1)
    t = c.reconstruction_text(q, q.figures[0])
    assert "PQR" in t and "הפונקציות חיוביות" not in t


@pytest.mark.parametrize("ang", [30, 48, 70])
def test_diameter_without_a_drawn_circle_holds_by_thales(ang):
    import math

    import diagram_engine as de
    tA = math.radians(80)
    pt = lambda t: [round(math.cos(t), 9), round(math.sin(t), 9)]  # noqa: E731
    P = {"A": pt(tA), "D": pt(tA + math.pi), "B": pt(tA + math.radians(ang)), "C": pt(tA + math.radians(ang + 60))}
    spec = {"diagram_type": "geometry", "confidence": 0.95, "labels": [{"text": k, "confidence": 1} for k in P],
            "geometry": {"points": [{"id": k, "x": v[0], "y": v[1]} for k, v in P.items()],
                         "segments": [{"a": "A", "b": "B"}, {"a": "B", "b": "C"}, {"a": "C", "b": "D"}, {"a": "D", "b": "A"}]},
            "observed": {"num_points": 4, "point_labels": list("ABCD")}}
    r = de.process("x", json.dumps(spec), "המרובע ABCD הוא בר חסימה במעגל, כך ש־AD הוא קוטר במעגל.", None)
    assert not any("diameter" in m for m in r.comparison.critical), r.comparison.critical
    bad = json.loads(json.dumps(spec))
    bad["geometry"]["points"][2]["x"] += 0.3                                    # B no longer sees AD at 90 degrees
    r2 = de.process("x", json.dumps(bad), "המרובע ABCD הוא בר חסימה במעגל, כך ש־AD הוא קוטר במעגל.", None)
    assert r2.decision.action != "high_confidence_preview"


def test_tight_crop_axes_are_not_a_frame():
    import io

    from PIL import Image

    import diagram_engine as de
    from diagram_engine.graph import fidelity as F
    spec = {"diagram_type": "graph", "confidence": 0.95, "labels": [{"text": "x", "confidence": 1}, {"text": "y", "confidence": 1}],
            "graph": {"axes": {"x_min": -3, "x_max": 3, "y_min": -6, "y_max": 6, "show_grid": False, "show_numbers": False},
                      "curves": [{"id": "f", "expression": "x^2-2"}]}, "observed": {"num_curves": 1}}
    png = de.render_spec(de.process("s", json.dumps(spec), "", None).spec)[1]
    im = Image.open(io.BytesIO(png)).convert("L")
    import numpy as np
    a = np.asarray(im)
    ys, xs = np.nonzero(a < 200)
    b = io.BytesIO()
    im.crop((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)).save(b, format="PNG")   # TIGHT crop
    assert F.check(b.getvalue(), png, 1)["decision"] == "PASS"


@pytest.mark.parametrize("src,mine,flag", [
    ("הנקודות (a 0 , ( , ) b 0 , ( , ) ו-(d , 0) הן נקודות החיתוך, הביעו", "הנקודות $(a,0)$, $(b,0)$, $(d,0)$ הן נקודות החיתוך, הביעו", False),
    ("נתון כי AB=AC, D על BC, E על AC.", "נתון כי $AB=AC$ D על BC E על AC.", True)])
def test_comma_gate_ignores_math_commas_but_not_lost_punctuation(src, mine, flag):
    q = c.postprocess_question(c.QuestionAI(topic="t", text=mine), 1, 10, 1)
    assert bool(ts.fidelity_issues(q, src, True)) == flag


def test_short_entity_formula_is_not_false_flagged():
    from diagram_engine import formula_pipeline as fp
    assert fp.cross_check(fp.question_formulas(["מצאו את היחס $\\frac{AD}{CD}$."]), "המרובע ABCD חסום במעגל. מצאו את היחס AD CD") == []
    assert fp.cross_check(fp.question_formulas(["$f(x)=x^{5}-12x$"]), "f(x) = x3 − 12x")        # real conflicts still caught


def test_latex_thousands_separator():
    from diagram_engine import formula_pipeline as fp
    assert fp.analyse("c_{3}+c_{4}+\\dots+c_{m}=44{,}307")["status"] == "OK"



def test_dashed_asymptotes_are_not_axes_and_options_stay_bound():
    import diagram_engine as de
    from diagram_engine.graph import fidelity as F
    H = 1.5707963
    ax = {"x_min": -2, "x_max": 2, "y_min": -3, "y_max": 3, "show_grid": False, "show_numbers": False}
    def opts(first):
        o = [{"label": "I", "formula": {"axes": ax, "curves": [{"id": "i", "pieces": [{"expression": first, "x_from": -H, "x_to": H}]}]}},
             {"label": "II", "formula": {"axes": ax, "curves": [{"id": "ii", "pieces": [{"expression": "-0.5*sin(2*x)", "x_from": -H, "x_to": H}]}]}},
             {"label": "III", "formula": {"axes": ax, "asymptotes": [{"kind": "vertical", "value": -H}, {"kind": "vertical", "value": H}],
                                          "curves": [{"id": "iii", "pieces": [{"expression": "tan(x)-2*sin(2*x)", "x_from": -H + 0.02, "x_to": H - 0.02}]}]}},
             {"label": "IV", "formula": {"axes": ax, "asymptotes": [{"kind": "vertical", "value": -H}, {"kind": "vertical", "value": H}],
                                         "curves": [{"id": "iv", "pieces": [{"expression": "tan(x)", "x_from": -H + 0.02, "x_to": H - 0.02}]}]}}]
        return {"diagram_type": "graph", "subtype": "multi_choice_graphs", "confidence": 0.9, "labels": [],
                "multi_graph": {"columns": 4, "options": o}, "observed": {"num_options": 4}}
    src = de.render_spec(de.process("s", json.dumps(opts("0.5*sin(2*x)")), "", None).spec)[1]
    ok = F.check(src, src, 4)
    assert ok["source_panels"] == 4 and ok["decision"] == "PASS", ok
    wrong = de.render_spec(de.process("s", json.dumps(opts("-0.5*sin(2*x)")), "", None).spec)[1]
    res = F.check(src, wrong, 4)
    assert [o["decision"] for o in res["per_option"]][0] == "MISMATCH" and [o["decision"] for o in res["per_option"]][1:] == ["PASS"] * 3


def test_subpart_entity_not_in_the_figure_is_not_required_for_the_stem_figure():
    ai = c.QuestionAI(topic="t", text="הקטע AB הוא קוטר במעגל. הנקודה D על המעגל.",
                      sections=[c.QuestionSection(section_id="א", text="מצאו את x.", points=10),
                                c.QuestionSection(section_id="ב", text="הנקודה F נמצאת על הצלע DE. מצאו את השטח.", points=10)],
                      figures=[c.FigureRef(description="f", section_id="", bbox=[])])
    q = c.postprocess_question(ai, 1, 20, 1)
    t = c.reconstruction_text(q, q.figures[0], {"A", "B", "C", "D", "E"})
    assert "F נמצאת" not in t
    assert "F נמצאת" in c.reconstruction_text(q, q.figures[0], {"A", "B", "D", "E", "F"})      # F IS drawn -> required


def test_math_list_commas_are_not_punctuation():
    assert ts.punctuation_commas("שאיבריה הם a1 , a2 , a3 ומנתה היא q") == 0
    assert ts.punctuation_commas("נתון כי AB=AC, D על BC, E על AC.") == 2


@pytest.mark.parametrize("visible,kept", [({"18", "6"}, False), ({"60", "30", "40"}, True)])
def test_measurement_givens_bind_to_the_object_that_shows_them(visible, kept):
    ai = c.QuestionAI(topic="t", text="לרון יש מיכל בצורת תיבה. אורכי מקצועות הבסיס שלו הם 60 ס\"מ ו־30 ס\"מ וגובהו 40 ס\"מ.",
                      sections=[c.QuestionSection(section_id="ב", text="בתוך המיכל גליל שרדיוסו 6 ס\"מ וגובהו 18 ס\"מ. מצאו את נפחו.", points=10)],
                      figures=[c.FigureRef(description="f", section_id="ב", bbox=[])])
    q = c.postprocess_question(ai, 1, 20, 1)
    t = c.reconstruction_text(q, q.figures[0], visible)
    assert ("60 ס\"מ" in t) == kept


@pytest.mark.parametrize("text,kind", [("גליל שאורך רדיוס הבסיס שלו הוא 6 ס\"מ", "radius"), ("אורך קוטר המעגל הוא 10 ס\"מ", "diameter"),
                                       ("אורך הצלע הוא 7 ס\"מ", "length"), ("גובהו 18 ס\"מ", "height")])
def test_length_of_a_radius_is_a_radius(text, kind):
    from diagram_engine import text_facts
    facts = [f for f in text_facts.extract(text, required=True) if f.fact_type == "dimension"]
    assert facts and facts[0].value["dimension_type"] == kind
