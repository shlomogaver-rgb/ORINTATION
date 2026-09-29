"""Offline stand-in for google.genai.Client, used by the tests and the E2E run.

It returns realistic structured JSON (Hebrew text, LaTeX, figure specs) so that the real
prompt-building, parsing, validation and document code paths are exercised without network access.
"""
from __future__ import annotations

import json
import threading
from types import SimpleNamespace

_LAST = threading.local()      # the QuestionAI payload this worker thread returned last (reader B echoes that question)

Q1 = {
    "topic": "פונקציה ריבועית",
    "text": "נתונה הפונקציה $f(x)=x^{2}-4$.",
    "sections": [
        {"section_id": "א", "text": "מצא את נקודות החיתוך של גרף הפונקציה עם הצירים.", "points": 20},
        {"section_id": "ב", "text": "מצא את נקודת הקיצון של הפונקציה וקבע את סוגה.", "points": 15},
        {"section_id": "ג", "text": "שרטט סקיצה של גרף הפונקציה.", "points": 15},
    ],
    "figures": [
        {
            "description": "גרף הפרבולה $y=x^2-4$ במערכת צירים",
            "source_image_index": 1,
            "bbox": [520, 200, 940, 800],
            "figure_type": "function_graph",
            "rebuild_required": True,
            "rebuild_confidence": 0.9,
            "render_engine": "matplotlib",
            "geogebra_commands": ["f(x)=x^2-4"],
            "spec_json": json.dumps({
                "diagram_type": "graph", "confidence": 0.93,
                "labels": [{"text": "A", "confidence": 0.98}, {"text": "B", "confidence": 0.98}, {"text": "f(x)", "confidence": 0.95}],
                "observed": {"num_curves": 1, "x_intercepts": [-2, 2], "y_intercept": -4, "point_labels": ["A", "B"]},
                "graph": {"axes": {"x_min": -4, "x_max": 4, "y_min": -5, "y_max": 8, "x_step": 1, "y_step": 1},
                          "curves": [{"id": "f", "label": "f(x)", "expression": "x^2-4"}],
                          "points": [{"name": "A", "x": -2, "y": 0, "on_curve": "f"}, {"name": "B", "x": 2, "y": 0, "on_curve": "f"}]},
            }, ensure_ascii=False),
        }
    ],
    "solution_steps": [
        {"section_id": "א", "step_title": "חיתוך עם ציר x", "content": "נציב $y=0$: $$x^{2}-4=0 \\Rightarrow x=\\pm 2$$",
         "final_answer": ""},
        {"section_id": "א", "step_title": "חיתוך עם ציר y", "content": "נציב $x=0$ ונקבל $f(0)=-4$.",
         "final_answer": "$(-2,0)$, $(2,0)$, $(0,-4)$"},
        {"section_id": "ב", "step_title": "גזירה", "content": "$f'(x)=2x$, ולכן $f'(x)=0$ עבור $x=0$. מכיוון ש-$f''(x)=2>0$ זוהי נקודת מינימום.",
         "final_answer": "מינימום ב-$(0,-4)$"},
        {"section_id": "ג", "step_title": "סקיצה", "content": "פרבולה \"מחייכת\" העוברת בנקודות שנמצאו בסעיפים א ו-ב.",
         "final_answer": "ראו שרטוט"},
    ],
    "rubric_steps": [
        {"section_id": "א", "stage_desc": "חיתוך עם ציר x", "percentage": 24,
         "full_credit": "שתי הנקודות $(\\pm2,0)$", "partial_credit": "נקודה אחת נכונה", "zero_credit": "אין פתרון",
         "carried_over_error_policy": "לא רלוונטי", "common_errors": [{"error": "שוכחים את הפתרון השלילי", "severity": "בינונית", "deduction_percent": 50}]},
        {"section_id": "א", "stage_desc": "חיתוך עם ציר y", "percentage": 16,
         "full_credit": "$(0,-4)$", "partial_credit": "—", "zero_credit": "טעות בהצבה",
         "carried_over_error_policy": "—", "common_errors": []},
        {"section_id": "ב", "stage_desc": "מציאת נקודת קיצון וסוגה", "percentage": 30,
         "full_credit": "נקודה וסוג נכונים עם נימוק", "partial_credit": "נקודה ללא קביעת סוג", "zero_credit": "אין גזירה",
         "carried_over_error_policy": "טעות בנגזרת שנגררה — עד 50% מהניקוד", "common_errors": []},
        {"section_id": "ג", "stage_desc": "סקיצה", "percentage": 30,
         "full_credit": "סקיצה עם כל הנקודות", "partial_credit": "סקיצה חלקית", "zero_credit": "אין סקיצה",
         "carried_over_error_policy": "סקיצה עקבית עם נקודות שגויות מסעיפים קודמים — ניקוד מלא", "common_errors": []},
    ],
}

Q2 = {
    "topic": "משפט פיתגורס",
    "text": "במשולש ישר זווית $ABC$ ($\\angle B=90^\\circ$) נתון: $AB=5$, $BC=12$.",
    "sections": [
        {"section_id": "א", "text": "חשב את אורך היתר $AC$.", "points": 25},
        {"section_id": "ב", "text": "חשב את שטח המשולש.", "points": 25},
    ],
    "figures": [
        {
            "description": "משולש ישר זווית ABC",
            "source_image_index": 1,
            "bbox": [],
            "figure_type": "geometry",
            "rebuild_required": True,
            "rebuild_confidence": 0.85,
            "render_engine": "matplotlib",
            "geogebra_commands": [],
            "spec_json": json.dumps({
                "diagram_type": "geometry", "confidence": 0.9,
                "labels": [{"text": t, "confidence": 0.97} for t in ("A", "B", "C", "5", "12")],
                "observed": {"num_points": 3, "point_labels": ["A", "B", "C"], "num_segments": 3, "right_angle_marks": 1},
                "geometry": {"points": [{"id": "B", "x": 0, "y": 0}, {"id": "A", "x": 0.1, "y": 5}, {"id": "C", "x": 12, "y": 0.2}],
                             "segments": [{"a": "A", "b": "B"}, {"a": "B", "b": "C"}, {"a": "C", "b": "A"}],
                             "angle_marks": [{"vertex": "B", "a": "A", "b": "C", "kind": "right"}],
                             "length_labels": [{"a": "A", "b": "B", "text": "5"}, {"a": "B", "b": "C", "text": "12"}]},
            }, ensure_ascii=False),
        }
    ],
    "solution_steps": [
        {"section_id": "א", "step_title": "משפט פיתגורס", "content": "$$AC=\\sqrt{AB^{2}+BC^{2}}=\\sqrt{25+144}=\\sqrt{169}$$",
         "final_answer": "$AC=13$"},
        {"section_id": "ב", "step_title": "שטח", "content": "$$S=\\frac{AB\\cdot BC}{2}=\\frac{5\\cdot 12}{2}$$",
         "final_answer": "$S=30$"},
    ],
    "rubric_steps": [
        {"section_id": "א", "stage_desc": "שימוש במשפט פיתגורס וחישוב", "percentage": 50,
         "full_credit": "$AC=13$ עם דרך", "partial_credit": "נוסחה נכונה, טעות חישוב", "zero_credit": "אין שימוש במשפט",
         "carried_over_error_policy": "—", "common_errors": [{"error": "חיבור אורכים במקום ריבועים", "severity": "גבוהה", "deduction_percent": 100}]},
        {"section_id": "ב", "stage_desc": "חישוב שטח", "percentage": 50,
         "full_credit": "$S=30$", "partial_credit": "נוסחה נכונה", "zero_credit": "אין פתרון",
         "carried_over_error_policy": "—", "common_errors": []},
    ],
}

HEADER = {
    "translated_exam_name": "Mathematics Exam",
    "translated_grade": "Grade 10",
    "translated_level": "5 units",
    "translated_instructions": "• Duration: 90 minutes.\n• Show all work.",
    "labels": {
        "exam_form": "Exam", "solutions": "Full Solutions", "rubric": "Marking Rubric", "question": "Question",
        "section": "Part", "points": "points", "instructions": "Instructions", "final_answer": "Final answer",
        "full_credit": "Full credit", "partial_credit": "Partial credit", "zero_credit": "Zero credit",
        "carried_error": "Carried error", "common_errors": "Common errors", "teacher": "Teacher", "grade": "Grade",
        "level": "Level", "exam_date": "Date", "duration": "Duration", "minutes": "minutes", "section_stage": "Part / stage",
        "student_name": "Student name", "class_name": "Class", "page": "Page", "of": "of", "figure": "Figure", "total": "Total",
    },
}


class _Models:
    def __init__(self, owner: "FakeClient"):
        self.owner = owner

    def list(self):
        return [SimpleNamespace(name=f"models/{m}") for m in ("gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash")]

    def generate_content(self, model, contents, config):
        self.owner.calls.append((model, config.response_schema.__name__))
        schema = config.response_schema.__name__
        text = " ".join(getattr(p, "text", "") or "" for p in contents[0].parts)
        if schema == "QuestionAI":
            payload = Q1 if "Question number: 1" in text else Q2
            _LAST.q = payload
        elif schema == "VerificationAI":
            section_ids = ["א", "ב", "ג"] if "x^{2}-4" in text else ["א", "ב"]
            payload = {"items": [{"section_id": sid, "independent_final_answer": "ok", "proposed_final_answer": "ok",
                                  "agrees": True, "reasoning_agrees": True, "source_text_agrees": True,
                                  "comment": ""} for sid in section_ids], "source_reconstruction_agrees": True,
                       "reasoning_agrees": True, "overall_agrees": True, "notes": ""}
            if self.owner.disagree:
                payload["items"][0]["agrees"] = False
                payload["overall_agrees"] = False
        elif schema == "ExamHeaderAI":
            payload = HEADER
        elif schema == "AIDiagramSpec":            # PASS 2: typed spec of the figure in the ROI
            from diagram_engine.ai_schema import to_ai_dict
            from diagram_engine.pipeline import parse_raw
            src = Q1 if "x^{2}-4" in text else Q2
            payload = to_ai_dict(parse_raw(src["figures"][0]["spec_json"]))
        elif schema == "LineReadingsAI":          # reader B: one literal reading per line crop
            n = sum(1 for p in contents[0].parts if getattr(p, "inline_data", None) is not None)
            start = next((int(t.split()[-1].rstrip(":")) for t in
                          (getattr(p, "text", "") or "" for p in contents[0].parts) if t.startswith("Image index")), 0)
            src = getattr(_LAST, "q", Q1)
            lines = [l for t in [src["text"]] + [s_["text"] for s_ in src["sections"]] for l in t.split("\n") if l.strip()]
            if self.owner.misread:
                lines = [l.replace("x^{2}-4", "x^{2}-9") for l in lines]
            if n and len(lines) > n:
                lines = lines[:n - 1] + [" ".join(lines[n - 1:])]
            lines += [""] * (n - len(lines))
            payload = {"lines": [{"index": start + k, "text": lines[k] if start == 0 else "", "unreadable": False}
                                 for k in range(n)]}
        elif schema == "FigureLabelsAI":
            src = getattr(_LAST, "q", Q1)
            spec = json.loads(src["figures"][0]["spec_json"]) if src.get("figures") else {}
            payload = {"labels": [l["text"] for l in spec.get("labels", [])]}
        else:
            raise ValueError(schema)
        return SimpleNamespace(
            parsed=None, text=json.dumps(payload, ensure_ascii=False),
            candidates=[SimpleNamespace(finish_reason="STOP")], prompt_feedback=None,
        )


class FakeClient:
    def __init__(self, api_key: str = "", disagree: bool = False, misread: bool = False):
        self.calls: list = []
        self.disagree = disagree
        self.misread = misread          # reader B sees a different number than PASS 1 (a misread in one of the readings)
        self.models = _Models(self)


def install(disagree: bool = False, misread: bool = False) -> None:
    import exam_core

    exam_core.make_client = lambda api_key: FakeClient(api_key, disagree=disagree, misread=misread)
