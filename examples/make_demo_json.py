"""Hand-made transcription of two sample pages, in exactly the format the model returns.

Used to test/demonstrate the DOCX builder without an API key:
    python examples/make_demo_json.py
    python -m math2word <pdf> -p 3 --from-json examples/demo_new1_p3.json -o examples/demo_new1_p3.docx
"""
import json
from pathlib import Path


def T(v, bold=False, underline=False):
    return {"type": "text", "value": v, "bold": bold, "underline": underline}


def M(v):
    return {"type": "math", "value": v, "bold": False, "underline": False}


def P(label, level, *lines, align="start", space_before=False):
    return {"label": label, "level": level, "align": align, "space_before": space_before, "lines": list(lines)}


def B(kind, par=None, figure_id="", figure_side="none", paragraphs=(), rows=()):
    par = par or P("", 0)
    return {"kind": kind, **par, "figure_id": figure_id, "figure_side": figure_side,
            "paragraphs": list(paragraphs), "rows": list(rows)}


new1_p3 = {
    "page_type": "questions",
    "figures": [
        {"id": "f1", "bbox": [60, 95, 370, 250], "description": "גרף פרבולה f(x) החותכת את ציר x ב־(-5,0) ו־(5,0) ומינימום ב־(0,-3)"},
        {"id": "f2", "bbox": [80, 480, 345, 695], "description": "מרובע ABCD, הנקודה F על המשך CB"},
    ],
    "blocks": [
        B("figure_row", figure_id="f1", figure_side="left", paragraphs=[
            P("ג.", 1,
              [T("בסרטוט שלפניכם מתואר גרף הפונקציה "), M("f(x)"), T(" , ועליו כתובים")],
              [T("כל שיעורי נקודות החיתוך של גרף הפונקציה "), M("f(x)"), T(" עם ציר ה־"), M("x")],
              [T("ושיעורי נקודת המינימום שלה.")],
              [T("הפונקציה  מוגדרת לכל "), M("x"), T(" .")],
              [T("נתונות הפונקציות: "), M(r"g(x)=\left|f(x)+m\right|"), T(" , "), M(r"h(x)=\left|f(x)\right|+m"), T(" .")],
              [M("m"), T(" הוא פרמטר, "), M("0<m<2"), T(" .")]),
            P("(1)", 2,
              [T("הביעו באמצעות "), M("m"), T(" , אם יש צורך,")],
              [T("את שיעורי נקודת המקסימום של הפונקציה "), M("g(x)"), T(" .")]),
        ]),
        B("paragraph", P("(2)", 2, [T("הביעו באמצעות "), M("m"), T(" , אם יש צורך, את שיעורי נקודות הקיצון של הפונקציה "),
                                     M("h(x)"), T(" , וקבעו את סוגן.")])),
        B("paragraph", P("(3)", 2, [T("לפניכם שתי טענות, "), M(r"\mathrm{I}-\mathrm{II}"),
                                     T(" . קבעו בעבור כל טענה אם היא נכונה או אינה נכונה. נמקו את קביעותיכם.")])),
        B("paragraph", P("I.", 3, [T("הפונקציות "), M("g(x)"), T(" ו־"), M("h(x)"), T(" חיוביות לכל ערך של "), M("x"), T(" .")])),
        B("paragraph", P("II.", 3,
                         [T("לכל ערך של "), M("m"), T(" בתחום "), M("0<m<2"), T(" מתקיים שהישר "), M(r"y=m+\frac{1}{2}"),
                          T(" חותך כל אחת מן")],
                         [T("הפונקציות "), M("g(x)"), T(" ו־"), M("h(x)"), T(" בשלוש נקודות.")])),
        B("figure_row", figure_id="f2", figure_side="left", paragraphs=[
            P("ד.", 1,
              [T("המרובע "), M("ABCD"), T(" הוא בר חסימה במעגל, כך ש־"), M("AD"), T(" הוא קוטר במעגל.")],
              [T("הנקודה "), M("F"), T(" נמצאת על המשך הצלע "), M("CB"), T(" , כך ש־"), M(r"FB\perp FA"), T(" ,")],
              [T("כמתואר בסרטוט שלפניכם.")], space_before=True),
            P("(1)", 2, [T("הוכיחו: "), M(r"\triangle ACD\sim\triangle AFB"), T(" .")]),
            P("", 1, [T("נתון: "), M(r"\sphericalangle BDA=24^{\circ}"), T(" .")]),
            P("(2)", 2, [T("מצאו את היחס בין שטח המשולש "), M("ACD"), T(" ובין שטח המשולש "), M("AFB"), T(" .")]),
        ]),
    ],
}

q26_p10 = {
    "page_type": "questions",
    "figures": [{"id": "f1", "bbox": [128, 122, 392, 330],
                 "description": "קטע מסילה פרבולי מ־A על ציר y עד B, עם עמודי תמיכה"}],
    "blocks": [
        B("figure_row", figure_id="f1", figure_side="left", paragraphs=[
            P("4.", 0,
              [T("בפארק שעשועים התקינו רכבת הרים על קרקע מישורית.")],
              [T("אחד מן הקטעים של מסילת הרכבת הוא בצורת פרבולה.")],
              [T("קטע מסילה זה מתחיל בנקודה "), M("A"), T(" על ציר ה־"), M("y")],
              [T("ומסתיים בנקודה "), M("B"), T(" (ראו סרטוט).")],
              [T("קטע זה מתואר על ידי הפונקציה "), M("f(x)=-0.25x^{2}+3x+7"), T(" .")],
              [T("ציר ה־"), M("x"), T(" מתאר את המרחק האופקי (במטרים) מן הנקודה "), M("A"), T(" .")],
              [T("ציר ה־"), M("y"), T(" מתאר את גובה המסילה (במטרים) מעל הקרקע.")]),
            P("א.", 1, [T("מצאו את גובה נקודת ההתחלה של קטע המסילה")],
              [T("מעל הקרקע (הנקודה "), M("A"), T(").")]),
        ]),
        B("paragraph", P("ב.", 1, [T("(1)", bold=True), T("\tמצאו את הגובה המקסימלי של קטע מסילה זה.")])),
        B("paragraph", P("(2)", 2, [T("מצאו בעבור אילו ערכים של "), M("x"), T(" בקטע מסילה זה הרכבת נמצאת במגמת עלייה.")])),
        B("paragraph", P("", 0,
                         [T("קטע המסילה מחובר לכמה עמודי תמיכה אנכיים המוצבים על הקרקע.")],
                         [T("אחד מעמודי התמיכה מחובר לקטע המסילה בנקודה "), M("B"), T(" .")],
                         [T("נתון כי שיעור ה־"), M("x"), T(" של הנקודה "), M("B"), T(" הוא "), M("13"), T(" .")],
                         space_before=True)),
        B("paragraph", P("ג.", 1, [T("מצאו את הגובה של עמוד תמיכה זה.")])),
        B("paragraph", P("", 0,
                         [T("בקטע מסילה זה מותקנות כמה מצלמות אוטומטיות כדי לתעד את הנוסעים.")],
                         [T("המצלמות נמצאות בנקודות שבהן גובה קטע המסילה מעל הקרקע הוא "), M("12"), T(" מטרים.")],
                         space_before=True)),
        B("paragraph", P("ד.", 1, [T("מצאו את שיעורי ה־"), M("x"), T(" של הנקודות שבהן המצלמות נמצאות בקטע מסילה זה.")])),
    ],
}

here = Path(__file__).parent
for name, pages, page_json in [("demo_new1_p3", [3], [new1_p3]), ("demo_q26_p10", [10], [q26_p10])]:
    (here / f"{name}.json").write_text(json.dumps({"pages": pages, "page_json": page_json}, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    print("wrote", name)
