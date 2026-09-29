"""Core logic for the math exam generator (V5).

This module has no Streamlit UI code so that it can be unit-tested on its own.
Sections:
  1. Data models (Pydantic)            5. Safe math-expression parser
  2. Gemini service (retry/fallback)   6. Figure rendering (bidi-aware)
  3. Scoring + validation              7. Word (OOXML) generation, RTL-correct
  4. Image processing                  8. PDF conversion via LibreOffice
"""
from __future__ import annotations

import hashlib
import html.entities
import io
import json
import os
import random
import re
import shutil
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Callable

import numpy as np
from PIL import Image, ImageOps
from pydantic import BaseModel, Field, ValidationError

import docx
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Inches, Pt, RGBColor

import latex2mathml.converter
import mathml2omml

import scoring
import text_structure

import matplotlib

import diagram_engine
from diagram_engine import safe_math as _sm
from diagram_engine.schemas import DiagramRecord, DiagramSpec
from diagram_engine.ai_schema import AIDiagramSpec, to_spec as ai_to_spec
from diagram_engine import notation

matplotlib.use("Agg")

try:
    from bidi import get_display as _bidi_get_display  # python-bidi >= 0.5
except Exception:  # pragma: no cover
    try:
        from bidi.algorithm import get_display as _bidi_get_display
    except Exception:
        _bidi_get_display = None

try:
    import arabic_reshaper
except Exception:  # pragma: no cover
    arabic_reshaper = None


# ============================================================
# Configuration
# ============================================================
APP_TITLE = "מחולל מבחנים במתמטיקה"
APP_VERSION = "5.7.9"
DEFAULT_MODEL = "gemini-3.8-flash"
FALLBACK_MODELS = ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash"]
TARGET_SCORE = Decimal("100")
POINT_TOLERANCE = Decimal("0.02")
MAX_IMAGE_SIDE = 2600
BODY_FONT = "Arial"
RTL_LANGUAGES = {"עברית", "ערבית"}
BIDI_LANG = {"עברית": "he-IL", "ערבית": "ar-SA"}
UNREADABLE_MARK = "[דרוש אימות מורה]"
SUPPORTED_FIGURE_TYPES = [
    "source_crop", "function_graph", "geometry", "bar_chart", "line_chart", "pie_chart", "generic_diagram",
]
RTL_CHARS = re.compile(r"[\u0590-\u05FF\u0600-\u06FF\u0750-\u077F\uFB1D-\uFDFF\uFE70-\uFEFF]")
ARABIC_CHARS = re.compile(r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]")


# ============================================================
# 1. Data models
# ============================================================
# NOTE: Models sent to Gemini as response_schema must NOT contain free-form dict fields
# (they produce `additionalProperties`, which the Gemini Developer API rejects).
# Numeric ranges are NOT enforced here: out-of-range model output is clamped afterwards
# instead of failing the whole question.

class DocumentLabels(BaseModel):
    exam_form: str
    solutions: str
    rubric: str
    question: str
    section: str
    points: str
    instructions: str
    final_answer: str
    full_credit: str
    partial_credit: str
    zero_credit: str
    carried_error: str
    common_errors: str
    teacher: str
    grade: str
    level: str
    exam_date: str
    duration: str
    minutes: str
    section_stage: str
    student_name: str
    class_name: str
    page: str
    of: str
    figure: str
    total: str


HEBREW_LABELS = DocumentLabels(
    exam_form="טופס בחינה", solutions="פתרון מלא", rubric="מחוון בדיקה", question="שאלה", section="סעיף",
    points="נקודות", instructions="הוראות לנבחן", final_answer="תשובה סופית", full_credit="ניקוד מלא",
    partial_credit="ניקוד חלקי", zero_credit="אפס נקודות", carried_error="טעות נגררת",
    common_errors="טעויות נפוצות", teacher="מורה", grade="שכבה", level="רמה", exam_date="תאריך",
    duration="משך הבחינה", minutes="דקות", section_stage="סעיף / שלב", student_name="שם התלמיד/ה",
    class_name="כיתה", page="עמוד", of="מתוך", figure="איור", total='סה"כ',
)

ENGLISH_LABELS = DocumentLabels(
    exam_form="Exam", solutions="Full Solutions", rubric="Marking Rubric", question="Question", section="Part",
    points="points", instructions="Instructions", final_answer="Final answer", full_credit="Full credit",
    partial_credit="Partial credit", zero_credit="Zero credit", carried_error="Carried-forward error",
    common_errors="Common errors", teacher="Teacher", grade="Grade", level="Level", exam_date="Date",
    duration="Duration", minutes="minutes", section_stage="Part / stage", student_name="Student name",
    class_name="Class", page="Page", of="of", figure="Figure", total="Total",
)


class CommonError(BaseModel):
    error: str
    severity: str = ""
    deduction_percent: float = 0.0


class RubricStep(BaseModel):
    section_id: str = ""
    stage_desc: str
    percentage: float
    full_credit: str = ""
    partial_credit: str = ""
    zero_credit: str = ""
    carried_over_error_policy: str = ""
    common_errors: list[CommonError] = Field(default_factory=list)


class SolutionStep(BaseModel):
    section_id: str = ""
    step_title: str
    content: str
    final_answer: str = ""


class QuestionSection(BaseModel):
    section_id: str
    text: str
    points: float                        # points IF ANSWERED (see scoring.py)
    selection_group: str = Field(default="", description="id of the 'answer K of N' group this subpart belongs to; empty = mandatory")


class SelectionGroup(BaseModel):
    group_id: str
    choose_k: int


class FigureRef(BaseModel):
    section_id: str = Field(default="", description="the subpart (א, ב, ...) this figure belongs to; empty = the question stem")
    description: str
    source_image_index: int = 1
    # Normalized [ymin, xmin, ymax, xmax] in 0..1000; empty list = whole image.
    bbox: list[int] = Field(default_factory=list)
    figure_type: str = "source_crop"
    rebuild_required: bool = False
    rebuild_confidence: float = 0.0
    render_engine: str = "source_crop"
    geogebra_commands: list[str] = Field(default_factory=list)
    spec_json: str = ""
    figure_id: str = ""


class QuestionAI(BaseModel):
    """What Gemini returns for ONE question."""
    topic: str
    text: str
    required_sections: int = Field(default=0, description="legacy shorthand: answer K of ALL subparts -> K; prefer selection_groups")
    selection_groups: list[SelectionGroup] = Field(default_factory=list,
                                                   description="'answer K of these N subparts' groups; sections refer to them by selection_group")
    sections: list[QuestionSection] = Field(default_factory=list)
    figures: list[FigureRef] = Field(default_factory=list)
    solution_steps: list[SolutionStep] = Field(default_factory=list)
    rubric_steps: list[RubricStep] = Field(default_factory=list)


DIAGRAM_SYSTEM_PROMPT = """You are PASS 2 of an exam digitisation pipeline. You receive ONE high-resolution crop of ONE
figure (and at most the question text for symbol names). You never draw; you describe the figure as structured data.
SEMANTICS (optional, typed - fill ONLY what the figure/question really contains; the engines verify or build from it):
- semantics.complex_plane: numbers [{label, value "a+bi" | r, theta_deg}] or roots_of {n, w}; polygon true if the points form one.
- semantics.conics: [{equation "x^2/25+y^2/9=1", claimed_kind}] for circles/ellipses/parabolas/hyperbolas.
- semantics.vectors: points [{id,x,y,z}], vectors [{name, from_point, to_point}], claims [{kind: parallel|perpendicular|ratio|combination, refs, value, coeffs}].
- semantics.space3d: points, lines [{id, through [A,B]}], planes [{id, through [A,B,C] | equation}], claims (on_plane, angle_*, distance_point_plane).
- semantics.function_relations: [{child, relation DERIVATIVE_OF|NEGATIVE_OF|VERTICAL_SCALE_OF|TRANSLATION_OF|..., parent, k, dx, dy}] between curve ids.
- semantics.formulas: [{id, latex}] for formulas printed INSIDE the figure.
Never invent semantics that are not shown or stated.
""" + """FIGURES (you EXTRACT structure; you never draw. A deterministic engine renders, validates and compares.)
- For every essential drawing/graph/chart add a FigureRef. source_image_index is 1-based within this question. bbox is [ymin,xmin,ymax,xmax] in 0..1000 tightly around the figure; [] for the whole image.
- Return the typed object (omit the blocks that do not apply). Shape reference:
  {"diagram_type": "graph|geometry|mixed_graph_geometry|chart|table|spatial|generic|unknown", "confidence": 0..1,
   "labels": [{"text":"A","bbox":[ymin,xmin,ymax,xmax],"confidence":0..1,"alternatives":["4"]}],
   "observed": {"point_labels":[...], "num_points":n, "num_segments":n, "num_circles":n, "num_curves":n,
                "right_angle_marks":n, "equal_mark_groups":n, "parallel_mark_groups":n, "angle_values":["40"],
                "x_intercepts":[...], "y_intercept":v, "open_endpoints":[[x,y]], "closed_endpoints":[[x,y]], "num_bars":n},
   "graph": {"axes":{"x_min":..,"x_max":..,"y_min":..,"y_max":..,"x_step":1,"y_step":1,"x_label":"x","y_label":"y","show_grid":true},
             "curves":[{"id":"f","label":"f(x)","expression":"x^2-4",
                        "pieces":[{"expression":"x+1","x_from":-2,"x_to":1,"left_closed":true,"right_closed":false}]}],
             "points":[{"name":"A","x":2,"y":0,"on_curve":"f","style":"closed|open"}],
             "asymptotes":[{"kind":"vertical|horizontal","value":3}]},
   "geometry": {"points":[{"id":"A","x":0,"y":0}], "segments":[{"a":"A","b":"B","style":"solid|dashed"}], "lines":[], "rays":[],
                "circles":[{"center":"O","through":"A"}], "arcs":[{"center":"O","start":"A","end":"B"}],
                "angle_marks":[{"vertex":"B","a":"A","b":"C","kind":"arc|right","value":"40"}],
                "equal_marks":[{"segments":[["A","C"],["B","C"]],"ticks":1}], "parallel_marks":[{"segments":[["A","B"],["C","D"]],"arrows":1}],
                "length_labels":[{"a":"A","b":"B","text":"5"}], "constraints":[]},
   "chart": {"kind":"bar|histogram|pie|line|frequency_table|two_way_table","categories":[],"values":[],"bins":[],
             "row_labels":[],"col_labels":[],"table":[[...]],"title":"","x_label":"","y_label":"","show_percentages":false},
   "generic": {"width":100,"height":60,"shapes":[{"kind":"rect|ellipse","x":..,"y":..,"w":..,"h":..,"text":""}],"arrows":[{"x1":..,"y1":..,"x2":..,"y2":..,"label":""}],
               "labels":[{"text":"A","x":..,"y":..}],"dimensions":[{"x1":..,"y1":..,"x2":..,"y2":..,"text":"8 מטרים","attach":["A","G"]}]},
   "subtype": "formula_graph|qualitative_graph|multi_choice_graphs|triangle_geometry|circle_geometry|polygon_geometry|analytic_geometry|coordinate_circle|graph_with_geometry|scatter_plot|histogram|bar_chart|pie_chart|normal_distribution_schematic|numeric_table|frequency_table|two_way_table|voxel_structure|cuboid|cylinder|cylinder_in_box|vector_box",
   "graph_topology" (graph WITHOUT a formula - never invent an equation): {"function_label":"f(x)","axes":{...,"show_numbers":false},
             "landmarks":[{"x":6,"y":1,"label":"(6 , a)","kind":"max|min|x_intercept|y_intercept|marked","style":"closed|open|none"}],
             "asymptotes":[...],"branches":[{"landmarks":[0,1,2],"left":{"toward":"asymptote|plus_inf|minus_inf|stop","value":0},"right":{...}}]},
   "multi_graph" (options I, II, III, IV - keep them SEPARATE): {"options":[{"label":"I","topology":{...}} or {"label":"I","formula":{...graph...}}]},
   "mixed" (curve + construction in one coordinate system): {"graph":{...},"geometry":{...,"constraints":[{"type":"on_curve","points":["A"],"curve":"f"}]}},
   "scatter": {"axes":{...},"points":[[x,y],...]},  "normal": {"percentages":["0.5%",...],"boxed_regions":[0,1],"answer_boxes":11},
   "table": {"header_rows":1,"header_columns":1,"rows":[[{"text":"..."}]]},
   "spatial": {"voxel":{"plate":[4,4],"columns":[{"x":0,"y":0,"height":2}],"ambiguous":false},
               "solids":[{"id":"box","kind":"cuboid|cylinder|polyhedron","dims":{"width":..,"depth":..,"height":..,"radius":..},
                          "vertices":{"A":[x,y,z]},"edges":[["A","B"]],"hidden_edges":[["A","B"]],"face_text":""}],
               "dimensions":[{"solid":"box","measure":"width|depth|height|radius|diameter","text":"24 ס\"מ"}],
               "vectors":[{"from":"A","to":"B","label":"u"}],"points_on_edges":[{"id":"F","a":"B","b":"C","ratio":0.5}],
               "relations":[{"type":"inside|touching_base|touching_side|separate","a":"cyl","b":"box"}],
               "construction_segments":[{"from":"A'","to":"C'"},{"from":"F","to":"E"}],"construction_lines":[],"construction_rays":[],
               "annotations":[{"text":"...","at":"E"}]},
   "unsupported_features": ["anything in the figure you could NOT encode above - the original image will then be used"]}
- Dimensions: object + dimension_type (radius|diameter|height|width|depth|length|side|distance) + value + unit. Never turn a radius
  into a diameter; if the source line goes from the centre to the rim it is a radius.
- Do NOT drop any drawn element: if something cannot be expressed in this JSON, list it in "unsupported_features".
- Geometry relations you may report as constraints ONLY when they are written in the question or marked by an explicit symbol:
  equal_length, parallel, perpendicular, right_angle, midpoint, point_order ["B","C","D"], point_on_circle, diameter, tangent,
  equilateral, isosceles, ... Incidence you SEE (a point on a line/circle, the order of points on a line) may be reported with
  source "image". A circle may be given by "through_points" when its centre is not marked.
- Cube structures: if some columns are hidden and their height cannot be seen, set voxel.ambiguous=true (never guess hidden cubes).
- Radius vs diameter: report exactly what the dimension line measures in the source.
- STRICT RULES:
  * Report ONLY what is visible. Never add points, segments, marks, labels, values or equations that are not in the source.
  * "observed" = counts/facts of the SOURCE image exactly as seen; it is used to check the reconstruction.
  * Every label: its confidence; if a character could be another one (6/8, B/8, l/1) set confidence < 0.8 and list alternatives.
  * Graph expression: calculator syntax in x (+ - * / ^ ( ) sqrt cbrt abs ln log exp sin cos tan pi e), NO LaTeX. Give an
    expression only if it is stated in the question or unambiguous; otherwise leave curves empty and set confidence low.
  * Geometry coordinates: approximate positions of the drawing in any units, y pointing UP. Drawings are often NOT to scale:
    never infer equal lengths/parallel/right angles from appearance; report them only as explicit marks.
  * Chart values: use the numbers written in the source/question; do not estimate from bar heights unless no numbers exist
    (then confidence <= 0.7). Pie: show_percentages=true only if percentages are printed in the source.
  * If unsure what the figure is, use diagram_type "unknown" - the original image will be used.
- figure_type (legacy) may be source_crop; rebuild_required/rebuild_confidence are ignored by the engine.
"""


class ExamHeaderAI(BaseModel):
    translated_exam_name: str
    translated_grade: str
    translated_level: str
    translated_instructions: str
    labels: DocumentLabels


class VerificationItem(BaseModel):
    section_id: str = ""
    independent_final_answer: str
    proposed_final_answer: str = ""
    agrees: bool
    reasoning_agrees: bool
    source_text_agrees: bool
    comment: str = ""


class VerificationAI(BaseModel):
    items: list[VerificationItem] = Field(default_factory=list)
    source_reconstruction_agrees: bool
    reasoning_agrees: bool
    overall_agrees: bool
    notes: str = ""


class QuestionAnalysis(QuestionAI):
    question_number: int
    points: float
    analysis_input_hashes: list[str] = Field(default_factory=list)   # digests of the EDITED images sent to the AI
    verification: VerificationAI | None = None
    verification_error: str = ""
    teacher_verified: bool = False
    analysis_error: str = ""
    error_detail: str = ""
    # figure_id -> diagram-engine record (spec, validation, comparison, decision, teacher review, audit)
    diagrams: dict[str, DiagramRecord] = Field(default_factory=dict)
    # PASS 2 typed diagram specs (native structured output; no JSON string parsing) and pass metadata
    diagram_specs: dict[str, DiagramSpec] = Field(default_factory=dict)
    formula_checks: list[dict] = Field(default_factory=list)       # ExpressionAST status of every formula
    model_evidence: list[dict] = Field(default_factory=list)       # raw PASS 1 / PASS 2 responses + model + prompt version
    formula_fingerprint: str = ""                                  # the math content formula_checks were computed for
    text_structure_source: dict = Field(default_factory=dict)      # independent structure evidence (PDF text layer / OCR)
    teacher_verified_fp: str = ""                                  # the math content the teacher confirmed
    formula_uncertain: list[str] = Field(default_factory=list)     # independent-evidence disagreements (teacher must confirm)
    diagram_pass: dict[str, dict] = Field(default_factory=dict)


class ExamAnalysis(BaseModel):
    translated_exam_name: str
    translated_grade: str
    translated_level: str
    translated_instructions: str
    labels: DocumentLabels
    questions: list[QuestionAnalysis]
    model_used: str = ""


def empty_question(number: int, points: float, error: str = "") -> QuestionAnalysis:
    return QuestionAnalysis(question_number=number, points=points, topic="", text="", analysis_error=error)


# ============================================================
# 2. Gemini service
# ============================================================
QUESTION_SYSTEM_PROMPT = r"""
You are a senior mathematics assessment editor for the Israeli school system.
You receive photos of ONE exam question. Reconstruct it faithfully and produce a full solution and a marking rubric.

ACCURACY RULES
- Never invent unreadable information. Write exactly [דרוש אימות מורה] wherever a symbol, number, label or word cannot be read reliably.
- Preserve mathematical meaning, numbering, given data, restrictions and logical dependencies of the source.
- 'text' is the stem only. Put lettered/numbered sub-parts in 'sections' (section_id like א, ב, ג or a, b, c). Do not duplicate them in the stem.
- Scoring: every section's "points" is its value IF ANSWERED. When all sections are mandatory, their sum equals the
  question's total. When the question says "answer K of these N subparts", create a selection_group (choose_k=K), set
  selection_group on those N sections and give each of them total/K points (so the N values may sum to MORE than the
  total, and their rubric percentages may sum to more than 100) - that is correct, not an error.
- Put every mathematical expression in LaTeX: $...$ inline, $$...$$ for display math. Do not use $ for anything else.
- Write question text, sections, figure descriptions, solutions and rubric in the requested target language, at a professional academic level.
- solution_steps: explain reasoning and calculations fully. Set section_id on every step. Put the final answer of each section in final_answer of its last step.
- rubric_steps: set section_id on each stage; the stages of one section sum to (section points / question points * 100).
  With no choice all stages sum to 100; with "answer K of N" groups they may sum to more than 100 (each optional path is complete).
- TEXT FIDELITY: copy punctuation exactly (every comma, period, colon, parenthesis); never merge two sentences. Put a blank line
  between source paragraphs, start every subsection "(1)", "(2)" on its own line, put displayed formulas on their own line as
  $$...$$, and KEEP EVERY SOURCE LINE BREAK as a single newline (the new exam reproduces the source line layout).
- Each rubric stage: full/partial/zero-credit criteria, carried-forward-error policy (credit later correct reasoning based on an earlier error unless the task became trivial), common errors with severity and deduction percent.

FIGURES (PASS 1 - locate only; the diagram structure is extracted in a SEPARATE high-resolution pass)
- For every essential drawing/graph/chart/table-as-image add a FigureRef: description, source_image_index (1-based within
  this question) and bbox [ymin,xmin,ymax,xmax] in 0..1000 tightly around the figure ([] = whole image).
- Do NOT describe the figure's objects, labels or values and leave spec_json EMPTY. Write every fact that the TEXT states
  (points, relations, lengths, formulas) in the question text / sections exactly as printed.
- geogebra_commands: optional construction commands (teacher reference only).
""".strip()

HEADER_SYSTEM_PROMPT = """
You translate exam header metadata for a mathematics exam. Translate the exam title, grade, level and the general
instructions into the requested target language, and provide document labels in that language.
Do not translate proper names (school name, teacher name).
""".strip()

VERIFY_SYSTEM_PROMPT = r"""
You are an independent mathematics examiner checking another teacher's answer key.
1) First compare the reconstructed stem, every section, all numbers, symbols, domains/restrictions and figure-dependent data with the original photos. source_reconstruction_agrees=false if anything material is missing, altered or unreadable.
2) Using the original photos, solve every section yourself from scratch before judging the proposed solution.
3) Check the proposed reasoning step-by-step, not only its final answer. reasoning_agrees=false if a step is invalid, unjustified, circular, uses a false assumption or loses/extraneously adds solutions, even when the final answer happens to match.
4) Then compare the final answer of EVERY section with your independent final answer. Treat mathematically equivalent forms as agreeing (e.g. 0.5 and 1/2, x=2 or x=-3 and x∈{-3,2}).
5) Return exactly one VerificationItem for every section_id in the question. If the question has no explicit sections, return exactly one item with section_id="".
6) For each item set agrees=false whenever the final answers differ or the proposed answer is missing; set source_text_agrees and reasoning_agrees independently.
7) overall_agrees may be true only if source reconstruction, reasoning and every final answer all agree.
Use LaTeX with $...$ for math. Write comments in the requested target language, briefly.
""".strip()


class GeminiError(Exception):
    pass


GEMINI_HTTP_TIMEOUT_MS = 180_000   # a stuck request must never freeze the analysis (retries/fallback handle the rest)


def make_client(api_key: str):  # patched in tests
    from google import genai

    try:
        from google.genai import types

        return genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=GEMINI_HTTP_TIMEOUT_MS))
    except (ImportError, AttributeError, TypeError):  # older SDKs without HttpOptions
        return genai.Client(api_key=api_key)


def _error_code(exc: Exception) -> int | None:
    for attr in ("code", "status_code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    match = re.match(r"\s*(\d{3})\b", str(exc))
    return int(match.group(1)) if match else None


def _is_not_found(exc: Exception) -> bool:
    return _error_code(exc) == 404 or "NOT_FOUND" in str(exc)


def _is_overloaded(exc: Exception) -> bool:
    text = str(exc)
    return _error_code(exc) in (500, 502, 503, 504) or any(k in text for k in ("UNAVAILABLE", "overloaded", "INTERNAL"))


def _is_retryable(exc: Exception) -> bool:
    code = _error_code(exc)
    text = str(exc)
    return code in (408, 429, 500, 502, 503, 504) or any(
        k in text for k in ("RESOURCE_EXHAUSTED", "UNAVAILABLE", "DEADLINE_EXCEEDED", "INTERNAL", "timed out")
    )


def _strip_json_fences(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text


def parse_quota_error(exc: Exception) -> dict[str, Any]:
    """Extract Google quota details from a 429 error (works on the SDK exception text / details)."""
    text = str(exc) + " " + str(getattr(exc, "details", "") or "")
    info: dict[str, Any] = {"per_day": False, "limit": None, "retry_after": None, "free_tier": "free_tier" in text.lower() or "FreeTier" in text}
    quota_ids = re.findall(r"quotaId'?\"?\s*:\s*'?\"?([A-Za-z-]+)", text)
    info["per_day"] = any("PerDay" in q for q in quota_ids)
    m = re.search(r"quotaValue'?\"?\s*:\s*'?\"?(\d+)", text) or re.search(r"limit:\s*(\d+)", text)
    if m:
        info["limit"] = int(m.group(1))
    m = re.search(r"retryDelay'?\"?\s*:\s*'?\"?([\d.]+)s", text) or re.search(r"retry in ([\d.]+)\s*s", text)
    if m:
        info["retry_after"] = float(m.group(1))
    return info


def friendly_error(exc: Exception | str) -> str:
    """Short Hebrew explanation of a Gemini failure (the raw text stays available for the technical details)."""
    text = str(exc)
    code = _error_code(exc) if isinstance(exc, Exception) else None
    if code is None:
        m = re.search(r"\b(4\d\d|5\d\d)\b", text)
        code = int(m.group(1)) if m else None
    if code == 429 or "RESOURCE_EXHAUSTED" in text:
        info = parse_quota_error(exc if isinstance(exc, Exception) else Exception(text))
        if info["per_day"]:
            return ("המכסה היומית של מפתח ה-Gemini נוצלה עבור כל המודלים הזמינים. אפשר לנסות שוב מחר, "
                    "להשתמש במפתח אחר, או להפעיל חיוב (Billing) בפרויקט ב-Google AI Studio.")
        tier = " (השכבה החינמית)" if info["free_tier"] else ""
        limit = f" — עד {info['limit']} בקשות בדקה" if info["limit"] else ""
        return (f"חריגה ממכסת הבקשות של Gemini{tier}{limit}. המערכת מאטה אוטומטית את הקצב; "
                "אם השגיאה חוזרת, המתינו דקה ולחצו 'נסה שוב רק את השאלות שנכשלו'.")
    if code in (401, 403) or "API_KEY_INVALID" in text or "API key not valid" in text or "PERMISSION_DENIED" in text:
        return "מפתח ה-API של Gemini אינו תקין או שאין לו הרשאה. בדקו את המפתח ב-Google AI Studio."
    if code == 404 or "NOT_FOUND" in text:
        return "המודל שהוגדר אינו זמין למפתח זה, ולא נמצא מודל חלופי."
    if code == 400 and ("location" in text.lower() or "FAILED_PRECONDITION" in text):
        return "Gemini API אינו זמין באזור או בפרויקט הזה (FAILED_PRECONDITION)."
    if code in (500, 502, 503, 504) or "UNAVAILABLE" in text:
        return ("שרתי Gemini עמוסים כרגע (שגיאת שרת של Google, לא תקלה במפתח או במכסה). המערכת ניסתה גם מודלים חלופיים. "
                "נסו שוב בעוד כמה דקות, או הזינו בשדה 'מודל Gemini' את gemini-3.6-flash ולחצו 'נסה שוב רק את השאלות שנכשלו'.")
    if "MAX_TOKENS" in text:
        return "התשובה של Gemini ארוכה מדי ונקטעה. נסו לפצל את השאלה לשתי תמונות/שאלות."
    return "קריאת Gemini נכשלה. פרטים טכניים מופיעים למטה."


PROMPT_VERSION = "prompts/5.7.4"


class GeminiService:
    """Gemini wrapper: structured output, retries, model fallback and an adaptive rate limiter.

    The limiter starts unlimited (paid keys stay fast). On the first per-minute 429 it learns the quota from the error
    (e.g. 5 requests/minute on the free tier) and the requested retry delay, and paces every thread accordingly.
    """

    WINDOW = 60.0

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, client: Any = None, max_attempts: int = 4,
                 rpm: int | None = None, sleep: Callable[[float], None] | None = None, max_total_time: float = 900.0):
        self.client = client or make_client(api_key)
        self.model = model or DEFAULT_MODEL
        self.max_attempts = max_attempts
        self.max_total_time = max_total_time        # no operation may retry forever
        self.raw_log: list[dict] = []               # raw responses (model evidence), consumed per question
        self.rpm = rpm
        self.status = ""
        self._sleep = sleep or time.sleep
        self._lock = threading.Lock()
        self._rate_lock = threading.Lock()
        self._calls: list[float] = []
        self._not_before = 0.0
        self._models_tried: set[str] = set()
        self._server_errors: dict[str, int] = {}
        self.notes: list[str] = []
        self.rate_limit_events = 0

    # ---------------- rate limiting
    def _acquire(self) -> None:
        while True:
            with self._rate_lock:
                now = time.monotonic()
                wait = max(0.0, self._not_before - now)
                if not wait and self.rpm:
                    self._calls = [t for t in self._calls if now - t < self.WINDOW]
                    if len(self._calls) >= self.rpm:
                        wait = self.WINDOW - (now - self._calls[0]) + 0.5
                if not wait:
                    self._calls.append(now)
                    self.status = ""
                    return
            self.status = f"ממתין למכסת Gemini ({int(wait) + 1} שניות)…"
            self._sleep(min(wait, 2.0))

    def _on_rate_limit(self, exc: Exception, failed_model: str | None = None) -> None:
        info = parse_quota_error(exc)
        with self._rate_lock:
            self.rate_limit_events += 1
            if info["limit"]:
                self.rpm = min(self.rpm or info["limit"], info["limit"])
            elif not self.rpm:
                self.rpm = 5
            delay = info["retry_after"] if info["retry_after"] is not None else 10.0
            # A late 429 from a model that another worker already abandoned must not pause the new model.
            if failed_model is None or failed_model == self.model:
                self._not_before = max(self._not_before, time.monotonic() + delay + 1.0)

    def _next_model(self, failed_model: str | None = None) -> str | None:
        with self._lock:
            failed_model = failed_model or self.model
            self._models_tried.add(failed_model)
            candidates = [m for m in FALLBACK_MODELS if m not in self._models_tried]
            try:
                available = {m.name.split("/")[-1] for m in self.client.models.list()}
                candidates = [m for m in candidates if m in available] or sorted(
                    (m for m in available if "flash" in m and not any(t in m for t in ("lite", "image", "tts", "live", "transcribe", "omni"))
                     and m not in self._models_tried),
                    reverse=True,
                )
            except Exception:
                pass
            if not candidates:
                return None
            self.model = candidates[0]
            with self._rate_lock:  # quotas are per model: start the new model without the old pause
                self._calls, self._not_before = [], 0.0
            return self.model

    # ---------------- main call
    def generate(
        self,
        parts: list,
        schema: type[BaseModel],
        system: str,
        max_output_tokens: int = 32768,
        thinking_level: str | None = None,
    ) -> BaseModel:
        from google.genai import types

        last_exc: Exception | None = None
        attempt = 0
        rate_waits = 0
        started = time.monotonic()
        while attempt < self.max_attempts:
            if time.monotonic() - started > self.max_total_time:
                last_exc = GeminiError("חריגה ממגבלת הזמן הכוללת של הבקשה.")
                break
            attempt += 1
            model = self.model
            try:
                self._acquire()
                config_kwargs: dict[str, Any] = dict(
                    system_instruction=system,
                    response_mime_type="application/json",
                    response_schema=schema,
                    max_output_tokens=max_output_tokens,
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                )
                if hasattr(types, "MediaResolution"):
                    config_kwargs["media_resolution"] = types.MediaResolution.MEDIA_RESOLUTION_HIGH
                if thinking_level and hasattr(types, "ThinkingConfig"):
                    config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_level=thinking_level)
                response = self.client.models.generate_content(
                    model=model,
                    contents=[types.Content(role="user", parts=parts)],
                    config=types.GenerateContentConfig(**config_kwargs),
                )
                candidates = getattr(response, "candidates", None) or []
                finish = str(getattr(candidates[0], "finish_reason", "") or "") if candidates else ""
                if "MAX_TOKENS" in finish:
                    raise GeminiError("התשובה של Gemini נקטעה (MAX_TOKENS).")
                if not candidates:
                    feedback = getattr(response, "prompt_feedback", None)
                    raise GeminiError(f"Gemini לא החזיר תשובה ({feedback}).")
                # RAW model evidence (forensics): the exact response text + model id, kept per schema
                try:
                    raw_text = response.text or ""
                except Exception:
                    raw_text = ""
                self.raw_log.append({"schema": schema.__name__, "model": model, "prompt_version": PROMPT_VERSION,
                                     "raw_text": raw_text[:200000]})
                parsed = getattr(response, "parsed", None)
                if isinstance(parsed, schema):
                    return parsed
                if parsed is not None:
                    return schema.model_validate(parsed)
                return schema.model_validate_json(_strip_json_fences(response.text or ""))
            except GeminiError as exc:
                last_exc = exc
                if "MAX_TOKENS" in str(exc) and max_output_tokens < 65536:
                    max_output_tokens = 65536
                    continue
                if attempt >= self.max_attempts:
                    break
            except (ValidationError, json.JSONDecodeError, ValueError) as exc:
                # ValueError also covers SDK-side schema/config problems; retry is harmless.
                last_exc = exc
                if "additionalProperties" in str(exc):
                    break
            except Exception as exc:  # network / API errors
                last_exc = exc
                if _error_code(exc) == 429 or "RESOURCE_EXHAUSTED" in str(exc):
                    info = parse_quota_error(exc)
                    if info["per_day"]:
                        # Daily quota of this model is gone; other models have their own quota.
                        if self._next_model(model):
                            attempt -= 1
                            continue
                        break
                    self._on_rate_limit(exc, model)
                    rate_waits += 1
                    if rate_waits <= 12:
                        attempt -= 1  # waiting for quota is not a failed attempt
                        continue
                    break
                if _is_not_found(exc):
                    if self._next_model(model):
                        attempt -= 1  # a model switch does not consume an attempt
                        continue
                    break
                if not _is_retryable(exc):
                    break
                if _is_overloaded(exc):
                    # 500/503 "overloaded" is per model (typical right after a model launch):
                    # after 2 failures on the same model, move to the next Flash model instead of giving up.
                    self._server_errors[model] = self._server_errors.get(model, 0) + 1
                    if self._server_errors[model] >= 2 and self.model == model and self._next_model(model):
                        self.notes.append(f"המודל {model} היה עמוס — הפענוח עבר אוטומטית ל-{self.model}.")
                        attempt -= 1
                        continue
                self._sleep(min(30.0, 3 * 2 ** attempt + random.random()))
        raise GeminiError(f"קריאת Gemini נכשלה (מודל {self.model}): {last_exc}")


def _meta_for_prompt(meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "school_name": meta.get("school_name", ""),
        "exam_name": meta.get("exam_name", ""),
        "grade": meta.get("grade", ""),
        "level": meta.get("level", ""),
        "language": meta.get("language", "עברית"),
    }


def _image_parts(question: dict[str, Any]) -> list:
    from google.genai import types

    parts = []
    for idx, image_bytes in enumerate(question.get("images", []), 1):
        parts.append(types.Part.from_text(text=f"Source image {idx}:"))
        parts.append(types.Part.from_bytes(data=image_bytes, mime_type="image/png"))
    return parts


def analyze_question(service: GeminiService, meta: dict[str, Any], question: dict[str, Any]) -> QuestionAnalysis:
    from google.genai import types

    q_num = int(question["question_number"])
    points = float(question["points"])
    language = meta.get("language", "עברית")
    question = {**question, "_raw_log_start": len(getattr(service, "raw_log", []))}
    intro = (
        f"Question number: {q_num}\n"
        f"Authoritative total points for this question: {points:g}\n"
        f"Target language: {language}\n"
        f"Exam context: {json.dumps(_meta_for_prompt(meta), ensure_ascii=False)}\n"
        "Reconstruct this single question from the attached photos."
    )
    parts = [types.Part.from_text(text=intro), *_image_parts(question)]
    # High thinking is intentionally used for mathematical solving. It is slower, but materially safer.
    ai = service.generate(parts, QuestionAI, QUESTION_SYSTEM_PROMPT, thinking_level="high")
    q = postprocess_question(ai, q_num, points, len(question.get("images", [])))
    apply_notation_profile(q, notation.Profile(meta.get("notation_profile", notation.DEFAULT_PROFILE.value)))
    q.analysis_input_hashes = [image_digest(b) for b in question.get("images", [])]
    check_formulas(q, (question.get("document") or {}).get("text_layer") or question.get("text_layer"))
    check_text_structure(q, question)
    apply_source_line_breaks(q)
    extract_diagrams_pass2(service, q, question)
    q.model_evidence = [{**e, "source_hashes": q.analysis_input_hashes}
                        for e in getattr(service, "raw_log", [])[question.get("_raw_log_start", 0):]]
    attach_diagrams(q, question.get("images", []), ai_model=service.model, masters=question.get("masters"),
                    provenance=question.get("provenance"))
    return q


def analyze_header(service: GeminiService, meta: dict[str, Any]) -> ExamHeaderAI:
    from google.genai import types

    payload = {
        "target_language": meta.get("language"),
        "exam_name": meta.get("exam_name", ""),
        "grade": meta.get("grade", ""),
        "level": meta.get("level", ""),
        "instructions": meta.get("instructions", ""),
        "english_label_examples": ENGLISH_LABELS.model_dump(),
    }
    parts = [types.Part.from_text(text=json.dumps(payload, ensure_ascii=False, indent=2))]
    return service.generate(parts, ExamHeaderAI, HEADER_SYSTEM_PROMPT, max_output_tokens=8192)


def verify_question(service: GeminiService, meta: dict[str, Any], question: dict[str, Any], q: QuestionAnalysis) -> VerificationAI:
    from google.genai import types

    proposed = {
        "stem": q.text,
        "sections": [s.model_dump() for s in q.sections],
        "proposed_solution_steps": [s.model_dump() for s in q.solution_steps],
    }
    intro = (
        f"Target language: {meta.get('language', 'עברית')}\n"
        "Reconstructed question and proposed answer key (verify against the photos):\n"
        + json.dumps(proposed, ensure_ascii=False, indent=2)
    )
    parts = [types.Part.from_text(text=intro), *_image_parts(question)]
    return service.generate(parts, VerificationAI, VERIFY_SYSTEM_PROMPT, max_output_tokens=32768, thinking_level="high")


def default_header(meta: dict[str, Any]) -> ExamHeaderAI:
    language = meta.get("language", "עברית")
    return ExamHeaderAI(
        translated_exam_name=str(meta.get("exam_name", "")),
        translated_grade=str(meta.get("grade", "")),
        translated_level=str(meta.get("level", "")),
        translated_instructions=str(meta.get("instructions", "")),
        labels=HEBREW_LABELS if language == "עברית" else ENGLISH_LABELS,
    )


def run_full_analysis(
    service: GeminiService,
    meta: dict[str, Any],
    questions_data: list[dict[str, Any]],
    verify: bool = True,
    progress: Callable[[float, str], None] | None = None,
    max_workers: int = 3,
    existing: ExamAnalysis | None = None,
    only: set[int] | None = None,
) -> tuple[ExamAnalysis, list[str]]:
    """Analyze each question separately (parallel, rate-limited), then optionally verify each one independently.

    `existing` + `only` re-run just some questions (e.g. the ones that failed on quota) and keep the rest.
    Always returns an ExamAnalysis; failed questions carry `analysis_error` so the teacher can retry them.
    """
    from concurrent.futures import FIRST_COMPLETED, wait

    notes: list[str] = []
    language = meta.get("language", "עברית")
    todo = [q for q in questions_data if only is None or int(q["question_number"]) in only]
    need_header = existing is None and language != "עברית"
    total_jobs = len(todo) * (2 if verify else 1) + (1 if need_header else 0)
    done = 0
    last_msg = "מתחיל…"

    def report(msg: str | None = None) -> None:
        nonlocal last_msg
        if msg:
            last_msg = msg
        if progress:
            shown = service.status or last_msg
            progress(min(1.0, done / max(1, total_jobs)), shown)

    def drain(futures: dict, on_done: Callable[[Any, Any], str]) -> None:
        nonlocal done
        pending = set(futures)
        while pending:
            finished, pending = wait(pending, timeout=1.0, return_when=FIRST_COMPLETED)
            for fut in finished:
                msg = on_done(fut, futures[fut])
                done += 1
                report(msg)
            if not finished:
                report()

    if existing is not None:
        header = ExamHeaderAI(
            translated_exam_name=existing.translated_exam_name, translated_grade=existing.translated_grade,
            translated_level=existing.translated_level, translated_instructions=existing.translated_instructions,
            labels=existing.labels,
        )
    else:
        header = default_header(meta)
    report("שולח את השאלות ל-Gemini…")
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        if need_header:
            fut = pool.submit(analyze_header, service, meta)

            def header_done(f, _):
                nonlocal header
                try:
                    header = f.result()
                except Exception as exc:
                    notes.append(f"תרגום כותרות נכשל ({friendly_error(exc)}); נעשה שימוש בתוויות באנגלית.")
                return "תורגמו כותרות המסמך"

            drain({fut: None}, header_done)

        results: dict[int, QuestionAnalysis] = {}

        def q_done(f, q):
            num = int(q["question_number"])
            try:
                results[num] = f.result()
            except Exception as exc:
                failed = empty_question(num, float(q["points"]), f"הפענוח נכשל: {friendly_error(exc)}")
                failed.error_detail = str(exc)
                results[num] = failed
            return f"פוענחה שאלה {num}"

        drain({pool.submit(analyze_question, service, meta, q): q for q in todo}, q_done)

        if verify:
            by_num = {int(q["question_number"]): q for q in todo}
            ok = {num: qa for num, qa in results.items() if not qa.analysis_error}
            done += len(results) - len(ok)  # skipped verifications

            def v_done(f, num):
                try:
                    results[num].verification = f.result()
                except Exception as exc:
                    results[num].verification_error = f"האימות נכשל: {friendly_error(exc)}"
                return f"אומתה שאלה {num}"

            drain({pool.submit(verify_question, service, meta, by_num[num], qa): num for num, qa in ok.items()}, v_done)

    merged: dict[int, QuestionAnalysis] = {q.question_number: q for q in existing.questions} if existing else {}
    merged.update(results)
    notes.extend(dict.fromkeys(service.notes))
    if service.rate_limit_events:
        notes.append(
            f"Gemini הגביל את קצב הבקשות (עד {service.rpm} בדקה), ולכן הפענוח הואט אוטומטית."
        )
    exam = ExamAnalysis(
        translated_exam_name=header.translated_exam_name,
        translated_grade=header.translated_grade,
        translated_level=header.translated_level,
        translated_instructions=header.translated_instructions,
        labels=header.labels,
        questions=[merged[k] for k in sorted(merged)],
        model_used=service.model,
    )
    return exam, notes


def estimate_calls(n_questions: int, verify: bool, language: str) -> int:
    return n_questions * (2 if verify else 1) + (0 if language == "עברית" else 1)


def postprocess_question(ai: QuestionAI, number: int, points: float, image_count: int) -> QuestionAnalysis:
    q = QuestionAnalysis(question_number=number, points=points, **ai.model_dump())
    for sec in q.sections:
        sec.section_id = clean_section_id(sec.section_id)
        sec.selection_group = (sec.selection_group or "").strip()
    for fig in q.figures:
        fig.section_id = clean_section_id(fig.section_id)          # same normalisation as QuestionSection
    if 0 < q.required_sections < len(q.sections) and not q.selection_groups:
        q.selection_groups = [SelectionGroup(group_id="all", choose_k=q.required_sections)]   # legacy shorthand -> canonical
        for sec in q.sections:
            sec.selection_group = "all"
        sec.points = max(0.0, float(sec.points))
    for step in q.solution_steps:
        step.section_id = clean_section_id(step.section_id)
    for rub in q.rubric_steps:
        rub.section_id = clean_section_id(rub.section_id)
        rub.percentage = min(100.0, max(0.0, float(rub.percentage)))
        for err in rub.common_errors:
            err.deduction_percent = min(100.0, max(0.0, float(err.deduction_percent)))
    seen_ids: set[str] = set()
    for i, fig in enumerate(q.figures, 1):
        if not fig.figure_id or fig.figure_id in seen_ids:
            fig.figure_id = f"q{number}f{i}"
        seen_ids.add(fig.figure_id)
    for fig in q.figures:
        fig.source_image_index = min(max(1, int(fig.source_image_index)), max(1, image_count))
        fig.rebuild_confidence = min(1.0, max(0.0, float(fig.rebuild_confidence)))
        if fig.figure_type not in SUPPORTED_FIGURE_TYPES:
            fig.figure_type = "source_crop"
            fig.rebuild_required = False
        if fig.bbox and (len(fig.bbox) != 4 or not bbox_is_valid(fig.bbox)):
            fig.bbox = []
    return q


def clean_section_id(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^(?:סעיף|תת[- ]?סעיף|section|part)\s+", "", text, flags=re.IGNORECASE)
    return text.strip().strip(".():[]-–' ").strip()          # ONE canonical form for sections AND figures


# ============================================================
# 3. Scoring + validation
# ============================================================
def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        result = float(value)
        if result != result:  # NaN
            return default
        return result
    except (TypeError, ValueError):
        return default


def normalize_decimal(value: Any) -> Decimal:
    return Decimal(str(safe_float(value))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def fmt_points(value: Any) -> str:
    d = normalize_decimal(value)
    return f"{d:f}".rstrip("0").rstrip(".") if "." in f"{d:f}" else f"{d:f}"


def bbox_is_valid(bbox: list[int]) -> bool:
    if len(bbox) != 4:
        return False
    y1, x1, y2, x2 = bbox
    return all(0 <= v <= 1000 for v in bbox) and y1 < y2 and x1 < x2


def validate_choice_groups(num_questions: int, groups: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    all_expected = set(range(1, num_questions + 1))
    seen: list[int] = []
    for i, group in enumerate(groups, 1):
        questions = [int(x) for x in group.get("questions", [])]
        required = int(group.get("required", 0))
        if not questions:
            errors.append(f"קבוצת בחירה {i} ריקה.")
            continue
        if required < 1 or required > len(questions):
            errors.append(f"בקבוצה {i} מספר השאלות הנדרש אינו חוקי.")
        seen.extend(questions)
    duplicated = sorted({q for q in seen if seen.count(q) > 1})
    missing = sorted(all_expected - set(seen))
    extra = sorted(set(seen) - all_expected)
    if duplicated:
        errors.append(f"השאלות הבאות מופיעות ביותר מקבוצה אחת: {duplicated}")
    if missing:
        errors.append(f"השאלות הבאות אינן משויכות לקבוצת בחירה: {missing}")
    if extra:
        errors.append(f"מספרי שאלות לא חוקיים בקבוצות: {extra}")
    return errors


def suggested_points(meta: dict[str, Any]) -> dict[int, float]:
    """Default points. With no choice the remainder goes to the last question so the total is exactly 100."""
    n = int(meta.get("num_questions", 1))
    groups = meta.get("choice_groups", []) or [{"questions": list(range(1, n + 1)), "required": n}]
    total_required = sum(int(g.get("required", 0)) for g in groups) or n
    each = (TARGET_SCORE / Decimal(total_required)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    result = {q: float(each) for q in range(1, n + 1)}
    no_choice = all(int(g.get("required", 0)) == len(g.get("questions", [])) for g in groups)
    if no_choice and n:
        result[n] = float(TARGET_SCORE - each * (n - 1))
    return result


def route_tolerance(groups: list[dict[str, Any]]) -> Decimal:
    """Allow rounding of 0.005 per required question (e.g. 7 × 14.29 = 100.03) but never less than 0.02."""
    required = sum(int(g.get("required", 0)) for g in groups)
    return max(POINT_TOLERANCE, Decimal("0.005") * required + Decimal("0.001"))


def validate_points_structure(meta: dict[str, Any], points_by_q: dict[int, Any]) -> list[str]:
    errors: list[str] = []
    groups = meta.get("choice_groups", [])
    route_total = Decimal("0")
    for idx, group in enumerate(groups, 1):
        nums = [int(x) for x in group.get("questions", [])]
        required = int(group.get("required", 0))
        pts = [normalize_decimal(points_by_q[n]) for n in nums if n in points_by_q]
        if len(pts) != len(nums):
            continue
        if required < len(nums):
            if len(set(pts)) != 1:
                errors.append(
                    f"קבוצת בחירה {idx}: כאשר בוחרים {required} מתוך {len(nums)}, כל השאלות בקבוצה חייבות להיות באותו ניקוד."
                )
            elif pts:
                route_total += pts[0] * required
        else:
            route_total += sum(pts, Decimal("0"))
    if groups and abs(route_total - TARGET_SCORE) > route_tolerance(groups):
        errors.append(f"סך הניקוד במסלול בחירה חוקי הוא {route_total} ולא 100.")
    return errors


def question_texts(q: QuestionAnalysis) -> str:
    return "\n".join(
        [
            q.text, q.topic,
            *(s.text for s in q.sections),
            *(s.content for s in q.solution_steps),
            *(s.final_answer for s in q.solution_steps),
            *(r.stage_desc for r in q.rubric_steps),
            *(r.full_credit for r in q.rubric_steps),
            *(r.partial_credit for r in q.rubric_steps),
            *(r.zero_credit for r in q.rubric_steps),
            *(r.carried_over_error_policy for r in q.rubric_steps),
            *(f.description for f in q.figures),
        ]
    )


def validate_exam(exam: ExamAnalysis, meta: dict[str, Any], questions_data: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    expected_n = int(meta.get("num_questions", 0))
    actual_numbers = [q.question_number for q in exam.questions]
    if len(exam.questions) != expected_n or set(actual_numbers) != set(range(1, expected_n + 1)):
        errors.append(f"מספור השאלות ({sorted(actual_numbers)}) אינו תואם את מבנה הבחינה ({expected_n} שאלות).")

    source_by_num = {int(q["question_number"]): q for q in questions_data}
    for q in exam.questions:
        num = q.question_number
        source = source_by_num.get(num, {})
        if q.analysis_error:
            errors.append(f"שאלה {num}: {q.analysis_error} — יש לפענח אותה מחדש.")
            continue
        total = normalize_decimal(q.points)
        if not q.text.strip() and not q.sections:
            errors.append(f"שאלה {num}: אין נוסח שאלה.")
        errors += [f"שאלה {num}: {m}" for m in scoring.check(q)]          # ONE canonical scoring model
        ids = [s.section_id for s in q.sections]
        if len(ids) != len(set(ids)):
            errors.append(f"שאלה {num}: יש מזהי סעיפים כפולים.")
        if not q.solution_steps:
            errors.append(f"שאלה {num}: לא קיימים שלבי פתרון.")
        if not q.rubric_steps:
            errors.append(f"שאלה {num}: לא קיימים שלבי מחוון.")

        # A solution is not complete until every requested part has an explicit final answer.
        expected_solution_ids = [s.section_id for s in q.sections] if q.sections else [""]
        for section_id in expected_solution_ids:
            matching = [s for s in q.solution_steps if s.section_id == section_id]
            label = f", סעיף {section_id}" if section_id else ""
            if not matching:
                errors.append(f"שאלה {num}{label}: חסר פתרון המשויך לסעיף.")
            elif not any(s.final_answer.strip() for s in matching):
                errors.append(f"שאלה {num}{label}: חסרה תשובה סופית מפורשת.")

        # Rubric per section must match section points (warning — a stage may legitimately span sections).
        if q.sections and q.rubric_steps and total > 0:
            for sec in q.sections:
                stages = [r for r in q.rubric_steps if r.section_id == sec.section_id]
                if not stages:
                    warnings.append(f"שאלה {num}, סעיף {sec.section_id}: אין שלבי מחוון המשויכים לסעיף.")
                    continue
                pct = sum((normalize_decimal(r.percentage) for r in stages), Decimal("0"))
                pts = (pct * total / Decimal("100")).quantize(Decimal("0.01"))
                if abs(pts - normalize_decimal(sec.points)) > Decimal("0.05"):
                    warnings.append(
                        f"שאלה {num}, סעיף {sec.section_id}: המחוון מקצה {pts} נק' אך הסעיף שווה {normalize_decimal(sec.points)} נק'."
                    )
        image_count = len(source.get("images", []))
        for fig_idx, fig in enumerate(q.figures, 1):
            if fig.source_image_index < 1 or fig.source_image_index > image_count:
                errors.append(f"שאלה {num}, תרשים {fig_idx}: תמונת מקור {fig.source_image_index} אינה קיימת.")
            if fig.bbox and not bbox_is_valid(fig.bbox):
                errors.append(f"שאלה {num}, תרשים {fig_idx}: bbox אינו חוקי.")
            rec = q.diagrams.get(fig.figure_id)
            if STRICTNESS == diagram_engine.constants.ReconstructionStrictness.EXAM_QUALITY:
                if figure_decision_pending(rec):
                    why = rec.teacher_message if rec is not None else "אין נתוני שחזור"
                    errors.append(f"שאלה {num}, תרשים {fig_idx}: נדרשת החלטת מורה — אישור השחזור או שימוש חריג בסריקה. ({why})")
                elif diagram_engine.usable_in_document(rec) and not figure_render_ok(rec):
                    errors.append(f"שאלה {num}, תרשים {fig_idx}: EXPORT_BLOCKED — השרטוט המאושר אינו ניתן להפקה. נדרשת החלטת מורה.")
                elif diagram_engine.raster_allowed(rec):
                    warnings.append(f"שאלה {num}, תרשים {fig_idx}: ישולב צילום מקורי באישור חריג של המורה.")
            elif rec is not None and rec.spec is not None and rec.spec.diagram_type != "unknown":
                if rec.review.status == "pending" and rec.decision.action in ("review", "draft", "high_confidence_preview"):
                    warnings.append(f"שאלה {num}, תרשים {fig_idx}: השחזור ממתין לאישור מורה (מצב LEGACY: עד לאישור ישולב השרטוט המקורי).")

        prof = notation.Profile(meta.get("notation_profile", notation.DEFAULT_PROFILE.value))
        if notation.is_statistics(q.text + " " + " ".join(s_.text for s_ in q.sections)):
            errors += notation.inconsistencies(_generated_texts(q), prof)
        if UNREADABLE_MARK in question_texts(q):
            errors.append(f"שאלה {num}: קיימים פרטים המסומנים {UNREADABLE_MARK} — יש לתקן לפני הפקה.")

        # formula validation is bound to the exact math content: stale results are recomputed, never reused
        src = next((d for d in questions_data if int(d.get("question_number", 0)) == int(num)), {}) if questions_data else {}
        if getattr(q, "formula_fingerprint", None) is None:           # objects saved by an older version: migrate
            q.formula_fingerprint, q.teacher_verified_fp, q.text_structure_source = "", "", {}
        if q.formula_checks or q.formula_fingerprint or (src.get("document") or {}).get("text_layer"):
            if q.formula_fingerprint != formula_fingerprint(q):
                check_formulas(q, (src.get("document") or {}).get("text_layer") or src.get("text_layer"))
        verified_now = q.teacher_verified and (not q.teacher_verified_fp or q.teacher_verified_fp == verification_fingerprint(q))
        ts = q.text_structure_source or {}
        struct_issues = text_structure.fidelity_issues(q, ts.get("text"), bool(ts.get("reliable_commas")))
        if struct_issues and not verified_now:
            errors += [f"שאלה {num}: {m}" for m in struct_issues[:3]]
        if q.teacher_verified and q.teacher_verified_fp and not verified_now:
            errors.append(f"שאלה {num}: FORMULA_REVALIDATION_REQUIRED — המתמטיקה או מבנה הסעיפים שונו אחרי אישור המורה; יש לאשר מחדש.")
        if q.formula_uncertain and not verified_now:
            errors += [f"שאלה {num}: {m}" for m in q.formula_uncertain[:3]]
        unparsed = [f["latex"] for f in q.formula_checks if f.get("status") != "OK"]
        if unparsed:
            warnings.append(f"שאלה {num}: {len(unparsed)} נוסחאות לא נותחו סמלית (יוצגו כפי שהן) — מומלץ לבדוק: {unparsed[0][:40]}")
        if not q.teacher_verified:
            if q.verification_error:
                errors.append(f"שאלה {num}: {q.verification_error} — נדרש אימות ידני לפני הפקה.")
            elif q.verification is None:
                errors.append(f"שאלה {num}: לא בוצעה בדיקה עצמאית — נדרש אימות ידני לפני הפקה.")
            else:
                expected_ids = [clean_section_id(s.section_id) for s in q.sections] if q.sections else [""]
                returned_ids = [clean_section_id(i.section_id) for i in q.verification.items]
                missing = [sid for sid in expected_ids if sid not in returned_ids]
                duplicates = sorted({sid for sid in returned_ids if returned_ids.count(sid) > 1})
                extras = [sid for sid in returned_ids if sid not in expected_ids]
                if missing or duplicates or extras or len(returned_ids) != len(expected_ids):
                    details = []
                    if missing:
                        details.append("חסרים: " + ", ".join(s or "כללי" for s in missing))
                    if duplicates:
                        details.append("כפולים: " + ", ".join(s or "כללי" for s in duplicates))
                    if extras:
                        details.append("לא צפויים: " + ", ".join(s or "כללי" for s in extras))
                    errors.append(f"שאלה {num}: הבדיקה העצמאית אינה מכסה בדיוק את כל הסעיפים ({'; '.join(details)}).")

                bad = [i for i in q.verification.items if not (i.agrees and i.reasoning_agrees and i.source_text_agrees)]
                if (
                    bad
                    or not q.verification.overall_agrees
                    or not q.verification.reasoning_agrees
                    or not q.verification.source_reconstruction_agrees
                ):
                    ids_txt = ", ".join(i.section_id or "כללי" for i in bad) or "כללי"
                    errors.append(
                        f"שאלה {num}: הבדיקה העצמאית מצאה אי-התאמה במקור, בדרך הפתרון או בתשובה "
                        f"(סעיפים: {ids_txt}). בדוק וסמן 'אימתתי ידנית'."
                    )

    errors.extend(validate_points_structure(meta, {q.question_number: q.points for q in exam.questions}))
    return errors, warnings


def rebalance_question(q: QuestionAnalysis) -> None:
    """UI auto-balance: delegates to the canonical scoring model (keeps 'answer K of N' rules)."""
    scoring.rebalance(q)


def allocate_rubric_points(total_points: float, percentages: list[float]) -> list[Decimal]:
    total = normalize_decimal(total_points)
    if not percentages:
        return []
    values = [
        (total * Decimal(str(p)) / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) for p in percentages
    ]
    pct_sum = sum((normalize_decimal(p) for p in percentages), Decimal("0"))
    if abs(pct_sum - Decimal("100")) <= POINT_TOLERANCE:
        values[-1] += total - sum(values, Decimal("0"))
    return values


def build_default_instructions(duration: int, groups: list[dict[str, Any]]) -> str:
    lines = [f"• משך הבחינה: {duration} דקות."]
    if len(groups) == 1:
        g = groups[0]
        count = len(g["questions"])
        required = int(g["required"])
        if required == count:
            lines.append(f"• מבנה המבחן: יש לענות על כל {count} השאלות.")
        else:
            lines.append(f"• מבנה המבחן: יש לענות על {required} מתוך {count} השאלות.")
    else:
        lines.append("• מבנה המבחן:")
        for idx, g in enumerate(groups, 1):
            q_text = ", ".join(str(x) for x in g["questions"])
            required = int(g["required"])
            if required == len(g["questions"]):
                lines.append(f"  ◦ קבוצה {idx} — שאלות {q_text}: יש לענות על כולן.")
            else:
                lines.append(f"  ◦ קבוצה {idx} — שאלות {q_text}: יש לענות על {required} שאלות.")
    lines += [
        "• חומר עזר מותר: מחשבון ודף נוסחאות בהתאם להנחיות המורה.",
        "• חובה להציג את דרך הפתרון ואת שלבי החישוב. תשובה ללא דרך לא תזכה במלוא הניקוד.",
        "• הקפידו על כתיבה ברורה ומסודרת, והעתיקו שרטוטים רלוונטיים למחברת כאשר נדרש.",
    ]
    return "\n".join(lines)


# ============================================================
# 4. Image processing
# ============================================================
def image_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _to_rgb(img: Image.Image) -> Image.Image:
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        return Image.alpha_composite(bg, rgba).convert("RGB")
    return img.convert("RGB")


def pil_to_png_bytes(img: Image.Image, max_side: int = MAX_IMAGE_SIDE) -> bytes:
    prepared = _to_rgb(img.copy())
    if max(prepared.size) > max_side:
        prepared.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    prepared.save(out, format="PNG", compress_level=6)
    return out.getvalue()


MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_IMAGE_PIXELS = 60_000_000          # ~ 7700 x 7700; decompression bombs are rejected before decoding
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


class ImageInputError(ValueError):
    """A user-facing (Hebrew) problem with an uploaded image."""


def image_to_png_bytes(source: Any, max_side: int | None = MAX_IMAGE_SIDE) -> bytes:
    """Normalize UploadedFile / camera / PIL / bytes into orientation-correct RGB PNG bytes.
    max_side=None keeps the FULL resolution (ORIGINAL_MASTER). Rejects oversized files, decompression bombs and
    malformed images with a clear Hebrew message."""
    max_side = max_side or 10 ** 9
    if isinstance(source, Image.Image):
        return pil_to_png_bytes(source, max_side=max_side)
    if isinstance(source, (bytes, bytearray)):
        raw = bytes(source)
    elif hasattr(source, "getvalue"):
        raw = source.getvalue()
    elif hasattr(source, "read"):
        raw = source.read()
    else:
        raise TypeError(f"Unsupported image source: {type(source)!r}")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ImageInputError(f"הקובץ גדול מדי ({len(raw) // (1024 * 1024)}MB). הגודל המרבי הוא {MAX_UPLOAD_BYTES // (1024 * 1024)}MB.")
    try:
        with Image.open(io.BytesIO(raw)) as im:
            if im.width * im.height > MAX_IMAGE_PIXELS:
                raise ImageInputError("התמונה גדולה מדי (מספר פיקסלים חריג). יש להקטין אותה ולנסות שוב.")
            im.load()
            return pil_to_png_bytes(im, max_side=max_side)
    except ImageInputError:
        raise
    except Image.DecompressionBombError:
        raise ImageInputError("הקובץ נראה כתמונה חריגה (פצצת פענוח) ולכן נחסם.") from None
    except Exception:
        raise ImageInputError("לא ניתן לקרוא את הקובץ כתמונה. יש להעלות PNG, JPG או WEBP תקינים.") from None


def png_bytes_to_pil(data: bytes) -> Image.Image:
    with Image.open(io.BytesIO(data)) as im:
        im.load()
        return _to_rgb(im.copy())


def fit_for_editor(img: Image.Image, max_width: int = 760, max_height: int = 1000) -> tuple[Image.Image, float]:
    """Return a display copy and the scale factor full/display (>= 1)."""
    copy = img.copy()
    copy.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
    scale = img.width / copy.width if copy.width else 1.0
    return copy, scale


def crop_normalized(data: bytes, rect: list[float], max_side: int | None = None) -> bytes:
    """Crop by a NORMALIZED rectangle [l, t, r, b] in 0..1 (resolution independent); no downsampling unless max_side."""
    img = png_bytes_to_pil(data)
    l, t, r, b = (round(v * s) for v, s in zip(rect, (img.width, img.height, img.width, img.height)))
    l, t = max(0, min(img.width - 1, l)), max(0, min(img.height - 1, t))
    r, b = max(l + 1, min(img.width, r)), max(t + 1, min(img.height, b))
    return pil_to_png_bytes(img.crop((l, t, r, b)), max_side=max_side or 10 ** 9)


def crop_box_to_normalized(working: bytes, box: dict[str, Any], scale: float) -> list[float]:
    img = png_bytes_to_pil(working)
    left, top = safe_float(box.get("left")) * scale, safe_float(box.get("top")) * scale
    width, height = safe_float(box.get("width")) * scale, safe_float(box.get("height")) * scale
    return [left / img.width, top / img.height, (left + width) / img.width, (top + height) / img.height]


def apply_master_op(master: bytes, op: dict[str, Any], store: Any) -> bytes:
    """Replay one recorded edit on the FULL-RESOLUTION master (never downsampled)."""
    t = op.get("type")
    if t == "crop":
        return crop_normalized(master, op["rect"])
    if t == "erase":
        mask = np.asarray(Image.open(io.BytesIO(store.get(op["mask_id"]))).convert("RGBA"))
        return apply_erase_mask(master, mask, max_side=10 ** 9)[0]
    if t == "rotate":
        return rotate_image_bytes(master, float(op["deg"]), max_side=10 ** 9)
    raise ValueError(f"unknown edit op {t}")


def crop_full_resolution(full_bytes: bytes, box: dict[str, Any], scale: float) -> bytes:
    """Apply a crop box expressed in display coordinates to the full-resolution image."""
    img = png_bytes_to_pil(full_bytes)
    left = safe_float(box.get("left")) * scale
    top = safe_float(box.get("top")) * scale
    width = safe_float(box.get("width")) * scale
    height = safe_float(box.get("height")) * scale
    l = max(0, min(img.width - 1, round(left)))
    t = max(0, min(img.height - 1, round(top)))
    r = max(l + 1, min(img.width, round(left + width)))
    b = max(t + 1, min(img.height, round(top + height)))
    if r - l < 10 or b - t < 10:
        raise ValueError("אזור החיתוך קטן מדי.")
    return pil_to_png_bytes(img.crop((l, t, r, b)))


def apply_erase_mask(full_bytes: bytes, canvas_rgba: Any, max_side: int = MAX_IMAGE_SIDE) -> tuple[bytes, float]:
    """Whiten on the full-resolution image every pixel painted on the canvas layer.

    The drawable-canvas component returns ONLY the drawing layer (RGBA, transparent where nothing
    was drawn) at display size. We scale that mask up to the full image, so no resolution is lost.
    Returns (png_bytes, fraction_of_image_erased).
    """
    arr = np.asarray(canvas_rgba)
    if arr.ndim != 3 or arr.shape[2] < 4:
        raise ValueError("פלט הקנבס אינו בפורמט RGBA.")
    alpha = arr[:, :, 3].astype(np.uint8)
    if not alpha.any():
        raise ValueError("לא סומן אזור למחיקה.")
    fraction = float((alpha > 0).mean())
    if fraction > 0.97:
        raise ValueError("כמעט כל התמונה סומנה למחיקה — הפעולה בוטלה ליתר ביטחון.")
    img = png_bytes_to_pil(full_bytes)
    mask = Image.fromarray(np.where(alpha > 0, 255, 0).astype(np.uint8), "L")
    mask = mask.resize(img.size, Image.Resampling.BILINEAR).point(lambda v: 255 if v >= 96 else 0)
    img.paste((255, 255, 255), mask=mask)
    return pil_to_png_bytes(img, max_side=max_side), fraction


def rotate_image_bytes(data: bytes, degrees: float, max_side: int = MAX_IMAGE_SIDE) -> bytes:
    """Positive = counter-clockwise (PIL convention). The canvas grows so no corner is cut."""
    img = png_bytes_to_pil(data)
    if abs(degrees) % 90 == 0:
        method = {90: Image.Transpose.ROTATE_90, 180: Image.Transpose.ROTATE_180, 270: Image.Transpose.ROTATE_270}
        k = int(round(degrees)) % 360
        return pil_to_png_bytes(img.transpose(method[k]) if k else img, max_side=max_side)
    rotated = img.rotate(float(degrees), resample=Image.Resampling.BICUBIC, expand=True, fillcolor=(255, 255, 255))
    return pil_to_png_bytes(rotated, max_side=max_side)


def _otsu_threshold(gray: np.ndarray) -> int:
    hist = np.bincount(gray.ravel(), minlength=256).astype(np.float64)
    total = gray.size
    sum_total = np.dot(np.arange(256), hist)
    w_b = sum_b = 0.0
    best_t, best_var = 127, -1.0
    for t in range(256):
        w_b += hist[t]
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += t * hist[t]
        m_b = sum_b / w_b
        m_f = (sum_total - sum_b) / w_f
        var = w_b * w_f * (m_b - m_f) ** 2
        if var > best_var:
            best_var, best_t = var, t
    return best_t


def estimate_skew_angle(img: Image.Image, max_angle: float = 15.0) -> float:
    """Projection-profile deskew. Returns the angle (degrees, PIL convention) that straightens the text lines."""
    gray = ImageOps.grayscale(img)
    gray.thumbnail((1000, 1000))
    arr = np.asarray(gray, dtype=np.uint8)
    # Remove slow illumination changes (phone photos / shadows) before thresholding.
    blurred = np.asarray(gray.resize((max(1, gray.width // 16), max(1, gray.height // 16))).resize(gray.size, Image.Resampling.BILINEAR), dtype=np.int16)
    flat = np.clip(arr.astype(np.int16) - blurred + 200, 0, 255).astype(np.uint8)
    t = _otsu_threshold(flat)
    ink = (flat < min(t, 185)).astype(np.uint8) * 255
    if ink.mean() < 0.3:  # almost empty page
        return 0.0
    ink_img = Image.fromarray(ink, "L")

    def score(angle: float) -> float:
        rotated = np.asarray(ink_img.rotate(angle, resample=Image.Resampling.NEAREST, expand=False), dtype=np.float64)
        profile = rotated.sum(axis=1)
        return float(np.sum(np.diff(profile) ** 2))

    coarse = np.arange(-max_angle, max_angle + 0.001, 1.0)
    best = max(coarse, key=score)
    fine = np.arange(best - 1.0, best + 1.0001, 0.1)
    best = max(fine, key=score)
    return float(round(best, 2))


def auto_straighten_bytes(data: bytes) -> tuple[bytes, float]:
    img = png_bytes_to_pil(data)
    angle = estimate_skew_angle(img)
    if abs(angle) < 0.15:
        return data, 0.0
    return rotate_image_bytes(data, angle), angle


def crop_figure_bytes(source: bytes, bbox: list[int] | None, max_side: int | None = MAX_IMAGE_SIDE) -> bytes:
    image = png_bytes_to_pil(source)
    if bbox and bbox_is_valid(bbox):
        y1, x1, y2, x2 = bbox
        w, h = image.size
        left = max(0, min(w - 1, round(x1 / 1000 * w)))
        right = max(left + 1, min(w, round(x2 / 1000 * w)))
        top = max(0, min(h - 1, round(y1 / 1000 * h)))
        bottom = max(top + 1, min(h, round(y2 / 1000 * h)))
        image = image.crop((left, top, right, bottom))
    return pil_to_png_bytes(image, max_side=max_side or 10 ** 9)


# ============================================================
# 5. Safe math-expression parser (lives in diagram_engine.safe_math; re-exported for compatibility)
# ============================================================
latex_to_plain = _sm.latex_to_plain
safe_function = _sm.safe_function


# ============================================================
# 6. Figures: text direction helpers + deterministic diagram engine integration
# ============================================================
def has_rtl(text: str) -> bool:
    return bool(RTL_CHARS.search(text or ""))


def visual_text(text: Any) -> str:
    """Convert logical-order Hebrew/Arabic to visual order for renderers without bidi support (matplotlib)."""
    s = str(text or "")
    if not has_rtl(s):
        return s
    if ARABIC_CHARS.search(s) and arabic_reshaper is not None:
        s = arabic_reshaper.reshape(s)
    if _bidi_get_display is None:
        return s
    from diagram_engine.text_utils import mirror_brackets   # python-bidi does not mirror brackets (fixed in 5.5)

    return "\n".join(_bidi_get_display(mirror_brackets(line)) for line in s.split("\n"))


def question_text_for_diagrams(q: QuestionAnalysis) -> str:
    return "\n".join([q.text, *(f"{s.section_id}. {s.text}" for s in q.sections)])


def padded(fig: FigureRef, frac: float) -> FigureRef:
    """The same figure with its bbox enlarged by `frac` of its size on every side (clipped to the page)."""
    if not fig.bbox or len(fig.bbox) != 4:
        return fig
    y0, x0, y1, x1 = fig.bbox
    dy, dx = (y1 - y0) * frac, (x1 - x0) * frac
    return fig.model_copy(update={"bbox": [max(0, int(y0 - dy)), max(0, int(x0 - dx)), min(1000, int(y1 + dy)), min(1000, int(x1 + dx))]})


def figure_source_crop(fig: FigureRef, images: list[bytes], masters: list[bytes] | None = None) -> bytes | None:
    """ROI crop. bbox is NORMALIZED (0..1000) -> taken from the full-resolution master-edited asset when available
    (never from an upscaled preview)."""
    if masters:
        idx = fig.source_image_index - 1
        if 0 <= idx < len(masters) and masters[idx]:
            try:
                return crop_figure_bytes(masters[idx], fig.bbox, max_side=None)
            except Exception:
                return None
    return _working_crop(fig, images)


def _working_crop(fig: FigureRef, images: list[bytes]) -> bytes | None:
    idx = fig.source_image_index - 1
    if 0 <= idx < len(images):
        try:
            return crop_figure_bytes(images[idx], fig.bbox)
        except Exception:
            return None
    return None


def _diagram_input_key(fig: FigureRef, images: list[bytes], spec: DiagramSpec | None = None) -> str:
    idx = fig.source_image_index - 1
    img = images[idx] if 0 <= idx < len(images) else b""
    raw = f"{diagram_engine.PARSER_VERSION}|{idx}|{fig.bbox}|{fig.figure_type}|{fig.rebuild_confidence}|{image_digest(img)}|{fig.spec_json}"
    if spec is not None:
        raw += "|" + spec.model_dump_json()
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _generated_texts(q: QuestionAnalysis) -> dict[str, str]:
    out = {}
    for i, st_ in enumerate(q.solution_steps, 1):
        out[f"שאלה {q.question_number} פתרון שלב {i}"] = f"{st_.content} {st_.final_answer}"
    for i, r in enumerate(q.rubric_steps, 1):
        out[f"שאלה {q.question_number} מחוון {i}"] = f"{r.full_credit} {r.partial_credit} {r.zero_credit}"
    return out


def apply_notation_profile(q: QuestionAnalysis, profile: "notation.Profile") -> None:
    """Semantic MEAN / STANDARD_DEVIATION displayed per profile in GENERATED content (solutions, rubric) of statistics
    questions. The transcribed question text is never rewritten (SOURCE_FAITHFUL for the source)."""
    if not notation.is_statistics(q.text + " " + " ".join(s.text for s in q.sections)):
        return
    for st_ in q.solution_steps:
        st_.content, st_.final_answer = notation.apply_profile(st_.content, profile), notation.apply_profile(st_.final_answer, profile)
    for r in q.rubric_steps:
        r.full_credit, r.partial_credit, r.zero_credit = (notation.apply_profile(r.full_credit, profile),
                                                          notation.apply_profile(r.partial_credit, profile),
                                                          notation.apply_profile(r.zero_credit, profile))


def reconstruction_text(q: QuestionAnalysis, fig: "FigureRef | None" = None, visible: set[str] | None = None) -> str:
    """Only the text that constrains THIS figure: the stem + declarative sentences of the subparts relevant to it (a figure
    bound to subpart X: the subparts up to X; a stem figure: all). Facts of another subpart never leak into a figure."""
    from diagram_engine.text_facts import split_by_role
    secs = q.sections
    if fig is not None and fig.section_id and any(s_.section_id == fig.section_id for s_ in secs):
        ids = [s_.section_id for s_ in secs]
        secs = [secs[ids.index(fig.section_id)]]                  # its own subpart (earlier subparts are other tasks)
    recon, _ = split_by_role([s.text for s in secs])
    if visible is not None and not (fig is not None and fig.section_id):
        # a STEM figure: a subpart given that introduces entities NOT shown in the figure ("F on DE" added later) is a
        # given for the solution, not a drawing requirement
        import re as _re
        from diagram_engine.text_facts import clauses as _cl
        stem_names = set(_re.findall(r"(?<![A-Za-z])[A-Z](?:'|′)?", q.text or ""))
        known = stem_names | set(visible)
        keep = [cl for kind, cl in _cl(recon) if kind == "GIVEN" and set(_re.findall(r"(?<![A-Za-z])[A-Z](?![a-z])", cl)) <= known]
        recon = " ".join(keep)
    out = (q.text or "") + ("\n" + recon if recon else "")
    if visible is not None:
        out = _visible_measurements_only(out, visible)
    return out


def _visible_measurements_only(text: str, visible: set[str]) -> str:
    """A MEASUREMENT given ("60 ס"מ ו־30 ס"מ וגובהו 40 ס"מ") belongs to the object that shows it: kept only when one of its
    values is visible in THIS figure (a question with two objects - an aquarium and a filter - has two figures)."""
    import re as _re
    from diagram_engine.text_facts import clauses as _cl2
    vis_nums = {_re.sub(r"[^\d.]", "", v) for v in visible if _re.search(r"\d", v)}
    unit = '(?:ס"מ|סמ"ק|מ"מ|ס״מ|סמ״ק|מטר(?:ים)?|גרם|ק"ג|קמ"ש|ליטר)'
    kept = []
    for _kind, cl in _cl2(text):
        nums = _re.findall(r"(\d+(?:[.,]\d+)?)\s*" + unit, cl)
        if nums and not any(n.replace(",", "") in vis_nums for n in nums):
            continue
        kept.append(cl)
    return " ".join(kept)


def formula_fingerprint(q: "QuestionAnalysis") -> str:
    from diagram_engine import formula_pipeline as fp
    return fp.math_fingerprint([q.text] + [s_.text for s_ in q.sections], q.analysis_input_hashes)


def check_formulas(q: "QuestionAnalysis", text_layer: str | None = None) -> None:
    """Every formula -> ExpressionAST -> validation -> LOCAL structural cross-check (PDF text layer when present).
    The result is bound to formula_fingerprint(q): any later change of the mathematics makes it stale."""
    from diagram_engine import formula_pipeline as fp
    texts = [q.text] + [s_.text for s_ in q.sections]
    q.formula_checks = fp.question_formulas(texts)
    q.formula_uncertain = fp.cross_check(q.formula_checks, text_layer)
    q.formula_fingerprint = formula_fingerprint(q)


def check_text_structure(q: "QuestionAnalysis", question: dict[str, Any]) -> None:
    """Independent structure evidence for the TEXT_STRUCTURE fidelity gate: the PDF text layer (reliable punctuation) or
    Hebrew OCR of the question images (section/subsection markers only - OCR commas are not trusted)."""
    layer = (question.get("document") or {}).get("text_layer") or question.get("text_layer")
    if layer:
        q.text_structure_source = {"text": layer, "reliable_commas": True, "source": "pdf_text_layer",
                                   "lines": (question.get("document") or {}).get("source_lines") or []}
        return
    try:
        from diagram_engine import ocr
        if not ocr.available():
            return
        texts = []
        for b in question.get("images", [])[:4]:
            texts.append(text_structure.ocr_marker_text(png_bytes_to_pil(b)))
        q.text_structure_source = {"text": "\n".join(texts), "reliable_commas": False, "source": "ocr",
                                   "lines": [l for t in texts for l in t.splitlines() if l.strip()]}
    except Exception:
        q.text_structure_source = {}


def verification_fingerprint(q: "QuestionAnalysis") -> str:
    """What a teacher confirmation covers: the mathematics AND the text structure (sections, subsections, punctuation)."""
    import hashlib
    return hashlib.sha256((formula_fingerprint(q) + "|" + text_structure.signature(q)).encode("utf-8")).hexdigest()[:24]


def apply_source_line_breaks(q: "QuestionAnalysis") -> None:
    """Reproduce the SOURCE line layout: line breaks are transferred from the source's visual lines to the stem and to
    every subpart (only where the word alignment is reliable)."""
    lines = (q.text_structure_source or {}).get("lines") or []
    if not lines:
        return
    q.text = text_structure.transfer_line_breaks(q.text, lines)
    for sec in q.sections:
        sec.text = text_structure.transfer_line_breaks(sec.text, lines)


def mark_teacher_verified(q: "QuestionAnalysis") -> None:
    """The teacher confirmed THIS content; a later math or structure edit voids the confirmation."""
    q.teacher_verified = True
    q.teacher_verified_fp = verification_fingerprint(q)


def pass2_context(q: "QuestionAnalysis", fig: "FigureRef") -> str:
    """PASS 2 context = RECONSTRUCTION semantics, not raw text: givens and definitions of the stem and of the subparts
    relevant to this figure (a figure bound to subpart X gets the subparts up to X; a stem figure gets all of them).
    Goals ('חשבו', 'מצאו') and claims-to-prove ('הוכיחו כי') are EXCLUDED from the givens."""
    from diagram_engine.text_facts import clauses
    secs = q.sections
    if fig.section_id and any(s_.section_id == fig.section_id for s_ in secs):
        idx = [s_.section_id for s_ in secs].index(fig.section_id)
        secs = secs[:idx + 1]
    givens, defs = [], []
    for label, text in [("", q.text)] + [(s_.section_id, s_.text) for s_ in secs]:
        for kind, cl in clauses(text):
            line = f"- {'[' + label + '] ' if label else ''}{cl}"
            if kind == "GIVEN":
                givens.append(line)
            elif kind == "DEFINITION":
                defs.append(line)
    return ("RECONSTRUCTION GIVENS (from the question; each MUST hold in the figure):\n" + ("\n".join(givens) or "- (none)") +
            "\nDEFINITIONS / NOTATION:\n" + ("\n".join(defs) or "- (none)") +
            "\nQUESTION TEXT (symbol names only - goals and statements to prove are NOT givens):\n" + (q.text or "")[:1500])


def extract_diagrams_pass2(service: "GeminiService", q: QuestionAnalysis, question: dict[str, Any]) -> None:
    """PASS 2: one SEPARATE call per figure on a high-resolution ROI cropped from the full-resolution master
    (never from an upscaled preview). Native structured output (AIDiagramSpec); invalid -> SCHEMA_VALIDATION_FAILED."""
    from google.genai import types

    images, masters = question.get("images", []), question.get("masters")
    for fig in q.figures:
        roi = figure_source_crop(fig, images, masters)
        meta = {"provider": "Gemini/Diagram/Pass2", "model": service.model, "roi_hash": image_digest(roi or b""),
                "roi_from_master": bool(masters), "status": "PENDING"}
        if roi is None:
            meta["status"] = "NO_ROI"
            q.diagram_pass[fig.figure_id] = meta
            continue
        started = time.monotonic()
        try:
            parts = [types.Part.from_text(text=pass2_context(q, fig)),
                     types.Part.from_bytes(data=roi, mime_type="image/png")]
            ai = service.generate(parts, AIDiagramSpec, DIAGRAM_SYSTEM_PROMPT, thinking_level="high")
            q.diagram_specs[fig.figure_id] = ai_to_spec(ai)
            meta.update(status="OK", raw=ai.model_dump() if hasattr(ai, "model_dump") else None)
        except Exception as exc:  # the question survives; the figure goes to the teacher
            meta.update(status="SCHEMA_VALIDATION_FAILED" if "validation" in str(exc).lower() else "FAILED",
                        error=f"{type(exc).__name__}")
        meta["latency_s"] = round(time.monotonic() - started, 3)
        q.diagram_pass[fig.figure_id] = meta


def attach_diagrams(q: QuestionAnalysis, images: list[bytes], ai_model: str = "", allow_auto: bool = False,
                    masters: list[bytes] | None = None, provenance: list[dict] | None = None) -> None:
    # allow_auto: kept for API compatibility with 5.4 and ignored - nothing is ever approved without a teacher.
    """Run the deterministic diagram engine for every figure whose input changed.
    An unchanged figure keeps its record (including teacher edits and approval)."""
    text = question_text_for_diagrams(q)
    new: dict[str, DiagramRecord] = {}
    for fig in q.figures:
        prior = q.diagrams.get(fig.figure_id)
        key = _diagram_input_key(fig, images, q.diagram_specs.get(fig.figure_id)) + ("|m:" + image_digest(masters[fig.source_image_index - 1])[:16]
                                                   if masters and 0 <= fig.source_image_index - 1 < len(masters) and masters[fig.source_image_index - 1] else "")
        if prior is not None and prior.audit.get("input_key") == key and prior.audit.get("question_text") == text:
            new[fig.figure_id] = prior
            continue
        idx = fig.source_image_index - 1
        edited_hash = image_digest(images[idx]) if 0 <= idx < len(images) else ""
        prov = (provenance or [{}] * len(images))[idx] if 0 <= idx < len(provenance or []) else {}
        hashes = {"edited_image_hash": edited_hash, "master_hash": prov.get("master_hash", ""),
                  "master_edited_hash": prov.get("master_edited_hash", ""), "ops_hash": prov.get("ops_hash", ""),
                  "vision_input_hash": q.analysis_input_hashes[idx] if 0 <= idx < len(q.analysis_input_hashes) else edited_hash,
                  "analysis_input_hash": q.analysis_input_hashes[idx] if 0 <= idx < len(q.analysis_input_hashes) else edited_hash}
        ai_spec = q.diagram_specs.get(fig.figure_id)
        # a cube-structure drawing is read from its plate corners: never cut them (the reader picks the main drawing)
        crop_fig = padded(fig, 0.08) if (ai_spec is not None and ai_spec.spatial is not None and ai_spec.spatial.voxel is not None) else fig
        rec = diagram_engine.process(
            fig.figure_id, "" if ai_spec is not None else fig.spec_json, text, figure_source_crop(crop_fig, images, masters),
            ai_spec=ai_spec, figure_type_hint=fig.figure_type,
            fallback_confidence=fig.rebuild_confidence, ai_model=ai_model,
            prior_review=prior.review if prior else None,
            required_text=reconstruction_text(q, fig, {l.text for l in ai_spec.labels} if ai_spec is not None else None),
            input_key=key, input_hashes=hashes)
        if prov and prov.get("working_hash") and prov["working_hash"] != edited_hash:
            hashes["vision_input_hash"] = "provenance-mismatch"
        if hashes["vision_input_hash"] != hashes["edited_image_hash"]:
            # the AI analysed a different image than the one the figure is being built from
            rec.decision.action = "original"
            rec.decision.reasons = ["PIPELINE_INTEGRITY_ERROR: התמונה שנותחה אינה התמונה הערוכה הנוכחית — יש לנתח מחדש."]
            rec.teacher_message = "התמונה נערכה אחרי הניתוח. יש להריץ ניתוח מחדש לשאלה זו לפני אישור התרשים."
            rec.review.status, rec.review.fingerprint = "pending", ""
            rec.audit["integrity_error"] = hashes
        rec.audit["input_key"], rec.audit["question_text"] = key, text
        if rec.review.status != "approved":
            diagram_engine.auto_approve_if_proven(rec)          # only a reconstruction PROVEN from the drawing itself
        new[fig.figure_id] = rec
    q.diagrams = new


STRICTNESS = diagram_engine.constants.DEFAULT_STRICTNESS


def figure_decision_pending(record: DiagramRecord | None) -> bool:
    """EXAM_QUALITY: a figure needs a teacher decision unless its reconstruction is approved or an explicit raster
    override is recorded (both bound to the current fingerprint)."""
    return not (diagram_engine.usable_in_document(record) or diagram_engine.raster_allowed(record))


def figure_bytes_for_document(fig: FigureRef, source_images: list[bytes], record: DiagramRecord | None = None,
                              strictness: str | None = None, masters: list[bytes] | None = None) -> tuple[bytes | None, str | None, bool]:
    """Returns (png, warning, is_rebuilt). The reconstruction is used ONLY if it is approved for this exact source.
    EXAM_QUALITY: the original raster only after an explicit, audited teacher override - never automatically."""
    strict = (strictness or STRICTNESS) == diagram_engine.constants.ReconstructionStrictness.EXAM_QUALITY
    if strict and not diagram_engine.usable_in_document(record):
        if diagram_engine.raster_allowed(record):
            crop = figure_source_crop(fig, source_images, masters)
            return crop, ("שולבה הסריקה המקורית באישור חריג של המורה" if crop else "תמונת המקור לא נמצאה"), False
        return None, "התרשים ממתין להחלטת מורה — לא שולב במסמך (EXAM_QUALITY)", False
    if diagram_engine.usable_in_document(record):
        try:
            _, png, _ = diagram_engine.render_spec(record.spec)
            return png, None, True
        except Exception as exc:  # never break the document - and never slip the original scan in
            if strict:
                return None, f"EXPORT_BLOCKED: יצירת השרטוט המאושר נכשלה ({type(exc).__name__}) — נדרשת החלטת מורה", False
            crop = figure_source_crop(fig, source_images)
            return crop, f"שחזור השרטוט נכשל ({type(exc).__name__}) — מצב LEGACY: שולב המקור", False
    crop = figure_source_crop(fig, source_images)
    return crop, (None if crop is not None else "תמונת המקור לא נמצאה"), False


def figure_render_ok(record: DiagramRecord | None) -> bool:
    """An approved reconstruction must actually render (validated before export)."""
    try:
        diagram_engine.render_spec(record.spec)
        return True
    except Exception:
        return False


def figure_svg_for_document(record: DiagramRecord | None) -> bytes | None:
    """Vector SVG of an APPROVED reconstruction (primary figure format in Word/PDF)."""
    if not diagram_engine.usable_in_document(record):
        return None
    try:
        svg, _, _ = diagram_engine.render_spec(record.spec)
        return svg.encode("utf-8")
    except Exception:
        return None


SVG_EXT_URI = "{96DAC541-7B7A-43D3-8B79-37D633B846F1}"
SVG_NS = "http://schemas.microsoft.com/office/drawing/2016/SVG/main"


def embed_svg_in_picture(document, inline_shape, svg: bytes) -> str:
    """Attach the SVG to an inline picture as its primary vector image (Office 2016+ svgBlip). The PNG added by python-docx
    stays as the compatibility fallback. Returns the relationship id of the SVG part."""
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.opc.packuri import PackURI
    from docx.opc.part import Part
    from docx.oxml.ns import qn
    from lxml import etree

    part = document.part
    existing = {str(p.partname) for p in part.package.iter_parts()}
    n = 1
    while f"/word/media/vector{n}.svg" in existing:
        n += 1
    svg_part = Part(PackURI(f"/word/media/vector{n}.svg"), "image/svg+xml", svg, part.package)
    rid = part.relate_to(svg_part, RT.IMAGE)
    blip = inline_shape._inline.xpath(".//a:blip")[0]
    ext_lst = blip.find(qn("a:extLst"))
    if ext_lst is None:
        ext_lst = etree.SubElement(blip, qn("a:extLst"))
    ext = etree.SubElement(ext_lst, qn("a:ext"))
    ext.set("uri", SVG_EXT_URI)
    svg_blip = etree.SubElement(ext, f"{{{SVG_NS}}}svgBlip", nsmap={"asvg": SVG_NS})
    svg_blip.set(qn("r:embed"), rid)
    return rid


# ============================================================
# 7. Word generation (schema-ordered OOXML, correct RTL)
# ============================================================
RPR_ORDER = [
    "w:rStyle", "w:rFonts", "w:b", "w:bCs", "w:i", "w:iCs", "w:caps", "w:smallCaps", "w:strike", "w:dstrike",
    "w:outline", "w:shadow", "w:emboss", "w:imprint", "w:noProof", "w:snapToGrid", "w:vanish", "w:webHidden",
    "w:color", "w:spacing", "w:w", "w:kern", "w:position", "w:sz", "w:szCs", "w:highlight", "w:u", "w:effect",
    "w:bdr", "w:shd", "w:fitText", "w:vertAlign", "w:rtl", "w:cs", "w:em", "w:lang", "w:eastAsianLayout",
    "w:specVanish", "w:oMath",
]
PPR_ORDER = [
    "w:pStyle", "w:keepNext", "w:keepLines", "w:pageBreakBefore", "w:framePr", "w:widowControl", "w:numPr",
    "w:suppressLineNumbers", "w:pBdr", "w:shd", "w:tabs", "w:suppressAutoHyphens", "w:kinsoku", "w:wordWrap",
    "w:overflowPunct", "w:topLinePunct", "w:autoSpaceDE", "w:autoSpaceDN", "w:bidi", "w:adjustRightInd",
    "w:snapToGrid", "w:spacing", "w:ind", "w:contextualSpacing", "w:mirrorIndents", "w:suppressOverlap", "w:jc",
    "w:textDirection", "w:textAlignment", "w:textboxTightWrap", "w:outlineLvl", "w:divId", "w:cnfStyle", "w:rPr",
    "w:sectPr", "w:pPrChange",
]
TBLPR_ORDER = [
    "w:tblStyle", "w:tblpPr", "w:tblOverlap", "w:bidiVisual", "w:tblStyleRowBandSize", "w:tblStyleColBandSize",
    "w:tblW", "w:jc", "w:tblCellSpacing", "w:tblInd", "w:tblBorders", "w:shd", "w:tblLayout", "w:tblCellMar",
    "w:tblLook", "w:tblCaption", "w:tblDescription",
]
TCPR_ORDER = [
    "w:cnfStyle", "w:tcW", "w:gridSpan", "w:hMerge", "w:vMerge", "w:tcBorders", "w:shd", "w:noWrap", "w:tcMar",
    "w:textDirection", "w:tcFitText", "w:vAlign", "w:hideMark",
]
SECTPR_ORDER = [
    "w:headerReference", "w:footerReference", "w:footnotePr", "w:endnotePr", "w:type", "w:pgSz", "w:pgMar",
    "w:paperSrc", "w:pgBorders", "w:lnNumType", "w:pgNumType", "w:cols", "w:formProt", "w:vAlign", "w:noEndnote",
    "w:titlePg", "w:textDirection", "w:bidi", "w:rtlGutter", "w:docGrid", "w:printerSettings", "w:sectPrChange",
]


def set_ordered(parent, tag: str, order: list[str], attrs: dict[str, str] | None = None):
    """Get-or-create child `tag` at its schema-correct position inside `parent`."""
    el = parent.find(qn(tag))
    if el is None:
        el = OxmlElement(tag)
        successors = {qn(t) for t in order[order.index(tag) + 1:]}
        for child in parent:
            if child.tag in successors:
                child.addprevious(el)
                break
        else:
            parent.append(el)
    for key, value in (attrs or {}).items():
        el.set(qn(key), value)
    return el


def remove_child(parent, tag: str) -> None:
    el = parent.find(qn(tag))
    if el is not None:
        parent.remove(el)


class DocContext:
    def __init__(self, language: str):
        self.language = language
        self.rtl = language in RTL_LANGUAGES
        self.bidi_lang = BIDI_LANG.get(language, "he-IL")
        self.warnings: list[str] = []
        self.scale = 1.0                   # < 1 when the source line layout needs a slightly smaller font to fit


def style_run(run, ctx: DocContext, bold: bool = False, size: float = 11, color: RGBColor | None = None) -> None:
    size = round(size * getattr(ctx, "scale", 1.0) * 2) / 2
    r_pr = run._r.get_or_add_rPr()
    set_ordered(r_pr, "w:rFonts", RPR_ORDER, {"w:ascii": BODY_FONT, "w:hAnsi": BODY_FONT, "w:eastAsia": BODY_FONT, "w:cs": BODY_FONT})
    for tag in ("w:b", "w:bCs"):
        if bold:
            set_ordered(r_pr, tag, RPR_ORDER)
        else:
            remove_child(r_pr, tag)
    if color is not None:
        run.font.color.rgb = color
    half_points = str(int(round(size * 2)))
    set_ordered(r_pr, "w:sz", RPR_ORDER, {"w:val": half_points})
    set_ordered(r_pr, "w:szCs", RPR_ORDER, {"w:val": half_points})  # Hebrew/Arabic size comes from szCs
    if has_rtl(run.text):
        set_ordered(r_pr, "w:rtl", RPR_ORDER)
    set_ordered(r_pr, "w:lang", RPR_ORDER, {"w:val": "en-US", "w:bidi": ctx.bidi_lang})


def set_paragraph(paragraph, ctx: DocContext, align: str = "start", rtl: bool | None = None,
                  space_after: float = 4, keep_next: bool = False) -> None:
    """align: start | center | end. In RTL paragraphs 'start' = right; we omit jc so Word and LibreOffice agree."""
    rtl = ctx.rtl if rtl is None else rtl
    p_pr = paragraph._p.get_or_add_pPr()
    if rtl:
        remove_child(p_pr, "w:bidi")  # drop any w:val="0" left from an earlier call
        set_ordered(p_pr, "w:bidi", PPR_ORDER)
    elif ctx.rtl:
        # The Normal style is RTL in Hebrew/Arabic documents, so an LTR paragraph must say so explicitly.
        set_ordered(p_pr, "w:bidi", PPR_ORDER, {"w:val": "0"})
    else:
        remove_child(p_pr, "w:bidi")
    if keep_next:
        set_ordered(p_pr, "w:keepNext", PPR_ORDER)
    set_ordered(p_pr, "w:spacing", PPR_ORDER, {"w:after": str(int(space_after * 20)), "w:line": "276", "w:lineRule": "auto"})
    remove_child(p_pr, "w:jc")
    if align == "center":
        set_ordered(p_pr, "w:jc", PPR_ORDER, {"w:val": "center"})
    elif align == "end":
        # For bidi paragraphs Word treats left/right as start/end.
        set_ordered(p_pr, "w:jc", PPR_ORDER, {"w:val": "left" if rtl else "right"})
    elif not rtl:
        set_ordered(p_pr, "w:jc", PPR_ORDER, {"w:val": "left"})


def add_text(paragraph, text: str, ctx: DocContext, bold: bool = False, size: float = 11, color: RGBColor | None = None) -> None:
    if not text:
        return
    for idx, line in enumerate(text.split("\n")):
        if idx:
            paragraph.add_run().add_break()
        if line:
            run = paragraph.add_run(line)
            style_run(run, ctx, bold=bold, size=size, color=color)


MATH_PATTERN = re.compile(r"(\$\$.+?\$\$|\$(?!\$)(?:\\\$|[^$])+?\$|\\\[.+?\\\]|\\\(.+?\\\))", re.DOTALL)


def unwrap_math(token: str) -> tuple[str, bool]:
    if token.startswith("$$"):
        return token[2:-2], True
    if token.startswith("\\["):
        return token[2:-2], True
    if token.startswith("\\("):
        return token[2:-2], False
    return token[1:-1], False


_LATEX_PREFIX_FIXES = [  # constructs mathml2omml converts incorrectly -> equivalent ones it handles
    (re.compile(r"\\(?:vec|overrightarrow)\s*\{"), r"\\overset{\\rightarrow}{"),
    (re.compile(r"\\vec\s*([A-Za-z])"), r"\\overset{\\rightarrow}{\1}"),
    (re.compile(r"\\bar\s*\{"), r"\\overline{"),
    (re.compile(r"\\[td]frac"), r"\\frac"),
]


def _repair_omml(root) -> None:
    """mathml2omml emits <m:rad> without the mandatory <m:deg>; Word's schema requires radPr?, deg, e."""
    m = "http://schemas.openxmlformats.org/officeDocument/2006/math"
    # <m:box> wrappers (from MathML <mrow>) make LibreOffice drop the whole equation. They carry no
    # meaning here, so unwrap them: move the children of box/e into the box's place.
    for box in list(root.iter(f"{{{m}}}box")):
        parent = box.getparent()
        if parent is None:
            continue
        inner = box.find(f"{{{m}}}e")
        pos = parent.index(box)
        for child in list(inner) if inner is not None else []:
            parent.insert(pos, child)
            pos += 1
        parent.remove(box)
    for rad in root.iter(f"{{{m}}}rad"):
        if rad.find(f"{{{m}}}deg") is None:
            rad_pr = rad.find(f"{{{m}}}radPr")
            if rad_pr is None:
                rad_pr = OxmlElement("m:radPr")
                rad.insert(0, rad_pr)
            if rad_pr.find(f"{{{m}}}degHide") is None:
                hide = OxmlElement("m:degHide")
                hide.set(qn("m:val"), "1")
                rad_pr.append(hide)
            rad_pr.addnext(OxmlElement("m:deg"))


def latex_to_omml(latex: str):
    latex = latex.strip()
    for pattern, repl in _LATEX_PREFIX_FIXES:
        latex = pattern.sub(repl, latex)
    mathml = latex2mathml.converter.convert(latex)
    omml = mathml2omml.convert(mathml, html.entities.name2codepoint)
    if "xmlns:m=" not in omml:
        omml = omml.replace("<m:oMath>", f"<m:oMath {nsdecls('m')}>", 1)
    root = parse_xml(omml)
    _repair_omml(root)
    _native_accents(root)
    _abs_delimiters(root)
    _operator_only_scripts(root)
    return root


def _operator_only_scripts(root) -> None:
    """A superscript/subscript that is ONLY an operator (0^{+}, x_{-}, a^{\\pm}) is a symbol, not an operation:
    mark the run as normal text (m:nor) - LibreOffice otherwise reads it as '+' with missing operands ('¿ ¿+')."""
    from lxml import etree
    M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
    q = lambda t: f"{{{M}}}{t}"  # noqa: E731
    for tag in ("sup", "sub"):
        for node in root.iter(q(tag)):
            kids = list(node)
            if len(kids) != 1 or kids[0].tag != q("r"):
                continue
            txt = "".join(t.text or "" for t in kids[0].iter(q("t"))).strip()
            if txt in ("+", "-", "−", "±", "∓", "*", "′", "″"):
                rpr = kids[0].find(q("rPr"))
                if rpr is None:
                    rpr = etree.Element(q("rPr"))
                    kids[0].insert(0, rpr)
                # schema CT_RPR: lit?, (nor | (scr?, sty?)), brk?, aln?  -> nor REPLACES scr/sty and follows lit
                for el in rpr.findall(q("sty")) + rpr.findall(q("scr")):
                    rpr.remove(el)
                if rpr.find(q("nor")) is None:
                    lit = rpr.find(q("lit"))
                    rpr.insert(0 if lit is None else list(rpr).index(lit) + 1, etree.Element(q("nor")))


def _abs_delimiters(root) -> None:
    """Lone '|' / '‖' runs -> a native Word delimiter m:d (begChr/endChr). A bare bar is read as an operator by some
    OMML consumers (LibreOffice turned |x| into '¿x∨¿' in exported PDFs)."""
    from lxml import etree
    M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
    q = lambda t: f"{{{M}}}{t}"  # noqa: E731

    def bar_of(el):
        if el.tag != q("r"):
            return None
        txt = "".join(t.text or "" for t in el.iter(q("t"))).strip()
        return txt if txt in ("|", "‖") else None          # '∣' is \mid (P(A∣B)) - a relation, never a delimiter
    def sup_bar(el):
        """m:sSup / m:sSubSup whose BASE is a lone bar run: a closing bar carrying an exponent (|FE|^2)."""
        if el.tag not in (q("sSup"), q("sSubSup")):
            return None
        base = el.find(q("e"))
        kids_ = list(base) if base is not None else []
        return bar_of(kids_[0]) if len(kids_) == 1 else None
    containers = [el for el in root.iter() if el.tag in (q("oMath"), q("e"), q("num"), q("den"), q("sup"), q("sub"), q("deg"), q("lim"))]
    for parent in containers:
        kids = list(parent)
        for j, k in enumerate(kids):
            ch = sup_bar(k)
            if not ch:
                continue
            opens = [i for i in range(j) if bar_of(kids[i]) == ch]
            if len(opens) % 2 == 1:                              # an unpaired opening bar before it
                a = opens[-1]
                d = etree.Element(q("d"))
                pr = etree.SubElement(d, q("dPr"))
                etree.SubElement(pr, q("begChr")).set(q("val"), ch)
                etree.SubElement(pr, q("endChr")).set(q("val"), ch)
                e = etree.SubElement(d, q("e"))
                for x in kids[a + 1:j]:
                    e.append(x)
                parent.remove(kids[a])
                base = k.find(q("e"))
                for x in list(base):
                    base.remove(x)
                base.append(d)
                break
    for parent in containers:
        changed = True
        while changed:
            changed = False
            kids = list(parent)
            bars = [i for i, k in enumerate(kids) if bar_of(k)]
            for a, b in zip(bars[::2], bars[1::2]):
                if bar_of(kids[a]) != bar_of(kids[b]) or b == a + 1:
                    continue
                ch = bar_of(kids[a])
                d = etree.Element(q("d"))
                pr = etree.SubElement(d, q("dPr"))
                etree.SubElement(pr, q("begChr")).set(q("val"), "|" if ch == "∣" else ch)
                etree.SubElement(pr, q("endChr")).set(q("val"), "|" if ch == "∣" else ch)
                e = etree.SubElement(d, q("e"))
                for k in kids[a + 1:b]:
                    e.append(k)
                parent.insert(parent.index(kids[a]), d)
                parent.remove(kids[a])
                parent.remove(kids[b])
                changed = True
                break


_ARROWS = {"→": "\u20d7", "⃗": "\u20d7", "←": "\u20d6", "↔": "\u20e1"}
_BARS = {"―", "_", "‾", "¯", "‗", "—", "−"}


def _native_accents(root) -> None:
    """mathml2omml emits \\overrightarrow / \\underline / \\overline as limUpp / limLow (a small centred character).
    Word's native forms stretch over the WHOLE base: m:acc (vector arrow) and m:bar (over/under line)."""
    from lxml import etree
    M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
    q = lambda t: f"{{{M}}}{t}"  # noqa: E731
    for tag in ("limUpp", "limLow"):
        for node in list(root.iter(q(tag))):
            lim, base = node.find(q("lim")), node.find(q("e"))
            if lim is None or base is None:
                continue
            txt = "".join(t.text or "" for t in lim.iter(q("t"))).strip()
            if tag == "limUpp" and txt in _ARROWS:
                new = etree.Element(q("acc"))
                pr = etree.SubElement(new, q("accPr"))
                etree.SubElement(pr, q("chr")).set(q("val"), _ARROWS[txt])
            elif txt in _BARS:
                new = etree.Element(q("bar"))
                pr = etree.SubElement(new, q("barPr"))
                etree.SubElement(pr, q("pos")).set(q("val"), "top" if tag == "limUpp" else "bot")
            else:
                continue
            new.append(base)
            node.getparent().replace(node, new)


def add_mixed(paragraph, text: str, ctx: DocContext, context: str, bold: bool = False, size: float = 11) -> None:
    """Plain text + $LaTeX$ → runs + native Word equations (OMML)."""
    text = text or ""
    stripped = text.strip()
    if stripped.startswith("$$") and stripped.endswith("$$") and stripped.count("$$") == 2 and not paragraph.runs:
        p_pr = paragraph._p.get_or_add_pPr()
        remove_child(p_pr, "w:jc")
        set_ordered(p_pr, "w:jc", PPR_ORDER, {"w:val": "center"})
        text = "$" + stripped[2:-2] + "$"
    cursor = 0
    for match in MATH_PATTERN.finditer(text):
        add_text(paragraph, text[cursor:match.start()], ctx, bold=bold, size=size)
        latex, display = unwrap_math(match.group(0))
        if display and paragraph.runs:
            paragraph.add_run().add_break()
        try:
            paragraph._p.append(latex_to_omml(latex))
        except Exception as exc:
            run = paragraph.add_run(f"[{latex}]")
            style_run(run, ctx, size=size)
            ctx.warnings.append(f"{context}: הנוסחה '{latex}' לא הומרה למשוואת Word ({exc}); נשמרה כטקסט.")
        if display and match.end() < len(text.rstrip()):
            paragraph.add_run().add_break()
        cursor = match.end()
    add_text(paragraph, text[cursor:], ctx, bold=bold, size=size)


def new_paragraph(container, ctx: DocContext, **kwargs):
    p = container.add_paragraph()
    set_paragraph(p, ctx, **kwargs)
    return p


def set_table_layout(table, ctx: DocContext, widths_in: list[float], borders: bool) -> None:
    tbl_pr = table._tbl.tblPr
    if ctx.rtl:
        set_ordered(tbl_pr, "w:bidiVisual", TBLPR_ORDER)
    total = sum(widths_in)
    set_ordered(tbl_pr, "w:tblW", TBLPR_ORDER, {"w:w": str(int(total * 1440)), "w:type": "dxa"})
    set_ordered(tbl_pr, "w:jc", TBLPR_ORDER, {"w:val": "center"})
    set_ordered(tbl_pr, "w:tblLayout", TBLPR_ORDER, {"w:type": "fixed"})
    if borders:
        b = set_ordered(tbl_pr, "w:tblBorders", TBLPR_ORDER)
        for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
            el = b.find(qn(f"w:{edge}"))
            if el is None:
                el = OxmlElement(f"w:{edge}")
                b.append(el)
            el.set(qn("w:val"), "single")
            el.set(qn("w:sz"), "6")
            el.set(qn("w:space"), "0")
            el.set(qn("w:color"), "8C8C8C")
    for i, col in enumerate(table.columns):
        col.width = Inches(widths_in[i])
    for row in table.rows:
        for i, cell in enumerate(row.cells):
            tc_pr = cell._tc.get_or_add_tcPr()
            set_ordered(tc_pr, "w:tcW", TCPR_ORDER, {"w:w": str(int(widths_in[i] * 1440)), "w:type": "dxa"})


def shade_cell(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    set_ordered(tc_pr, "w:shd", TCPR_ORDER, {"w:val": "clear", "w:color": "auto", "w:fill": fill})


def fill_cell(cell, text: str, ctx: DocContext, context: str, bold: bool = False, size: float = 9.5, align: str = "start") -> None:
    cell.text = ""
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
    lines = (text or "").split("\n")
    for idx, line in enumerate(lines):
        p = cell.paragraphs[0] if idx == 0 else cell.add_paragraph()
        set_paragraph(p, ctx, align=align, space_after=2)
        add_mixed(p, line, ctx, context, bold=bold, size=size)


def add_field(paragraph, instr: str, ctx: DocContext, size: float = 9) -> None:
    def fld(kind: str):
        run = paragraph.add_run()
        el = OxmlElement("w:fldChar")
        el.set(qn("w:fldCharType"), kind)
        run._r.append(el)
        return run

    fld("begin")
    r = paragraph.add_run()
    instr_el = OxmlElement("w:instrText")
    instr_el.set(qn("xml:space"), "preserve")
    instr_el.text = f" {instr} "
    r._r.append(instr_el)
    fld("separate")
    placeholder = paragraph.add_run("1")
    style_run(placeholder, ctx, size=size)
    fld("end")


def setup_document(ctx: DocContext) -> docx.Document:
    doc = docx.Document()
    for section in doc.sections:
        section.page_width = Inches(8.27)   # A4
        section.page_height = Inches(11.69)
        for side in ("top_margin", "bottom_margin", "left_margin", "right_margin"):
            wide = getattr(ctx, "keep_lines", False) and side in ("left_margin", "right_margin")
            setattr(section, side, Inches(SOURCE_LAYOUT_MARGIN_IN if wide else 0.7))
        section.footer_distance = Inches(0.35)
        if ctx.rtl:
            set_ordered(section._sectPr, "w:bidi", SECTPR_ORDER)
    zoom = doc.settings.element.find(qn("w:zoom"))
    if zoom is not None and zoom.get(qn("w:percent")) is None:
        zoom.set(qn("w:percent"), "100")  # python-docx template omits this required attribute
    normal = doc.styles["Normal"]
    normal.font.name = BODY_FONT
    normal.font.size = Pt(11)
    r_pr = normal.element.get_or_add_rPr()
    set_ordered(r_pr, "w:rFonts", RPR_ORDER, {"w:ascii": BODY_FONT, "w:hAnsi": BODY_FONT, "w:eastAsia": BODY_FONT, "w:cs": BODY_FONT})
    set_ordered(r_pr, "w:szCs", RPR_ORDER, {"w:val": "22"})
    set_ordered(r_pr, "w:lang", RPR_ORDER, {"w:val": "en-US", "w:bidi": ctx.bidi_lang})
    if ctx.rtl:
        p_pr = normal.element.get_or_add_pPr()
        set_ordered(p_pr, "w:bidi", PPR_ORDER)
    return doc


def add_footer(doc: docx.Document, ctx: DocContext, labels: DocumentLabels, title: str) -> None:
    footer = doc.sections[0].footer
    p = footer.paragraphs[0]
    set_paragraph(p, ctx, align="center", space_after=0)
    add_text(p, f"{title} | {labels.page} ", ctx, size=9, color=RGBColor(110, 110, 110))
    add_field(p, "PAGE", ctx)
    add_text(p, f" {labels.of} ", ctx, size=9, color=RGBColor(110, 110, 110))
    add_field(p, "NUMPAGES", ctx)


def format_exam_date(value: str) -> str:
    try:
        return date.fromisoformat(str(value)).strftime("%d/%m/%Y")
    except Exception:
        return str(value or "")


def add_header_block(doc, meta: dict[str, Any], exam: ExamAnalysis, ctx: DocContext, title: str) -> None:
    labels = exam.labels
    logo = meta.get("logo_bytes")
    widths = [5.27, 1.6] if logo else [6.87]
    table = doc.add_table(rows=1, cols=len(widths))
    set_table_layout(table, ctx, widths, borders=False)
    info = table.rows[0].cells[0]
    info.text = ""
    p = info.paragraphs[0]
    set_paragraph(p, ctx, space_after=2)
    school = str(meta.get("school_name", "")).strip()
    add_text(p, school, ctx, bold=True, size=15)
    p2 = info.add_paragraph()
    set_paragraph(p2, ctx, space_after=2)
    add_text(p2, exam.translated_exam_name, ctx, bold=True, size=13)
    details = [
        f"{labels.grade}: {exam.translated_grade}",
        f"{labels.level}: {exam.translated_level}",
        f"{labels.exam_date}: {format_exam_date(meta.get('date', ''))}",
    ]
    p3 = info.add_paragraph()
    set_paragraph(p3, ctx, space_after=2)
    add_text(p3, "   |   ".join(details), ctx, size=10)
    p4 = info.add_paragraph()
    set_paragraph(p4, ctx, space_after=2)
    teacher = str(meta.get("teacher_name", "")).strip()
    line4 = f"{labels.duration}: {meta.get('duration', '')} {labels.minutes}"
    if teacher:
        line4 += f"   |   {labels.teacher}: {teacher}"
    add_text(p4, line4, ctx, size=10)
    if logo:
        cell = table.rows[0].cells[1]
        cp = cell.paragraphs[0]
        set_paragraph(cp, ctx, align="center", space_after=0)
        try:
            cp.add_run().add_picture(io.BytesIO(logo), width=Inches(1.3))
        except Exception as exc:
            ctx.warnings.append(f"לא ניתן היה להוסיף את הלוגו: {exc}")
    # Title with a bottom rule (paragraph border, not a row of dashes).
    pt = new_paragraph(doc, ctx, align="center", space_after=8)
    p_pr = pt._p.get_or_add_pPr()
    bdr = set_ordered(p_pr, "w:pBdr", PPR_ORDER)
    bottom = OxmlElement("w:bottom")
    for k, v in {"w:val": "single", "w:sz": "8", "w:space": "4", "w:color": "1E88E5"}.items():
        bottom.set(qn(k), v)
    bdr.append(bottom)
    add_text(pt, title, ctx, bold=True, size=17, color=RGBColor(21, 101, 192))


def add_figures(doc, q: QuestionAnalysis, source: dict[str, Any], ctx: DocContext, labels: DocumentLabels,
                with_captions: bool, section: str | None = None) -> None:
    """section=None: every figure (legacy); section="": stem figures; section="ב": the figures bound to subpart ב."""
    images = source.get("images", [])
    known = {s_.section_id for s_ in q.sections}
    for idx, fig in enumerate(q.figures, 1):
        if section is not None:
            owner = fig.section_id if fig.section_id in known else ""
            if owner != section:
                continue
        rec = q.diagrams.get(fig.figure_id)
        if diagram_engine.usable_in_document(rec) and rec.spec.diagram_type == "table":
            try:
                add_native_table(doc, rec.spec.table, ctx)
                if with_captions:
                    cap = new_paragraph(doc, ctx, align="center", space_after=6)
                    add_mixed(cap, f"{labels.figure} {idx} (טבלה משוחזרת ואושרה): {fig.description}", ctx, f"כיתוב איור {idx}", size=9)
                continue
            except Exception as exc:  # fall back to the image path below
                ctx.warnings.append(f"שאלה {q.question_number}, טבלה {idx}: יצירת טבלה מקורית ב-Word נכשלה ({type(exc).__name__}) — שולבה הטבלה המשוחזרת כשרטוט וקטורי.")
                rec = None
        data, warn, rebuilt = figure_bytes_for_document(fig, images, rec, masters=source.get("masters"))
        if warn:
            ctx.warnings.append(f"שאלה {q.question_number}, תרשים {idx}: {warn}.")
        if data is None:
            # never a silent omission: a visible, unmistakable placeholder
            ph = new_paragraph(doc, ctx, align="center", space_after=6)
            add_mixed(ph, f"⚠ [{labels.figure} {idx}: {fig.description} — ממתין להחלטת מורה, לא שולב]", ctx, f"מציין מקום {idx}",
                      bold=True, size=10)
            continue
        with Image.open(io.BytesIO(data)) as im:
            px_w = im.width
        width = min(4.8, max(1.5, px_w / (430 if rebuilt else 160)))  # rebuilt PNGs are 300 dpi
        p = new_paragraph(doc, ctx, align="center", space_after=2, keep_next=with_captions)
        pic = p.add_run().add_picture(io.BytesIO(data), width=Inches(width))
        svg = figure_svg_for_document(rec) if rebuilt else None
        if svg:
            embed_svg_in_picture(doc, pic, svg)          # vector first, PNG only as fallback
        if with_captions:
            cap = new_paragraph(doc, ctx, align="center", space_after=6)
            kind = "שוחזר ואושר" if rebuilt else ("סריקה מקורית — אישור חריג" if diagram_engine.raster_allowed(rec) else "מקור")
            add_mixed(cap, f"{labels.figure} {idx} ({kind}): {fig.description}", ctx, f"כיתוב איור {idx}", size=9)
            if fig.geogebra_commands:
                geo = new_paragraph(doc, ctx, align="center", space_after=6, rtl=False)
                add_text(geo, "GeoGebra: " + " ; ".join(fig.geogebra_commands), ctx, size=8, color=RGBColor(90, 90, 90))


def add_native_table(doc, table_spec, ctx: DocContext) -> None:
    """Approved TableSpec -> real Word table (editable, sharp), RTL aware, header rows/columns in bold + shaded."""
    rows = table_spec.rows
    n_c = len(rows[0])
    width = min(6.3, max(2.0, 1.3 * n_c))
    table = doc.add_table(rows=len(rows), cols=n_c)
    set_table_layout(table, ctx, [width / n_c] * n_c, borders=True)
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            header = r < table_spec.header_rows or c < table_spec.header_columns
            fill_cell(table.rows[r].cells[c], cell.text, ctx, "טבלה משוחזרת", bold=header, size=9.5, align="center")
            if header:
                shade_cell(table.rows[r].cells[c], "F2F2F2")
            elif cell.fill:
                shade_cell(table.rows[r].cells[c], "808080")
    new_paragraph(doc, ctx, space_after=4)


# ------------------------------------------------------------------ pagination engine
PAGE_BODY_FALLBACK_IN = 9.4


def _body_len(doc) -> int:
    from docx.oxml.ns import qn
    return sum(1 for el in doc.element.body if el.tag != qn("w:sectPr"))


def _block_elements(doc, start: int, end: int) -> list:
    from docx.oxml.ns import qn
    els = [el for el in doc.element.body if el.tag != qn("w:sectPr")]
    return els[start:end]


def _estimate_height_in(elements) -> float:
    """Approximate rendered height (inches): text lines, pictures (extent), table rows, spacing."""
    from docx.oxml.ns import qn
    h = 0.0
    for el in elements:
        if el.tag == qn("w:tbl"):
            h += 0.32 * len(el.findall(qn("w:tr"))) + 0.1
            continue
        text = "".join(t.text or "" for t in el.iter(qn("w:t")))
        maths = len(el.findall(".//" + qn("m:oMath")))
        lines = max(1, -(-len(text) // 88)) + 0.4 * maths
        h += lines * 0.21 + 0.08
        for ext in el.iter("{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}extent"):
            h += int(ext.get("cy", "0")) / 914400 + 0.05
    return h


def _set_keep(el, keep_next: bool, keep_lines: bool = True, page_break_before: bool = False) -> None:
    from docx.oxml.ns import qn
    targets = [el] if el.tag == qn("w:p") else list(el.iter(qn("w:p")))
    if el.tag == qn("w:tbl"):
        for tr in el.findall(qn("w:tr")):                     # table rows never split
            tr_pr = tr.find(qn("w:trPr"))
            if tr_pr is None:
                tr_pr = tr.makeelement(qn("w:trPr"), {})
                tr.insert(0 if tr.find(qn("w:tblPrEx")) is None else 1, tr_pr)
            if tr_pr.find(qn("w:cantSplit")) is None:
                tr_pr.insert(0, tr_pr.makeelement(qn("w:cantSplit"), {}))
    for p in targets:
        p_pr = p.get_or_add_pPr()
        for tag, on in (("w:keepNext", keep_next), ("w:keepLines", keep_lines), ("w:pageBreakBefore", page_break_before)):
            existing = p_pr.find(qn(tag))
            if on and existing is None:
                set_ordered(p_pr, tag, PPR_ORDER)
            elif not on and existing is not None and tag != "w:keepLines":
                p_pr.remove(existing)


def paginate_questions(doc, blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every question is one pedagogical unit.
    - fits on a page: the whole block is chained (keepNext on all but the last paragraph, keepLines, rows cantSplit),
      so Word/LibreOffice move the WHOLE question to the next page instead of starting it at the bottom;
    - longer than a page: it starts on a fresh page and may break ONLY between subparts (semantic break points).
    Returns a small report (used by tests / QA)."""
    sec = doc.sections[0]
    body_in = ((int(sec.page_height) - int(sec.top_margin or 0) - int(sec.bottom_margin or 0)) / 914400
               if sec.page_height else PAGE_BODY_FALLBACK_IN)
    report = []
    for b in blocks:
        els = _block_elements(doc, b["start"], b["end"])
        if not els:
            continue
        height = _estimate_height_in(els)
        long_q = height > 0.92 * body_in
        cut = {bp - b["start"] for bp in b["breaks"]} if long_q else set()
        for i, el in enumerate(els):
            last = i == len(els) - 1
            _set_keep(el, keep_next=not last and (i + 1) not in cut)
        if long_q:
            _set_keep(els[0], keep_next=True, page_break_before=True)
        report.append({"start": b["start"], "height_in": round(height, 2), "long": long_q, "breaks": sorted(cut)})
    return report


def add_response_templates(doc, source: dict[str, Any], ctx: DocContext) -> int:
    """Student response areas from the source (answer boxes, empty grids, rows of boxes) as EMPTY native Word tables.
    They are never filled - understanding/solving the question never writes into a response area."""
    from docx.shared import Pt
    n = 0
    for t in (source.get("document") or {}).get("response_templates", []):
        rows, cols = (t.get("grid") or [1, 1])[:2]
        rows, cols = max(1, min(int(rows), 30)), max(1, min(int(cols), 30))
        x0, y0, x1, y1 = t["bbox"]
        table = doc.add_table(rows=rows, cols=cols)
        table.style = "Table Grid"
        cell_h = max(12.0, min(60.0, (y1 - y0) / rows))
        for r in table.rows:
            r.height = Pt(cell_h)
        new_paragraph(doc, ctx, space_after=4)
        n += 1
    return n


STUDENT_EXAM_PROFILE = {"show_question_points": False, "show_section_points": False, "show_subsection_points": False}
TEACHER_PROFILE = {"show_question_points": True, "show_section_points": True, "show_subsection_points": True}


def render_profile(doc_type: str, meta: dict[str, Any] | None = None) -> dict[str, bool]:
    """Student exam: no scoring metadata unless the teacher's template explicitly asks (meta['show_question_points'])."""
    if doc_type == "exam":
        prof = dict(STUDENT_EXAM_PROFILE)
        if meta and meta.get("show_question_points"):
            prof["show_question_points"] = True
        return prof
    return dict(TEACHER_PROFILE)


def question_heading(doc, q: QuestionAnalysis, ctx: DocContext, labels: DocumentLabels, show_topic: bool,
                     show_points: bool = True) -> None:
    p = new_paragraph(doc, ctx, space_after=6, keep_next=True)
    p.paragraph_format.space_before = Pt(14)
    text = f"{labels.question} {q.question_number}" + (f" ({fmt_points(q.points)} {labels.points})" if show_points else "")
    if show_topic and q.topic.strip():
        text += f" — {q.topic.strip()}"
    add_text(p, text, ctx, bold=True, size=13, color=RGBColor(21, 101, 192))


def add_structured_block(doc, tb, ctx: DocContext, context: str, keep_next: bool = False, indent: bool = False) -> None:
    """A TextBlock -> its own w:p (never a w:br hack, never spaces/tabs)."""
    p = new_paragraph(doc, ctx, space_after=6 if tb.block_type != "SUBSECTION" else 4, keep_next=keep_next)
    if tb.block_type == "SUBSECTION":
        # In a bidi paragraph w:left/w:right are LOGICAL (start = right side on screen). Hanging "(1)" marker.
        p.paragraph_format.left_indent = Inches(0.6)
        p.paragraph_format.first_line_indent = Inches(-0.3)
    elif indent:
        p.paragraph_format.left_indent = Inches(0.3)
    add_mixed(p, tb.text, ctx, context)


def student_choice_note(q: QuestionAnalysis) -> str:
    """'ענו על שלושה מארבעת הסעיפים א–ד.' - the rule without internal point values (not repeated when the stem already
    states the rule)."""
    if re.search(r"ענו על\s+\S+\s+מ", q.text or ""):
        return ""
    notes = []
    for gid, k in scoring.groups(q).items():
        opts = scoring.members(q, gid)
        if opts and k < len(opts):
            ids = [s_.section_id for s_ in q.sections]
            pos = [ids.index(o.section_id) for o in opts]
            contiguous = pos == list(range(pos[0], pos[0] + len(pos)))
            notes.append(text_structure.choice_sentence(k, len(opts), opts[0].section_id, opts[-1].section_id,
                                                        None if contiguous else [o.section_id for o in opts]))
    return " ".join(notes)


def section_label(sec_id: str, ctx: DocContext) -> str:
    return f"{sec_id}." if sec_id else ""


def create_word_document(exam: ExamAnalysis, meta: dict[str, Any], questions_data: list[dict[str, Any]],
                         doc_type: str, show_topic_in_exam: bool = False) -> tuple[bytes, list[str]]:
    ctx = DocContext(meta.get("language", "עברית"))
    ctx.keep_lines = bool(meta.get("preserve_source_lines", True)) and doc_type == "exam"
    labels = exam.labels
    title = {"exam": labels.exam_form, "solution": labels.solutions, "rubric": labels.rubric}[doc_type]
    doc = setup_document(ctx)
    add_header_block(doc, meta, exam, ctx, title)
    add_footer(doc, ctx, labels, f"{exam.translated_exam_name} — {title}")
    source_by_num = {int(q["question_number"]): q for q in questions_data}

    if doc_type == "exam":
        p = new_paragraph(doc, ctx, space_after=8)
        add_text(p, f"{labels.student_name}: ______________________      {labels.class_name}: ________", ctx, size=11)
        if exam.translated_instructions.strip():
            ph = new_paragraph(doc, ctx, space_after=2, keep_next=True)
            add_text(ph, labels.instructions + ":", ctx, bold=True, size=12)
            for line_no, line in enumerate(exam.translated_instructions.splitlines(), 1):
                if line.strip():
                    pl = new_paragraph(doc, ctx, space_after=1)
                    add_mixed(pl, line, ctx, f"הוראות, שורה {line_no}", size=10.5)

    q_blocks: list[dict[str, Any]] = []
    profile = render_profile(doc_type, meta)
    keep_lines = bool((meta or {}).get("preserve_source_lines", True))
    if keep_lines and doc_type == "exam":
        ctx.scale = fit_scale_for_source_lines(exam)
    for q in sorted(exam.questions, key=lambda x: x.question_number):
        source = source_by_num.get(q.question_number, {})
        block = {"start": _body_len(doc), "breaks": []}
        q_blocks.append(block)
        question_heading(doc, q, ctx, labels, show_topic=(doc_type != "exam" or show_topic_in_exam),
                         show_points=profile["show_question_points"])

        if doc_type == "exam":
            if q.text.strip():
                # TEXT STRUCTURE: one Word paragraph per logical block (soft wraps joined, hard breaks kept)
                for tb in text_structure.blocks(q.text, preserve_lines=keep_lines):
                    add_structured_block(doc, tb, ctx, f"שאלה {q.question_number}, גזע", keep_next=bool(q.figures))
            note = student_choice_note(q) if not profile["show_section_points"] else scoring.selection_note(q)
            if note:
                add_text(new_paragraph(doc, ctx, space_after=6), note, ctx, bold=True)
            add_figures(doc, q, source, ctx, labels, with_captions=False, section="")
            add_response_templates(doc, source, ctx)
            for si, sec in enumerate(q.sections):
                if si > 0:
                    block["breaks"].append(_body_len(doc))          # semantic break point: between subparts
                p = new_paragraph(doc, ctx, space_after=6)
                ind = p.paragraph_format
                ind.left_indent = Inches(0.0)
                ind.right_indent = Inches(0.0)
                ind.first_line_indent = None
                pts = f" ({fmt_points(sec.points)} {labels.points})" if profile["show_section_points"] else ""
                add_text(p, f"{section_label(sec.section_id, ctx)}{pts}  ", ctx, bold=True)
                sb = text_structure.blocks(sec.text, preserve_lines=keep_lines)
                p.paragraph_format.left_indent = Inches(0.3)            # bidi START side: continuation lines under the text
                p.paragraph_format.first_line_indent = Inches(-0.3)     # the label hangs
                if sb:
                    add_mixed(p, sb[0].text, ctx, f"שאלה {q.question_number}, סעיף {sec.section_id}")
                    for tb in sb[1:]:                       # subsections / further paragraphs = their own Word paragraphs
                        add_structured_block(doc, tb, ctx, f"שאלה {q.question_number}, סעיף {sec.section_id}", indent=True)
                add_figures(doc, q, source, ctx, labels, with_captions=False, section=sec.section_id)   # figure next to its subpart

        elif doc_type == "solution":
            if q.text.strip():
                for tb in text_structure.blocks(q.text):              # same TextBlock path as the student exam (no w:br)
                    add_mixed(new_paragraph(doc, ctx, space_after=4), tb.text, ctx, f"שאלה {q.question_number}, גזע", size=10)
            add_figures(doc, q, source, ctx, labels, with_captions=True, section="")
            sec_ids = [s.section_id for s in q.sections]
            groups: list[tuple[str, list[SolutionStep]]] = []
            general = [s for s in q.solution_steps if s.section_id not in sec_ids]
            if general:
                groups.append(("", general))
            for sid in sec_ids:
                steps = [s for s in q.solution_steps if s.section_id == sid]
                if steps:
                    groups.append((sid, steps))
            for gi, (sid, steps) in enumerate(groups):
                if gi > 0:
                    block["breaks"].append(_body_len(doc))
                if sid:
                    sec = next(s for s in q.sections if s.section_id == sid)
                    ph = new_paragraph(doc, ctx, space_after=2, keep_next=True)
                    add_text(ph, f"{labels.section} {sid} ({fmt_points(sec.points)} {labels.points})", ctx, bold=True, size=11.5)
                    add_figures(doc, q, source, ctx, labels, with_captions=True, section=sid)
                for idx, step in enumerate(steps, 1):
                    p = new_paragraph(doc, ctx, space_after=3)
                    if step.step_title.strip():
                        add_text(p, step.step_title.strip() + ": ", ctx, bold=True)
                    sblocks = text_structure.blocks(step.content)
                    add_mixed(p, sblocks[0].text if sblocks else step.content, ctx, f"שאלה {q.question_number}, פתרון {sid or ''} שלב {idx}")
                    for tb in sblocks[1:]:                      # further lines = their own paragraphs (no w:br)
                        add_structured_block(doc, tb, ctx, f"שאלה {q.question_number}, פתרון {sid or ''} שלב {idx}")
                    if step.final_answer.strip():
                        pa = new_paragraph(doc, ctx, space_after=6)
                        p_pr = pa._p.get_or_add_pPr()
                        set_ordered(p_pr, "w:shd", PPR_ORDER, {"w:val": "clear", "w:color": "auto", "w:fill": "E8F5E9"})
                        add_text(pa, labels.final_answer + ": ", ctx, bold=True, color=RGBColor(27, 94, 32))
                        fblocks = text_structure.blocks(step.final_answer)
                        add_mixed(pa, fblocks[0].text if fblocks else step.final_answer, ctx, f"שאלה {q.question_number}, תשובה סופית", bold=True)
                        for tb in fblocks[1:]:
                            add_structured_block(doc, tb, ctx, f"שאלה {q.question_number}, תשובה סופית")

        elif doc_type == "rubric":
            allocated = allocate_rubric_points(q.points, [r.percentage for r in q.rubric_steps])
            widths = [1.35, 0.8, 2.35, 1.2, 1.17]
            table = doc.add_table(rows=1, cols=5)
            headers = [labels.section_stage, labels.points, f"{labels.full_credit} / {labels.partial_credit} / {labels.zero_credit}",
                       labels.carried_error, labels.common_errors]
            for cell, text in zip(table.rows[0].cells, headers):
                fill_cell(cell, text, ctx, "כותרת מחוון", bold=True, size=9.5, align="center")
                shade_cell(cell, "DCE8F5")
            tr_pr = table.rows[0]._tr.get_or_add_trPr()
            tr_pr.append(OxmlElement("w:tblHeader"))
            for idx, rub in enumerate(q.rubric_steps):
                cells = table.add_row().cells
                stage = (f"{labels.section} {rub.section_id}: " if rub.section_id else "") + rub.stage_desc
                pts = f"{fmt_points(allocated[idx])}\n({rub.percentage:g}%)"
                criteria = (f"{labels.full_credit}: {rub.full_credit}\n{labels.partial_credit}: {rub.partial_credit}\n"
                            f"{labels.zero_credit}: {rub.zero_credit}")
                common = "\n".join(f"• {e.error} ({e.severity}; −{e.deduction_percent:g}%)" for e in rub.common_errors) or "—"
                values = [stage, pts, criteria, rub.carried_over_error_policy or "—", common]
                for col, value in enumerate(values):
                    fill_cell(cells[col], value, ctx, f"מחוון שאלה {q.question_number}, שלב {idx + 1}", size=9,
                              align="center" if col == 1 else "start")
            total_cells = table.add_row().cells
            fill_cell(total_cells[0], labels.total, ctx, "סיכום", bold=True, size=9.5)
            fill_cell(total_cells[1], fmt_points(sum(allocated, Decimal("0"))), ctx, "סיכום", bold=True, size=9.5, align="center")
            for c in total_cells:
                shade_cell(c, "F2F2F2")
            set_table_layout(table, ctx, widths, borders=True)
            new_paragraph(doc, ctx, space_after=4)

    for i, b in enumerate(q_blocks):
        b["end"] = q_blocks[i + 1]["start"] if i + 1 < len(q_blocks) else _body_len(doc)
    paginate_questions(doc, q_blocks)
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue(), ctx.warnings


# ============================================================
# 8. PDF conversion through LibreOffice
# ============================================================
_PDF_LOCK = threading.Lock()


def soffice_executable() -> str | None:
    return shutil.which("soffice") or shutil.which("libreoffice")


def docx_to_pdf_bytes(docx_bytes: bytes, stem: str = "document", timeout: int = 180) -> tuple[bytes | None, str]:
    exe = soffice_executable()
    if not exe:
        return None, "LibreOffice אינו מותקן בסביבה."
    with _PDF_LOCK, tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        src = tmp_path / f"{sanitize_filename(stem)}.docx"
        src.write_bytes(docx_bytes)
        profile = tmp_path / "lo_profile"  # private profile: no lock clashes between users
        env = os.environ.copy()
        env.setdefault("SAL_USE_VCLPLUGIN", "svp")
        env["HOME"] = str(tmp_path)
        cmd = [exe, f"-env:UserInstallation={profile.as_uri()}", "--headless", "--norestore", "--nolockcheck",
               "--convert-to", "pdf:writer_pdf_Export", "--outdir", str(tmp_path), str(src)]
        try:
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, env=env, check=False)
        except subprocess.TimeoutExpired:
            return None, "ההמרה ל-PDF חרגה מזמן ההמתנה."
        pdf = src.with_suffix(".pdf")
        if proc.returncode != 0 or not pdf.exists():
            return None, f"ההמרה ל-PDF נכשלה: {proc.stderr.decode(errors='ignore')[-400:]}"
        return pdf.read_bytes(), ""


def sanitize_filename(name: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", name or "").strip().strip(".")
    return cleaned[:80] or "document"


SOURCE_LAYOUT_MARGIN_IN = 0.6          # text column ~18 cm on A4, like the Bagrut / textbook source column
MIN_FIT_PT = 10.0


def fit_scale_for_source_lines(exam: "ExamAnalysis", body_pt: float = 11.0, margin_in: float = SOURCE_LAYOUT_MARGIN_IN) -> float:
    """Measure every forced source line with the real metrics of the body font (Arial metrics = Liberation Sans) and
    return the font scale (>= MIN_FIT_PT / body_pt) at which the longest line fits the text column: Word then keeps the
    source line layout instead of re-wrapping a line and leaving an orphan."""
    try:
        from PIL import ImageFont
        import subprocess
        path = subprocess.run(["fc-match", "Arial", "-f", "%{file}"], capture_output=True, text=True, timeout=5).stdout.strip()
        font = ImageFont.truetype(path, 100)
    except Exception:
        return 1.0

    def plain(t: str) -> str:
        t = re.sub(r"\\(frac|dfrac)\{([^{}]*)\}\{([^{}]*)\}", r"\2/\3", t)
        t = re.sub(r"\\[A-Za-z]+", "x", t)
        return re.sub(r"[{}$^_]", "", t)
    avail_full = (8.27 - 2 * margin_in) * 72
    need = 0.0
    for q in exam.questions:
        items = [(q.text, 0.0, "")] + [(s_.text, 0.3, "א.  ") for s_ in q.sections]
        for text, indent, label in items:
            for b in text_structure.blocks(text, preserve_lines=True):
                ind = indent + (0.3 if b.block_type == "SUBSECTION" else 0.0)
                for k, line in enumerate(b.text.split("\n")):
                    if b.block_type == "DISPLAY_FORMULA":
                        continue
                    w = font.getlength(plain((label if k == 0 and b is not None else "") + line)) / 100.0   # points per 1pt font
                    need = max(need, w / max(1.0, avail_full - ind * 72))
    if need <= 0:
        return 1.0
    fit_pt = 1.0 / need * 0.98
    return max(MIN_FIT_PT / body_pt, min(1.0, fit_pt / body_pt))
