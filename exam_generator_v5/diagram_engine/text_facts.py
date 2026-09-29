"""Hebrew Mathematical Parser V2: explicit facts of the question text -> Facts (required=True for the stem).

Handles real Bagrut formulations (Hebrew + LaTeX), points with primes (A', C'), extensions, axes, circles, tangents,
diagonals, ratios, dimensions with their MEANING (radius != diameter), coordinates, formulas and declared parameters."""
from __future__ import annotations

import re
from fractions import Fraction

from .fact_graph import Fact
from .text_utils import normalize_math_text

P = r"[A-Z](?:''|'|_\d+)?"             # a point: A, A', A'', A_1 (prime-safe: A != A' != A'')
PN = rf"((?:{P}){{2,}})"                # a name made of points (segment / polygon)
B = r"(?<![A-Za-z'_])"                  # left boundary
E = r"(?![A-Za-z_'])"                   # right boundary
SEP = r"\s*[,،]\s*|\s+ו-?\s*|\s+ו"


def label_key(text: str) -> str:
    """Normalised label text: '(18, −2a)' and '(18 , -2a)' are the same label."""
    return re.sub(r"\s+", "", (text or "").replace("−", "-"))


def points_of(name: str) -> list[str]:
    return re.findall(P, name)


def _norm(text: str) -> str:
    s = normalize_math_text(text or "")
    s = re.sub(r"(?<=[\u0590-\u05FF])''(?=[\u0590-\u05FF])", '"', s)     # ס''מ -> ס"מ (only between Hebrew letters: A'' stays a point)
    s = s.replace("″", "''").replace("״", '"').replace("׳", "'").replace("“", '"').replace("”", '"').replace("„", '"')
    return (s.replace("′", "'").replace("’", "'").replace("`", "'").replace("−", "-").replace("־", "-")
             .replace("\\prime", "'").replace("^{'}", "'").replace("^'", "'"))


def _list(chunk: str) -> list[str]:
    return [p for p in re.split(r"[,،\s]+|ו-?", chunk) if re.fullmatch(P, p or "")]


UNIT = r"(סמ\"ר|סמ\"ק|ס\"מ|מ\"מ|ק\"מ|מטרים|מטר|מ'|סמ|cm|m)"
DIM_WORDS = {"רדיוס": "radius", "קוטר": "diameter", "גובה": "height", "רוחב": "width", "עומק": "depth", "אורך": "length",
             "אורכ": "length", "צלע": "side", "מרחק": "distance"}
# morphology: אורך/אורכו/שאורכו, גובה/גובהו/שגובהו, רדיוס/רדיוסו, קוטר/קוטרו, רוחב/רוחבו ...
DIM_RE = r"(?<![\u0590-\u05FF])[והב]?ש?(רדיוס|קוטר|גובה|רוחב|עומק|אורך|אורכ|צלע|מרחק)(?:ו|ה|ם|ן)?(?![\u0590-\u05FF])"
ENTITY_WORDS = {"גליל": "cylinder", "כוס": "cylinder", "תיבה": "cuboid", "אקווריום": "cuboid", "קרטון": "cuboid",
                "קובייה": "cuboid", "מלבן": "polygon", "ריבוע": "polygon", "מעגל": "circle", "חרוט": "cone", "פירמידה": "polyhedron"}


def extract(text: str, required: bool = True) -> list[Fact]:
    s = _norm(text)
    out: list[Fact] = []

    def add(t: str, ents: list[str], value=None, raw: str = "") -> None:
        out.append(Fact(fact_type=t, entities=ents, value=value, source="question_text", required=required, raw_text=raw.strip()))

    # ---- triangles and polygons
    for m in re.finditer(rf"(?:{B}{PN}{E}\s*(?:הוא|היא)?\s*משולש\s*שווה[- ]?צלעות|(?:המשולש|משולש)\s*{PN}{E}\s*(?:הוא\s*)?(?:משולש\s*)?שווה[- ]?צלעות)", s):
        name = m.group(1) or m.group(2)
        pts = points_of(name)
        if len(pts) == 3:
            add("equilateral", pts, raw=m.group(0))
    for m in re.finditer(rf"(?:{B}{PN}{E}\s*(?:הוא|היא)?\s*משולש\s*שווה[- ]?שוקיים|(?:המשולש|משולש)\s*{PN}{E}\s*(?:הוא\s*)?(?:משולש\s*)?שווה[- ]?שוקיים)", s):
        name = m.group(1) or m.group(2)
        pts = points_of(name)
        if len(pts) == 3:
            add("triangle", pts, "isosceles", raw=m.group(0))
    # ---- equalities between segments (chains), ratios between segments
    for m in re.finditer(rf"{B}((?:{P}){{2}})(\s*=\s*(?:{P}){{2}}{E})+", s):
        segs = [points_of(t) for t in re.findall(rf"(?:{P}){{2}}", m.group(0))]
        for a, b in zip(segs, segs[1:]):
            add("equal_length", a + b, raw=m.group(0))
    for m in re.finditer(rf"{B}((?:{P}){{2}})\s*=\s*(\d+)\s*/\s*(\d+)\s*\*?\s*((?:{P}){{2}}){E}", s):
        a, b = points_of(m.group(1)), points_of(m.group(4))
        if a[0] == b[0] and len(set(a + b)) == 3:        # A'E = 3/4 A'C'  -> E at 3/4 from A' on A'C'
            add("ratio_on_segment", [a[1], b[0], b[1]], float(Fraction(int(m.group(2)), int(m.group(3)))), raw=m.group(0))
    # ---- parallel / perpendicular (symbols and words), axes
    for m in re.finditer(rf"{B}((?:{P}){{2}})\s*∥\s*((?:{P}){{2}}){E}", s):
        add("parallel", points_of(m.group(1)) + points_of(m.group(2)), raw=m.group(0))
    for m in re.finditer(rf"{B}((?:{P}){{2}})\s*⊥\s*((?:{P}){{2}}){E}", s):
        add("perpendicular", points_of(m.group(1)) + points_of(m.group(2)), raw=m.group(0))
    for m in re.finditer(rf"{B}(?:הישר|הקטע|הצלע)?\s*((?:{P}){{2}}){E}\s*(מקביל|מאונכ|מאונך|ניצב)[הת]?\s*ל-?\s*(?:ציר|צלע|ישר|קטע)?\s*(?:ה[-]?)?\s*(x|y|(?:{P}){{2}})", s):
        seg, rel, tgt = points_of(m.group(1)), m.group(2), m.group(3)
        if tgt in ("x", "y"):
            kind = ("parallel_to_" if rel == "מקביל" else "perpendicular_to_") + tgt + "_axis"
            # AB ⟂ x-axis is the same fact as AB ∥ y-axis (stored in the canonical form)
            kind = {"perpendicular_to_x_axis": "parallel_to_y_axis", "perpendicular_to_y_axis": "parallel_to_x_axis"}.get(kind, kind)
            add(kind, seg, raw=m.group(0))
        else:
            add("parallel" if rel == "מקביל" else "perpendicular", seg + points_of(tgt), raw=m.group(0))
    # ---- angles
    tris = re.findall(rf"(?:משולש|triangle)\s*(?:ישר[- ]זווית|שווה[- ]שוקיים|שווה[- ]צלעות)?\s*((?:{P}){{3}}){E}", s)
    for m in re.finditer(rf"∠\s*((?:{P}){{3}}|{P})\s*=\s*(\d+(?:\.\d+)?)\s*°?", s):
        pts = points_of(m.group(1))
        if len(pts) == 1:
            tri = next((points_of(t) for t in tris if pts[0] in points_of(t)), None)
            if not tri:
                continue
            o = [c for c in tri if c != pts[0]]
            pts = [o[0], pts[0], o[1]]
        if abs(float(m.group(2)) - 90) < 1e-9:
            add("right_angle", pts, raw=m.group(0))
        else:
            add("angle_value", pts, float(m.group(2)), raw=m.group(0))
    # ---- midpoint
    for m in re.finditer(rf"{B}({P})\s*(?:היא|הוא)?\s*(?:נקודת\s+)?(?:אמצע|האמצע של|midpoint of)\s*(?:הצלע|הקטע|המקצוע|של)?\s*((?:{P}){{2}}){E}", s):
        add("midpoint", [m.group(1)] + points_of(m.group(2)), raw=m.group(0))
    # ---- points on segment / diagonal / edge / extension
    for m in re.finditer(rf"(?:הנקודה\s*)?{B}({P})\s*(?:נמצאת|נמצא|מונחת|מונח)\s*על\s*(הצלע|הקטע|המקצוע|האלכסון|הישר|המשך(?:\s*הקטע|\s*הצלע)?)\s*((?:{P}){{2}}){E}", s):
        p, where, seg = m.group(1), m.group(2), points_of(m.group(3))
        if where.startswith("המשך"):
            add("point_order", seg + [p], raw=m.group(0))
            add("collinear", seg + [p], raw=m.group(0))
        elif where == "הישר":
            add("point_on_line", [p] + seg, raw=m.group(0))
        else:
            add("point_on_segment", [p] + seg, raw=m.group(0))
    for m in re.finditer(rf"המשך\s*(?:הקטע|הצלע)?\s*((?:{P}){{2}}){E}\s*(?:חותך|פוגש)\s*(?:את\s*)?(ציר\s*ה?-?\s*[xy]|(?:הקטע|הישר|הצלע)?\s*(?:{P}){{2}}|המעגל)?[^.]*?בנקודה\s*({P})", s):
        seg, tgt, p = points_of(m.group(1)), (m.group(2) or ""), m.group(3)
        add("point_order", seg + [p], raw=m.group(0))
        add("collinear", seg + [p], raw=m.group(0))
        if re.search(r"ציר.*x", tgt):
            add("on_x_axis", [p], raw=m.group(0))
        elif re.search(r"ציר.*y", tgt):
            add("on_y_axis", [p], raw=m.group(0))
        elif "המעגל" in tgt:
            add("on_circle", [p], raw=m.group(0))
    # ---- a segment/line cuts the circle / an axis / another segment at a point
    for m in re.finditer(rf"{B}(?:הקטע|הישר|הצלע)?\s*((?:{P}){{2}}){E}\s*חותך\s*את\s*(המעגל|ציר\s*ה?-?\s*[xy]|(?:הקטע|הישר|הצלע)?\s*(?:{P}){{2}})\s*(?:גם\s*)?בנקודה\s*({P})", s):
        seg, tgt, p = points_of(m.group(1)), m.group(2), m.group(3)
        if "המעגל" in tgt:
            add("point_on_line", [p] + seg, raw=m.group(0))
            add("on_circle", [p], raw=m.group(0))
        elif re.search(r"ציר.*x", tgt):
            add("point_on_line", [p] + seg, raw=m.group(0))
            add("on_x_axis", [p], raw=m.group(0))
        elif re.search(r"ציר.*y", tgt):
            add("point_on_line", [p] + seg, raw=m.group(0))
            add("on_y_axis", [p], raw=m.group(0))
        else:
            other = points_of(re.search(rf"(?:{P}){{2}}", tgt).group(0))
            add("intersection", [p] + seg + other, raw=m.group(0))
    # ---- collinear / concyclic lists
    for m in re.finditer(rf"(?:הנקודות\s*)?((?:{P})(?:(?:{SEP})(?:{P})){{2,}})\s*(?:נמצאות|נמצאים)\s*על\s*(ישר\s*אחד|אותו\s*ישר|אותו\s*מעגל|מעגל\s*אחד|המעגל)", s):
        pts = _list(m.group(1))
        if "מעגל" in m.group(2):
            add("concyclic", pts, raw=m.group(0))
            for p in pts:
                add("on_circle", [p], raw=m.group(0))
        else:
            add("collinear", pts, raw=m.group(0))
    for m in re.finditer(rf"(?:הנקודה\s*)?{B}({P})\s*(?:נמצאת|נמצא)\s*על\s*(?:ה)?מעגל", s):
        add("on_circle", [m.group(1)], raw=m.group(0))
    for m in re.finditer(rf"(?:הנקודה\s*)?{B}({P})\s*(?:נמצאת|נמצא)\s*על\s*ציר\s*ה?-?\s*([xy])", s):
        add("on_" + m.group(2) + "_axis", [m.group(1)], raw=m.group(0))
    for m in re.finditer(rf"מרכז\s*המעגל\s*({P})?\s*[^.]*?(?:נמצא|נמצאת)\s*על\s*ציר\s*ה?-?\s*([xy])", s):
        if m.group(1):
            add("on_" + m.group(2) + "_axis", [m.group(1)], raw=m.group(0))
    for m in re.finditer(rf"(?:מעגל\s*שמרכזו|מרכז\s*המעגל(?:\s*הוא)?)\s*({P})", s):
        add("circle_center", [m.group(1)], raw=m.group(0))
    # ---- circle roles
    for m in re.finditer(rf"{B}((?:{P}){{2}}){E}\s*(?:הוא|היא)\s*(קוטר|מיתר|רדיוס)", s):
        add({"קוטר": "diameter", "מיתר": "chord", "רדיוס": "radius"}[m.group(2)], points_of(m.group(1)), raw=m.group(0))
    for m in re.finditer(rf"דרך\s*(?:הנקודה\s*)?({P})\s*(?:מעבירים|העבירו|עובר|הועבר)\s*משיק\s*(?:למעגל)?(?:[^.]*?בנקודה\s*({P}))?", s):
        add("tangent", [m.group(1)] + ([m.group(2)] if m.group(2) else []), raw=m.group(0))
    for m in re.finditer(rf"{B}((?:{P}){{2}}){E}\s*(?:הוא\s*|היא\s*)?(?:משיק|משיקה)\s*(?:למעגל)?\s*(?:בנקודה\s*({P}))?", s):
        seg = points_of(m.group(1))
        t = m.group(2) or seg[0]
        other = [q for q in seg if q != t]
        add("tangent", [t] + other[:1], raw=m.group(0))
    # ---- coordinates, dimensions
    for name, x, y in re.findall(rf"{B}({P})\s*\(\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)", s):
        add("coordinate", [name], [float(x), float(y)])
    for m in re.finditer(DIM_RE + rf"[^.\d]{{0,40}}?(?:הוא|היא|=|של)?\s*(\d+(?:\.\d+)?)\s*{UNIT}", s):
        sent_start = max(s.rfind(".", 0, m.start()), s.rfind("\n", 0, m.start())) + 1
        before = s[sent_start:m.end()]                              # the SAME sentence only
        seg = re.findall(rf"(?:הקטע|הצלע|המקצוע|קטע|צלע)\s*((?:{P}){{2}}){E}", before)
        ent_kind, best = None, None
        for w, k in ENTITY_WORDS.items():                           # the object word NEAREST to the dimension word
            for om in re.finditer(w, before):
                d = abs((sent_start + om.start()) - m.start())
                if best is None or d < best:
                    best, ent_kind = d, k
        entity = "".join(points_of(seg[-1])) if seg else ent_kind
        idx = None                                                   # "הגליל השני" / "גליל 2" / "cylinder_2"
        om = re.search(r"(?:ה(?:גליל|תיבה|כוס|קובייה|מלבן)\s*ה?(ראשון|ראשונה|שני|שנייה|שלישי|שלישית|רביעי|רביעית))|"
                       r"(?:(?:גליל|תיבה|כוס|קובייה)\s*(?:מס(?:פר|')?\s*)?(\d+))|(?:[a-z]+_(\d+))", before)
        if om:
            words = {"ראשון": 1, "ראשונה": 1, "שני": 2, "שנייה": 2, "שלישי": 3, "שלישית": 3, "רביעי": 4, "רביעית": 4}
            idx = words.get(om.group(1)) if om.group(1) else int(om.group(2) or om.group(3))
        dim_word = m.group(1)
        if dim_word in ("אורך", "אורכ"):                             # "אורך רדיוס הבסיס" = a RADIUS (the specific word wins)
            spec_m = re.search(r"(רדיוס|קוטר|גובה|רוחב|עומק)", s[m.end(1):m.start(2)])
            if spec_m:
                dim_word = spec_m.group(1)
        add("dimension", points_of(seg[-1]) if seg else [], {"dimension_type": DIM_WORDS[dim_word], "value": float(m.group(2)),
                                                              "unit": m.group(3), "entity": entity, "entity_kind": "segment" if seg else ent_kind,
                                                              "entity_index": idx},
            raw=m.group(0))
    # ---- semantic polygons (explicit words only; never from appearance)
    SEM = {"מלבן": "rectangle", "ריבוע": "square", "מקבילית": "parallelogram", "מעוין": "rhombus", "טרפז": "trapezoid",
           "דלתון": "kite"}
    for m in re.finditer(rf"(?:ה?(מלבן|ריבוע|מקבילית|מעוין|טרפז|דלתון)\s*((?:{P}){{4}}){E}|{B}((?:{P}){{4}}){E}\s*(?:הוא\s*|היא\s*)?(מלבן|ריבוע|מקבילית|מעוין|טרפז|דלתון))", s):
        kind = SEM[m.group(1) or m.group(4)]
        pts = points_of(m.group(2) or m.group(3))
        if kind in ("trapezoid", "kite"):
            out.append(Fact(fact_type="needs_review", entities=pts, value=f"{kind}: אילו צלעות מקבילות/שוות אינו מפורש",
                            source="question_text", required=False, raw_text=m.group(0)))
        else:
            add(kind, pts, raw=m.group(0))
    for m in re.finditer(rf"(?:משולש\s*)?ישר[- ]זווית\s*((?:{P}){{3}}){E}", s):
        if not re.search(r"∠|=\s*90|זווית\s+[A-Z]\s+(?:היא\s+)?ישרה", s):
            out.append(Fact(fact_type="needs_review", entities=points_of(m.group(1)), value="משולש ישר זווית: הקודקוד הישר אינו מפורש",
                            source="question_text", required=False, raw_text=m.group(0)))
    for f in list(out):
        if f.fact_type == "triangle" and f.value == "isosceles" and not any(g.fact_type == "equal_length" for g in out):
            out.append(Fact(fact_type="needs_review", entities=f.entities, value="משולש שווה שוקיים: השוקיים אינן מפורשות",
                            source="question_text", required=False, raw_text=f.raw_text))
    for m in re.finditer(rf"(?:המשולש|משולש|המרובע|מרובע|המלבן|הריבוע|ה)?\s*((?:{P}){{3,4}}){E}\s*(?:ה)?חסו(?:ם|מה|י)\s*במעגל", s):
        for p in points_of(m.group(1)):
            add("on_circle", [p], raw=m.group(0))
    for m in re.finditer(rf"דרך\s*(?:הנקודה\s*)?({P})\s*(?:מעבירים|העבירו|עובר|הועבר)\s*משיק\s*(?:למעגל)?\s*(?:ה)?חותך\s*את\s*ציר\s*ה?-?\s*([xy])\s*בנקודה\s*({P})", s):
        t, ax, f_ = m.group(1), m.group(2), m.group(3)
        add("tangent", [t, f_], raw=m.group(0))
        add("on_" + ax + "_axis", [f_], raw=m.group(0))
    for m in re.finditer(r"באמצעות\s*((?:[a-z](?:\s*[,،]\s*|\s+ו-?)?){2,})", s):
        for v in re.findall(r"[a-z]", m.group(1)):
            add("vector_label", [v], raw=m.group(0))
    for m in re.finditer(rf"(?:הבע|הביעו|בטא|בטאו|חשב|חשבו|מצא|מצאו)[^.]*?(?:את|ואת)\s*((?:{P}){{2}}){E}(?:\s*ואת\s*((?:{P}){{2}}){E})?", s):
        for g in (m.group(1), m.group(2)):
            if g:
                add("segment", points_of(g), raw=m.group(0))
    # ---- named polygons: their sides are required segments
    for m in re.finditer(rf"(?:המשולש|משולש|המרובע|מרובע|הריבוע|ריבוע|המלבן|מלבן|הטרפז|טרפז|הדלתון|דלתון|המקבילית|מקבילית|המעוין|מעוין)\s*((?:{P}){{3,4}}){E}", s):
        pts = points_of(m.group(1))
        for i in range(len(pts)):
            add("segment", [pts[i], pts[(i + 1) % len(pts)]], raw=m.group(0))
    for m in re.finditer(rf"{B}((?:{P}){{3,4}}){E}\s*(?:הוא|היא)\s*(?:משולש|מרובע|ריבוע|מלבן|טרפז|דלתון|מקבילית|מעוין)", s):
        pts = points_of(m.group(1))
        for i in range(len(pts)):
            add("segment", [pts[i], pts[(i + 1) % len(pts)]], raw=m.group(0))
    for m in re.finditer(rf"(?:הקטע|הקטעים|קטע|האלכסון|אלכסון)\s*((?:{P}){{2}}){E}", s):
        add("segment", points_of(m.group(1)), raw=m.group(0))
    # explicit LINEAR EXTENT: segment / ray / line (never inferred for tangents)
    for word, ext in (("(?:הקטע|קטע)", "SEGMENT"), ("(?:הקרן|קרן)", "RAY"), ("(?:הישר|ישר)", "LINE")):
        for m in re.finditer(rf"(?<![\u0590-\u05FF]){word}\s*((?:{P}){{2}}){E}", s):
            if not re.match(r"\s*(?:אחד|ה?מקביל)", s[m.end():m.end() + 8]):
                add("extent", points_of(m.group(1)), ext, raw=m.group(0))
    # ---- graph facts written in the text: options I-IV, coordinate labels, horizontal/vertical asymptote equations
    rom = ["I", "II", "III", "IV", "V", "VI"]
    for m in re.finditer(r"(?<![A-Za-z])(I{1,3}|IV|VI?)\s*[–—-]\s*(I{1,3}|IV|VI?)(?![A-Za-z])", s):
        a, b = rom.index(m.group(1)), rom.index(m.group(2))
        for r in rom[a:b + 1]:
            out.append(Fact(fact_type="option", entities=[r], source="question_text", required=required, raw_text=m.group(0)))
    for m in re.finditer(r"\(\s*(-?\d+(?:\.\d+)?|[a-z])\s*,\s*(-?\d*(?:\.\d+)?[a-z]?)\s*\)", s):
        add("label", [label_key(m.group(0))], raw=m.group(0))
    for m in re.finditer(r"(?<![A-Za-z])([xy])\s*=\s*(-?\d+(?:\.\d+)?)(?![\d.])", s):
        add("asymptote", ["horizontal" if m.group(1) == "y" else "vertical"], float(m.group(2)), raw=m.group(0))
    # ---- plural / coordinated dimensions: one object, one plural phrase, several values (none may be lost)
    for m in re.finditer(rf"(אורכי|מידות|ממדי|רדיוסי|קוטרי|גובהי)\s+([^.\d]{{0,50}}?)(?:הם|הן|:)?\s*((?:\d+(?:\.\d+)?\s*{UNIT}?\s*(?:,|ו-?|\s)\s*)+\d+(?:\.\d+)?\s*{UNIT})", s):
        vals = [float(v) for v in re.findall(r"\d+(?:\.\d+)?", m.group(3))]
        unit_m = re.search(UNIT, m.group(3))
        noun = m.group(1)
        if noun in ("מידות", "ממדי"):
            types = ["length", "width", "height"][:len(vals)] if len(vals) <= 3 else ["length"] * len(vals)
        else:
            base = {"אורכי": "length", "רדיוסי": "radius", "קוטרי": "diameter", "גובהי": "height"}[noun]
            types = [base] * len(vals)
        before = s[max(s.rfind(".", 0, m.start()), 0):m.end()]
        ent_kind = next((k for w, k in ENTITY_WORDS.items() if w in before), None)
        for v, t in zip(vals, types):
            add("dimension", [], {"dimension_type": t, "value": v, "unit": unit_m.group(1) if unit_m else "", "entity": ent_kind,
                                  "entity_kind": ent_kind, "entity_index": None, "plural_group": m.group(0)[:40]}, raw=m.group(0))
    # ---- explicitly mentioned points (only as required entities of a named figure)
    names = set()
    for m in re.finditer(rf"(?:הנקודה|הנקודות|נקודה|המשולש|משולש|המרובע|מרובע|הריבוע|ריבוע|המלבן|מלבן|הטרפז|טרפז|הדלתון|דלתון|המקבילית|מקבילית|התיבה|תיבה|הפירמידה|פירמידה|הקטע|קטע|הצלע|צלע|המקצוע|הישר|ישר|הקוטר|המיתר|האלכסון)\s*((?:{P})(?:(?:{SEP})(?:{P}))*|(?:{P})+){E}", s):
        names.update(points_of(m.group(1)))
    for f in out:
        names.update(e for e in f.entities if re.fullmatch(P, e))
    for n in sorted(names):
        add("point", [n])
    uniq, seen = [], set()
    for f in out:
        k = (f.key, str(f.value))
        if k not in seen:
            seen.add(k)
            uniq.append(f)
    return uniq


def constraints_from_facts(facts: list, circle_id: str | None, circle_center: str | None) -> list:
    """Explicit text facts -> solver constraints (source='text'). Facts that need a circle use the single circle."""
    from .schemas import GConstraint

    simple = {"rectangle": "rectangle", "square": "square", "equilateral": "equilateral", "equal_length": "equal_length", "parallel": "parallel", "perpendicular": "perpendicular",
              "parallel_to_x_axis": "parallel_to_x_axis", "parallel_to_y_axis": "parallel_to_y_axis", "right_angle": "right_angle",
              "midpoint": "midpoint", "point_on_segment": "on_segment", "point_on_line": "point_on_line", "collinear": "collinear",
              "point_order": "point_order", "intersection": "intersection", "on_x_axis": "on_x_axis", "on_y_axis": "on_y_axis"}
    out = []
    for f in facts:
        t, e = f.fact_type, list(f.entities)
        if t in simple:
            out.append(GConstraint(type=simple[t], points=e, source="text"))
        elif t == "angle_value":
            out.append(GConstraint(type="angle_value", points=e, value=f.value, source="text"))
        elif t in ("parallelogram", "rhombus") and len(e) == 4:
            out.append(GConstraint(type="parallel", points=[e[0], e[1], e[3], e[2]], source="text"))
            out.append(GConstraint(type="parallel", points=[e[1], e[2], e[0], e[3]], source="text"))
            if t == "rhombus":
                out.append(GConstraint(type="equal_length", points=[e[0], e[1], e[1], e[2]], source="text"))
        elif t == "ratio_on_segment":
            out.append(GConstraint(type="ratio_on_segment", points=e, value=f.value, source="text"))
        elif circle_id and t in ("on_circle", "diameter", "chord"):
            pts = e if t != "on_circle" else [e[0], circle_center or f"__c_{circle_id}"]
            out.append(GConstraint(type=t, points=pts, circle=circle_id, source="text"))
        elif circle_id and t == "concyclic":
            out += [GConstraint(type="on_circle", points=[p, circle_center or f"__c_{circle_id}"], circle=circle_id, source="text") for p in e]
        elif circle_id and t == "tangent" and len(e) == 2:
            out.append(GConstraint(type="tangent", points=e, circle=circle_id, source="text"))
    return out


REQUEST_VERBS = re.compile(r"(?<![\u0590-\u05FF])(?:חשב|חשבו|חשבי|מצא|מצאו|מצאי|הבע|הביעו|הביעי|הוכח|הוכיחו|הוכיחי|הראה|הראו|הראי|"
                           r"קבע|קבעו|קבעי|בדוק|בדקו|נמק|נמקו|כתוב|כתבו|סרטט|סרטטו|שרטט|שרטטו|האם|פתור|פתרו|הסבר|הסבירו)(?![\u0590-\u05FF])")


def split_by_role(sections: list[str]) -> tuple[str, str]:
    """(reconstruction_text, solution_text) at CLAUSE level: givens constrain the figure; goals and claims-to-prove never do."""
    recon, sol = [], []
    for sec in sections:
        for kind, c in clauses(sec):
            (recon if kind == "GIVEN" else sol).append(c)
    return " ".join(recon), " ".join(sol)


# ---------------------------------------------------------------- clause-level GIVEN / GOAL / CLAIM
CLAIM_RE = re.compile(r"(?<![\u0590-\u05FF])ו?(?:הוכיחו|הוכח|הוכיחי|הראו|הראה|הראי|הסבירו|הסבר|הסבירי|נמקו|נמק)\s*(?::|כי|ש-?|מדוע|למה)")
GOAL_RE = re.compile(r"(?<![\u0590-\u05FF])ו?(?:חשבו|חשב|חשבי|מצאו|מצא|מצאי|הביעו|הבע|הביעי|קבעו|קבע|קבעי|בדקו|בדוק|כתבו|כתוב|"
                     r"סרטטו|סרטט|שרטטו|שרטט|פתרו|פתור|השלימו|השלם|הוכיחו|הוכח|הראו|הראה|האם)(?![\u0590-\u05FF])")
CLAUSE_SPLIT = re.compile(r"(?<=[.?!;])\s+|\n|,\s*(?=ו?(?:חשבו|חשב|מצאו|מצא|הביעו|הבע|קבעו|קבע|הוכיחו|הוכח|הראו|הראה|הסבירו|הסבר|נמקו|כתבו|סרטטו|בדקו)(?![\u0590-\u05FF]))")


def clauses(text: str) -> list[tuple[str, str]]:
    """[(kind, clause)] with kind in GIVEN / GOAL / CLAIM. A command word makes only ITS clause a goal:
    'הנקודה E נמצאת על הקטע BO, ומצאו את BE' -> GIVEN(E on BO) + GOAL(find BE);
    'והוכיחו כי AB=CD' -> CLAIM (never a given)."""
    out = []
    for c in CLAUSE_SPLIT.split(_norm(text or "")):
        c = (c or "").strip(" ,")
        if not c:
            continue
        if re.match(r"\s*ו?נסמן|\s*ו?נסמנו|\s*יסומן", c):
            out.append(("DEFINITION", c))          # notation for the solution (areas, heights, angles) - not a drawn fact
        elif CLAIM_RE.search(c):
            out.append(("CLAIM", c))
        elif GOAL_RE.search(c):
            out.append(("GOAL", c))
        else:
            out.append(("GIVEN", c))
    return out


def given_text(text: str) -> str:
    return " ".join(c for k, c in clauses(text) if k == "GIVEN")
