# -*- coding: utf-8 -*-
"""BLIND HOLDOUT (5 teacher images, never seen by the code). PASS-1 / PASS-2 content written in the model's structure
BEFORE any run; no code was changed for these images before the first run."""
import math


def Q(topic, text, sections, steps, rubric, figures=(), k=0):
    return {"topic": topic, "text": text, "required_sections": k,
            "sections": [{"section_id": a, "text": b, "points": c} for a, b, c in sections],
            "solution_steps": [{"section_id": a, "step_title": b, "content": c, "final_answer": d} for a, b, c, d in steps],
            "rubric_steps": [{"section_id": a, "stage_desc": b, "percentage": p, "full_credit": f, "partial_credit": pc, "zero_credit": z,
                              "carried_over_error_policy": "טעות נגררת — ניקוד מלא על המשך דרך נכון", "common_errors": []}
                             for a, b, p, f, pc, z in rubric],
            "figures": list(figures)}


def fig(desc, bbox, sec=""):
    return {"description": desc, "source_image_index": 1, "bbox": bbox, "figure_type": "source_crop", "rebuild_required": True,
            "rebuild_confidence": 0.95, "render_engine": "", "geogebra_commands": [], "spec_json": "", "section_id": sec}


QUESTIONS, SPECS = [], {}

# ------------------------------------------------------------------ H1: box, vectors (image 1)
QUESTIONS.append(Q("וקטורים במרחב",
    "בסרטוט שלפניכם תיבה $ABCDA'B'C'D'$ שבסיסה $ABCD$ הוא ריבוע.\nהנקודה $F$ היא אמצע המקצוע $BC$.\n"
    "הנקודה $E$ נמצאת על האלכסון $A'C'$, כך שמתקיים $\\overrightarrow{A'E}=\\frac34\\overrightarrow{A'C'}$.\n"
    "נסמן: $\\overrightarrow{AB}=\\underline{u}$, $\\overrightarrow{BC}=\\underline{v}$, $\\overrightarrow{AA'}=\\underline{w}$.",
    [("א", "הביעו באמצעות $\\underline{u}$, $\\underline{v}$ ו־$\\underline{w}$ את הווקטורים $\\overrightarrow{A'E}$ ו־$\\overrightarrow{FE}$.", 5),
     ("ב", "נתון כי אורך מקצוע הבסיס הוא 4. חשבו את האורך של הווקטור $\\overrightarrow{A'E}$.", 4),
     ("ג", "נתון: $|\\overrightarrow{A'E}|=|\\overrightarrow{FE}|$. הראו כי התיבה היא קובייה.", 5),
     ("ד", "(1) הראו כי $\\overrightarrow{FE}$ מאונך ל־$\\overrightarrow{A'C'}$.\n(2) חשבו את שטח המשולש $A'FC'$.", 6)],
    [("א", "A'E", "$\\overrightarrow{A'C'}=\\overrightarrow{AC}=\\underline{u}+\\underline{v}$, ולכן $\\overrightarrow{A'E}=\\frac34\\underline{u}+\\frac34\\underline{v}$.", "$\\overrightarrow{A'E}=\\frac34\\underline{u}+\\frac34\\underline{v}$"),
     ("א", "FE", "$\\overrightarrow{FE}=\\overrightarrow{FB}+\\overrightarrow{BA}+\\overrightarrow{AA'}+\\overrightarrow{A'E}=-\\frac12\\underline{v}-\\underline{u}+\\underline{w}+\\frac34\\underline{u}+\\frac34\\underline{v}$.",
      "$\\overrightarrow{FE}=-\\frac14\\underline{u}+\\frac14\\underline{v}+\\underline{w}$"),
     ("ב", "אורך", "$|\\underline{u}|=|\\underline{v}|=4$ ו־$\\underline{u}\\perp\\underline{v}$: $|\\overrightarrow{A'E}|=\\frac34|\\underline{u}+\\underline{v}|=\\frac34\\cdot4\\sqrt2$.", "$3\\sqrt2$"),
     ("ג", "גובה התיבה", "נסמן $|\\underline{w}|=h$. הווקטורים ניצבים זה לזה: $|\\overrightarrow{FE}|^{2}=\\frac{16}{16}+\\frac{16}{16}+h^{2}=2+h^{2}$.\n"
      "$2+h^{2}=(3\\sqrt2)^{2}=18\\Rightarrow h=4$ — כל המקצועות שווים.", "התיבה היא קובייה."),
     ("ד", "(1) מכפלה סקלרית", "$\\overrightarrow{FE}\\cdot\\overrightarrow{A'C'}=\\left(-\\frac14\\underline{u}+\\frac14\\underline{v}+\\underline{w}\\right)\\cdot(\\underline{u}+\\underline{v})=-\\frac14\\cdot16+\\frac14\\cdot16=0$.", "$FE\\perp A'C'$"),
     ("ד", "(2) שטח", "$E$ על $A'C'$ ו־$FE\\perp A'C'$, לכן $FE$ הוא הגובה לצלע $A'C'$: $S=\\frac12\\cdot A'C'\\cdot FE=\\frac12\\cdot4\\sqrt2\\cdot3\\sqrt2$.", "$S=12$")],
    [("א", "ביטוי הווקטורים", 25, "שני הביטויים נכונים.", "ביטוי אחד נכון.", "—"),
     ("ב", "אורך", 20, "$3\\sqrt2$.", "ביטוי נכון בלי חישוב.", "—"),
     ("ג", "קובייה", 25, "$h=4$ עם שימוש בניצבות.", "משוואה נכונה וטעות חישוב.", "—"),
     ("ד", "ניצבות ושטח", 30, "מכפלה סקלרית 0 ושטח 12.", "אחד מהשניים.", "—")],
    [fig("תיבה ABCDA'B'C'D' עם האלכסון A'C', הנקודות E ו־F", [40, 20, 760, 350])]))
SPECS[1] = [{"diagram_type": "spatial", "subtype": "cuboid", "confidence": 0.93,
             "labels": [{"text": t, "confidence": 0.98} for t in ["A", "B", "C", "D", "A'", "B'", "C'", "D'", "E", "F"]],
             "spatial": {"camera": "OBLIQUE_RIGHT",
                         "solids": [{"id": "box", "kind": "cuboid",
                                     "vertices": {"A": [0, 0, 0], "B": [4, 0, 0], "C": [4, 4, 0], "D": [0, 4, 0],
                                                  "A'": [0, 0, 4], "B'": [4, 0, 4], "C'": [4, 4, 4], "D'": [0, 4, 4]},
                                     "edges": [["A", "B"], ["B", "C"], ["C", "D"], ["D", "A"], ["A'", "B'"], ["B'", "C'"], ["C'", "D'"], ["D'", "A'"],
                                               ["A", "A'"], ["B", "B'"], ["C", "C'"], ["D", "D'"]],
                                     "hidden_edges": [["D", "A"], ["D", "C"], ["D", "D'"]]}],
                         "points_on_edges": [{"id": "F", "a": "B", "b": "C", "ratio": 0.5}],
                         "points_on_diagonals": [{"id": "E", "a": "A'", "b": "C'", "ratio": 0.75}],
                         "construction_segments": [{"a": "A'", "b": "C'", "style": "solid"}, {"a": "E", "b": "F", "style": "dashed"}]},
             "semantics": {"vectors": {"points": [{"id": "A", "x": 0, "y": 0, "z": 0}, {"id": "B", "x": 4, "y": 0, "z": 0},
                                                  {"id": "C", "x": 4, "y": 4, "z": 0}, {"id": "A'", "x": 0, "y": 0, "z": 4},
                                                  {"id": "C'", "x": 4, "y": 4, "z": 4}, {"id": "E", "x": 3, "y": 3, "z": 4},
                                                  {"id": "F", "x": 4, "y": 2, "z": 0}],
                                       "vectors": [{"name": "u", "from_point": "A", "to_point": "B"}, {"name": "v", "from_point": "B", "to_point": "C"},
                                                   {"name": "w", "from_point": "A", "to_point": "A'"},
                                                   {"name": "A'E", "from_point": "A'", "to_point": "E"}, {"name": "A'C'", "from_point": "A'", "to_point": "C'"}],
                                       "claims": [{"kind": "ratio", "refs": ["A'E", "A'C'"], "value": 0.75}]}},
             "observed": {"num_solids": 1, "point_labels": ["A", "A'", "B", "B'", "C", "C'", "D", "D'", "E", "F"]}}]

# ------------------------------------------------------------------ H2: (3x^2-a)e^x and |f| options (image 2)
QUESTIONS.append(Q("פונקציה מעריכית ופונקציית ערך מוחלט",
    "נתונה הפונקצייה $f(x)=(3x^{2}-a)\\cdot e^{x}$, המוגדרת לכל $x$. $a$ הוא פרמטר.\nנתון כי לפונקצייה $f(x)$ יש נקודת קיצון בנקודה שבה $x=1$.",
    [("א", "מצאו את הערך של $a$.", 3),
     ("ב", "הציבו $a=9$ בפונקצייה $f(x)$ וענו על הסעיפים ב–ה. מצאו את שיעורי נקודות הקיצון של הפונקצייה $f(x)$, וקבעו את סוגן.", 4),
     ("ג", "מצאו את שיעורי נקודות החיתוך של גרף הפונקצייה $f(x)$ עם הצירים.", 3),
     ("ד", "סרטטו סקיצה של גרף הפונקצייה $f(x)$.", 3),
     ("ה", "נתונה הפונקצייה $g(x)=|f(x)|$, המוגדרת לכל $x$.\n(1) קבעו איזה מן הגרפים I–IV שלפניכם מתאר את הפונקצייה $g(x)$. נמקו את קביעתכם.\n"
           "(2) מצאו את שיעורי נקודות הקיצון של הפונקצייה $g(x)$, וקבעו את סוגן.", 7)],
    [("א", "נגזרת", "$f'(x)=6x\\,e^{x}+(3x^{2}-a)e^{x}=(3x^{2}+6x-a)e^{x}$. $f'(1)=0\\Rightarrow 9-a=0$.", "$a=9$"),
     ("ב", "קיצון", "$f'(x)=3(x^{2}+2x-3)e^{x}=3(x+3)(x-1)e^{x}$: $x=-3$ (מעבר מחיובי לשלילי), $x=1$ (משלילי לחיובי).",
      "מקסימום $(-3,\\ 18e^{-3})$, מינימום $(1,\\ -6e)$"),
     ("ג", "חיתוך", "$f(0)=-9$; $3x^{2}-9=0\\Rightarrow x=\\pm\\sqrt3$.", "$(0,-9)$, $(\\sqrt3,0)$, $(-\\sqrt3,0)$"),
     ("ד", "סקיצה", "כאשר $x\\to-\\infty$: $f(x)\\to0^{+}$; מקסימום $(-3,18e^{-3})$; חיתוכים $x=\\pm\\sqrt3$; מינימום $(1,-6e)$; $f\\to\\infty$ כאשר $x\\to\\infty$.", "סקיצה לפי הנקודות והתחומים שלעיל."),
     ("ה", "(1) זיהוי", "$g=|f|\\ge0$: אפסים ב־$x=\\pm\\sqrt3$, שיא קטן ב־$x=-3$ ושיא גדול ($6e$) ב־$x=1$, ושאיפה ל־0 משמאל.", "גרף IV"),
     ("ה", "(2) קיצון של g", "המינימום של $f$ (שלילי) הופך למקסימום של $g$; בנקודות האפס יש מינימום (חוד).",
      "מקסימום $(-3,18e^{-3})$, מקסימום $(1,6e)$, מינימום $(-\\sqrt3,0)$ ו־$(\\sqrt3,0)$")],
    [("א", "a", 15, "$a=9$.", "נגזרת נכונה בלבד.", "—"), ("ב", "קיצון", 20, "שתי הנקודות וסוגן.", "נקודה אחת.", "—"),
     ("ג", "חיתוך", 15, "שלוש הנקודות.", "חלק מהן.", "—"), ("ד", "סקיצה", 15, "סקיצה תואמת.", "—", "—"),
     ("ה", "g", 35, "גרף IV וארבע נקודות הקיצון.", "גרף נכון בלבד.", "—")],
    [fig("גרפים I–IV (סעיף ה)", [440, 100, 1000, 850], "ה")]))


def topo(axes, landmarks, branches, asy=()):
    return {"function_label": "", "axes": {**axes, "show_grid": False, "show_numbers": False},
            "landmarks": [{"x": x, "y": y, "kind": k, "style": "none"} for x, y, k in landmarks],
            "branches": branches, "asymptotes": [{"kind": a, "value": v} for a, v in asy]}


AX2 = {"x_min": -6, "x_max": 3, "y_min": -1.5, "y_max": 18, "y_label": "y"}
SPECS[2] = [{"diagram_type": "graph", "subtype": "multi_choice_graphs", "confidence": 0.9,
             "labels": [{"text": t, "confidence": 0.98} for t in ("I", "II", "III", "IV")],
             "multi_graph": {"columns": 2, "options": [
                 {"label": "I", "topology": topo(AX2, [(-5.5, 11, "marked"), (-1.8, 12.5, "max"), (0.35, 0, "min")],
                                                 [{"landmarks": [0, 1, 2], "left": {"toward": "stop"}, "right": {"toward": "plus_inf"}, "x_from": -6}])},
                 {"label": "II", "topology": topo(AX2, [(-0.5, 0, "endpoint"), (-0.25, 15, "max"), (0.2, 0, "min"), (0.9, 0.6, "max")],
                                                  [{"landmarks": [0, 1, 2, 3], "left": {"toward": "stop"}, "right": {"toward": "asymptote", "value": 0}}])},
                 {"label": "III", "topology": topo(AX2, [(-0.8, 0, "min"), (0.9, 11, "max"), (2.8, 10, "marked")],
                                                   [{"landmarks": [0, 1, 2], "left": {"toward": "plus_inf"}, "right": {"toward": "stop"}, "x_to": 3}])},
                 {"label": "IV", "formula": {"axes": {**AX2, "show_grid": False, "show_numbers": False},
                                             "curves": [{"id": "g", "expression": "abs((3*x^2-9)*exp(x))"}]}}]},
             "observed": {"num_options": 4}}]

# ------------------------------------------------------------------ H3: x^2/(-6+4ln x) options (image 3)
E15 = math.exp(1.5)
QUESTIONS.append(Q("פונקציה לוגריתמית",
    "נתונה הפונקצייה $f(x)=\\frac{x^{2}}{-6+4\\ln(x)}$.",
    [("א", "(1) מצאו את תחום ההגדרה של הפונקצייה $f(x)$.\n(2) מצאו את משוואת האסימפטוטה המאונכת לציר ה־$x$ של הפונקצייה $f(x)$.", 4),
     ("ב", "האם גרף הפונקצייה $f(x)$ חותך את ציר ה־$x$? נמקו את תשובתכם.", 3),
     ("ג", "(1) מצאו את שיעורי נקודת הקיצון של הפונקצייה $f(x)$, וקבעו את סוגה.\n(2) מצאו את תחומי העלייה והירידה של הפונקצייה $f(x)$.", 5),
     ("ד", "תחום ההגדרה של פונקציית הנגזרת $f'(x)$ זהה לתחום ההגדרה של הפונקצייה $f(x)$.\n"
           "(1) קבעו איזה מן הגרפים I–IV שלפניכם מתאר את הפונקצייה $f(x)$, ואיזה מהם מתאר את פונקציית הנגזרת $f'(x)$. נמקו את קביעותיכם.\n"
           "(2) חשבו את השטח המוגבל על ידי גרף פונקציית הנגזרת $f'(x)$, על ידי ציר ה־$x$ ועל ידי הישר $x=e^{3}$.", 8)],
    [("א", "תחום ואסימפטוטה", "$x>0$ וגם $-6+4\\ln x\\ne0\\Rightarrow x\\ne e^{1.5}$.", "תחום: $x>0,\\ x\\ne e^{1.5}$; אסימפטוטה: $x=e^{1.5}$"),
     ("ב", "חיתוך", "$f(x)=0\\Rightarrow x=0$, אך $x=0$ אינו בתחום ההגדרה.", "לא"),
     ("ג", "(1) קיצון", "$f'(x)=\\frac{2x(-6+4\\ln x)-4x}{(-6+4\\ln x)^{2}}=\\frac{2x(4\\ln x-8)}{(-6+4\\ln x)^{2}}=0\\Rightarrow \\ln x=2$.\n"
      "משמאל ל־$e^{2}$ (בתחום $e^{1.5}<x<e^{2}$) $f'<0$, מימין $f'>0$.", "מינימום $\\left(e^{2},\\ \\frac{e^{4}}{2}\\right)$"),
     ("ג", "(2) עלייה וירידה", "סימן $f'$ כסימן $4\\ln x-8$.", "עולה: $x>e^{2}$; יורדת: $0<x<e^{1.5}$ וגם $e^{1.5}<x<e^{2}$"),
     ("ד", "(1) זיהוי", "$f<0$ משמאל לאסימפטוטה ו־$f\\to0^{-}$ כאשר $x\\to0^{+}$; מימין לה מינימום — גרף IV. "
      "$f'<0$ משמאל לאסימפטוטה ו־$f'\\to-\\infty$ משני צדיה, מתאפסת ב־$e^{2}$ ועולה — גרף II.", "$f$ — גרף IV, $f'$ — גרף II"),
     ("ד", "(2) שטח", "$f'>0$ בתחום $e^{2}<x<e^{3}$: $S=\\int_{e^{2}}^{e^{3}}f'(x)dx=f(e^{3})-f(e^{2})=\\frac{e^{6}}{6}-\\frac{e^{4}}{2}$.",
      "$S=\\frac{e^{6}}{6}-\\frac{e^{4}}{2}\\approx39.94$")],
    [("א", "תחום ואסימפטוטה", 20, "שניהם.", "אחד.", "—"), ("ב", "חיתוך", 15, "לא, עם נימוק.", "—", "—"),
     ("ג", "קיצון ומונוטוניות", 25, "מינימום ותחומים.", "חלקי.", "—"), ("ד", "זיהוי ושטח", 40, "IV, II ושטח.", "זיהוי בלבד.", "—")],
    [fig("גרפים I–IV (סעיף ד)", [300, 40, 1000, 990], "ד")]))


def fpcs(pieces):
    return [{"expression": e, "x_from": a, "x_to": b} for e, a, b in pieces]


AX3 = {"x_min": -1, "x_max": 14, "show_grid": False, "show_numbers": False, "y_label": "y"}
FP = "2*x*(4*ln(x)-8)/(4*ln(x)-6)^2"
SPECS[3] = [{"diagram_type": "graph", "subtype": "multi_choice_graphs", "confidence": 0.9,
             "labels": [{"text": t, "confidence": 0.98} for t in ("I", "II", "III", "IV")],
             "multi_graph": {"columns": 2, "options": [
                 {"label": "I", "formula": {"axes": {**AX3, "y_min": -6, "y_max": 6}, "asymptotes": [{"kind": "vertical", "value": E15}],
                                            "curves": [{"id": "i", "pieces": fpcs([(f"-({FP})", 0.001, E15 - 1e-3), (FP, E15 + 1e-3, 14)])}],
                                            "points": [{"name": "", "x": 0, "y": 0, "kind": "marked", "style": "open"}]}},
                 {"label": "II", "formula": {"axes": {**AX3, "y_min": -6, "y_max": 6}, "asymptotes": [{"kind": "vertical", "value": E15}],
                                             "curves": [{"id": "fp", "expression": FP}],
                                             "points": [{"name": "", "x": 0, "y": 0, "kind": "marked", "style": "open"}]}},
                 {"label": "III", "formula": {"axes": {**AX3, "y_min": -6, "y_max": 6}, "asymptotes": [{"kind": "vertical", "value": E15}],
                                              "curves": [{"id": "iii", "pieces": fpcs([(FP, 0.001, E15 - 1e-3), (f"1.5+2/(x-{E15})", E15 + 1e-3, 14)])}],
                                              "points": [{"name": "", "x": 0, "y": 0, "kind": "marked", "style": "open"}]}},
                 {"label": "IV", "formula": {"axes": {**AX3, "y_min": -40, "y_max": 80}, "asymptotes": [{"kind": "vertical", "value": E15}],
                                             "curves": [{"id": "f", "expression": "x^2/(-6+4*ln(x))"}],
                                             "points": [{"name": "", "x": 0, "y": 0, "kind": "marked", "style": "open"}]}}]},
             "observed": {"num_options": 4}}]

# ------------------------------------------------------------------ H4: equilateral triangle in a circle (image 4)
R = math.sqrt(3)
QUESTIONS.append(Q("גאומטרייה: מעגל, משולש שווה צלעות, דמיון",
    "$ABC$ הוא משולש שווה צלעות החסום במעגל.\nהנקודה $D$ נמצאת על המשך הצלע $BC$, כמתואר בסרטוט.\nהקטע $AD$ חותך את המעגל בנקודה $E$.",
    [("א", "הוכיחו: $\\angle AEB=\\angle BEC=\\angle CED=60^{\\circ}$.", 5), ("ב", "הוכיחו: $\\triangle AEB\\sim\\triangle CED$.", 5),
     ("ג", "הוכיחו: $\\frac{AE}{CE}=\\frac{BC}{CD}$.", 4),
     ("ד", "נתון כי שטח המשולש $AEB$ גדול פי 2.25 משטח המשולש $CED$. מצאו פי כמה גדול שטח המשולש $ABD$ משטח המשולש $CED$.", 6)],
    [("א", "זוויות היקפיות", "$\\angle AEB=\\angle ACB=60^{\\circ}$ ו־$\\angle BEC=\\angle BAC=60^{\\circ}$ (נשענות על אותן קשתות).\n"
      "$\\angle AEC=120^{\\circ}$, ו־$A,E,D$ על ישר אחד: $\\angle CED=180^{\\circ}-120^{\\circ}=60^{\\circ}$.", "הוכח."),
     ("ב", "דמיון", "$\\angle AEB=\\angle CED=60^{\\circ}$. במרובע החסום $ABCE$: $\\angle BAE+\\angle BCE=180^{\\circ}$, ולכן $\\angle ECD=\\angle BAE$ (ז.ז.).", "הוכח."),
     ("ג", "יחס", "מהדמיון: $\\frac{AE}{CE}=\\frac{AB}{CD}$, ו־$AB=BC$ (משולש שווה צלעות).", "הוכח."),
     ("ד", "יחס דמיון", "יחס השטחים $2.25$ ⇒ יחס הדמיון $1.5$: $\\frac{BC}{CD}=1.5$. נסמן $CD=2k$, $BC=3k$.", ""),
     ("ד", "שטחים", "חזקת הנקודה $D$: $DC\\cdot DB=DE\\cdot DA\\Rightarrow 2k\\cdot5k=DE\\cdot DA$. במשולש $ABD$ ($\\angle ABD=60^{\\circ}$): "
      "$AD^{2}=9k^{2}+25k^{2}-2\\cdot3k\\cdot5k\\cdot\\frac12=19k^{2}$, ולכן $\\frac{DE}{DA}=\\frac{10k^{2}}{19k^{2}}=\\frac{10}{19}$.\n"
      "$\\frac{S_{CED}}{S_{CAD}}=\\frac{DE}{DA}=\\frac{10}{19}$ ו־$\\frac{S_{CAD}}{S_{ABD}}=\\frac{CD}{BD}=\\frac25$, לכן $S_{CED}=\\frac{4}{19}S_{ABD}$.",
      "$\\frac{S_{ABD}}{S_{CED}}=\\frac{19}{4}=4.75$")],
    [("א", "זוויות", 25, "שלוש הזוויות עם נימוק.", "שתיים.", "—"), ("ב", "דמיון", 25, "שתי זוויות שוות עם נימוק.", "זווית אחת.", "—"),
     ("ג", "יחס", 20, "יחס מהדמיון ו־AB=BC.", "—", "—"), ("ד", "יחס שטחים", 30, "$4.75$.", "יחס דמיון 1.5 בלבד.", "—")],
    [fig("משולש שווה צלעות חסום במעגל, D על המשך BC, E על המעגל", [40, 20, 780, 470])]))
Bx, Cx = 0.0, 3.0
SPECS[4] = [{"diagram_type": "geometry", "subtype": "circle_geometry", "confidence": 0.95,
             "labels": [{"text": t, "confidence": 0.99} for t in "ABCDE"],
             "geometry": {"points": [{"id": "O", "x": 1.5, "y": R / 2, "hidden": True}, {"id": "A", "x": 1.5, "y": round(3 * R / 2, 9)},
                                     {"id": "B", "x": 0, "y": 0}, {"id": "C", "x": 3, "y": 0}, {"id": "D", "x": 5, "y": 0},
                                     {"id": "E", "x": round(60 / 19, 9), "y": round(15 * R / 19, 9)}],
                          "circles": [{"id": "c", "center": "O", "through": "A"}],
                          "segments": [{"a": "A", "b": "B"}, {"a": "A", "b": "C"}, {"a": "B", "b": "D"}, {"a": "A", "b": "D"},
                                       {"a": "B", "b": "E"}, {"a": "C", "b": "E"}]},
             "observed": {"num_points": 5, "point_labels": list("ABCDE"), "num_circles": 1}}]

# ------------------------------------------------------------------ H5: (4x-2)^3 and y=3x+b (image 5)
bval, tval = 0.3, 0.7
yA = (4 * tval - 2) ** 3
xB = (yA - bval) / 3
QUESTIONS.append(Q("בעיית קיצון עם פרמטר",
    "בסרטוט שלפניכם מתוארים גרף הפונקצייה $f(x)=(4x-2)^{3}$ והישר $y=3x+b$. $b$ הוא פרמטר חיובי.\n"
    "הנקודה $A$ נמצאת על גרף הפונקצייה $f(x)$ כך ששיעור ה־$x$ שלה קטן משיעור ה־$x$ של נקודת החיתוך של גרף הפונקצייה $f(x)$ עם הישר הנתון.\n"
    "הנקודה $B$ נמצאת על הישר הנתון כך שהקטע $AB$ מקביל לציר ה־$x$.\nנסמן ב־$t$ את שיעור ה־$x$ של הנקודה $A$. נתון: $0\\le t\\le 0.7$.",
    [("א", "הביעו באמצעות $b$ ו־$t$ את שיעור ה־$x$ של הנקודה $B$.", 6),
     ("ב", "(1) מצאו את הערך של $t$ שבעבורו אורך הקטע $AB$ הוא מינימלי.\n(2) מצאו את הערך של $t$ שבעבורו אורך הקטע $AB$ הוא מקסימלי.", 14)],
    [("א", "שיעור B", "$y_A=(4t-2)^{3}$; ל־$B$ אותו שיעור $y$ על הישר: $3x_B+b=(4t-2)^{3}$.", "$x_B=\\frac{(4t-2)^{3}-b}{3}$"),
     ("ב", "אורך AB", "$A$ מימין ל־$B$: $AB=t-x_B=\\frac{3t-(4t-2)^{3}+b}{3}$.\n$\\frac{d}{dt}AB=1-4(4t-2)^{2}=0\\Rightarrow 4t-2=\\pm\\frac12\\Rightarrow t=\\frac38,\\ t=\\frac58$.", ""),
     ("ב", "(1) מינימום", "$\\frac{d^{2}}{dt^{2}}AB=-32(4t-2)$: ב־$t=\\frac38$ חיובית — מינימום. בקצוות: $AB(0)=\\frac{8+b}{3}$, $AB(0.7)=\\frac{1.588+b}{3}$ — גדולים מ־$AB(\\frac38)=\\frac{1.25+b}{3}$.", "$t=\\frac38$"),
     ("ב", "(2) מקסימום", "ב־$t=\\frac58$ מקסימום מקומי: $AB=\\frac{1.75+b}{3}$, אך בקצה $t=0$: $AB=\\frac{8+b}{3}$ — גדול יותר.", "$t=0$")],
    [("א", "x_B", 30, "ביטוי נכון.", "משוואה נכונה בלבד.", "—"),
     ("ב", "מינימום ומקסימום", 70, "$t=\\frac38$ מינימום ו־$t=0$ מקסימום (כולל בדיקת קצוות).", "$t=\\frac58$ כמקסימום בלי בדיקת קצוות.", "—")],
    [fig("גרף f(x)=(4x-2)^3, הישר y=3x+b והקטע AB", [60, 30, 960, 330])]))
SPECS[5] = [{"diagram_type": "mixed_graph_geometry", "subtype": "", "confidence": 0.9,
             "labels": [{"text": t, "confidence": 0.98} for t in ("A", "B", "x", "y")],
             "mixed": {"graph": {"axes": {"x_min": -1.2, "x_max": 1.25, "y_min": -9, "y_max": 5, "x_label": "x", "y_label": "y",
                                          "show_grid": False, "show_numbers": False},
                                 "curves": [{"id": "f", "expression": "(4*x-2)^3"}, {"id": "l", "expression": f"3*x+{bval}"}]},
                       "geometry": {"points": [{"id": "A", "x": tval, "y": round(yA, 9)}, {"id": "B", "x": round(xB, 9), "y": round(yA, 9)}],
                                    "segments": [{"a": "A", "b": "B", "style": "dashed"}]}},
             "symbols": {"b": {"value": bval, "kind": "parameter"}},
             "observed": {"num_curves": 2, "point_labels": ["A", "B"]}}]
