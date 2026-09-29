"""מחולל מבחנים במתמטיקה — V5 (Streamlit UI).

All logic lives in exam_core.py; this file only handles screens, widgets and session state.
"""
from __future__ import annotations

import hashlib
import io
import numpy as np
from pathlib import Path
import json
import uuid
import zipfile
from datetime import date
from typing import Any

import pandas as pd
import streamlit as st
from PIL import Image

import diagram_ui
import exam_core as core
from exam_core import (
    CommonError, ExamAnalysis, QuestionSection, RubricStep, SolutionStep,
)

try:
    from streamlit_paste_button import paste_image_button
except Exception:
    paste_image_button = None
try:
    from streamlit_cropper import st_cropper
except Exception:
    st_cropper = None
try:
    from streamlit_drawable_canvas import st_canvas
except Exception:
    st_canvas = None


st.set_page_config(page_title=core.APP_TITLE, page_icon="📐", layout="wide", initial_sidebar_state="expanded")
st.markdown(
    """
    <style>
    .stApp, [data-testid="stSidebar"] { direction: rtl; text-align: right; }
    .stApp { font-family: "Segoe UI", Tahoma, Arial, sans-serif; }
    [data-testid="stSidebar"] { text-align: right; }
    .stButton > button, .stDownloadButton > button { font-weight: 700; border-radius: 8px; }
    [data-testid="stTabs"] button { font-weight: 700; }
    /* keep formulas / code / canvases left-to-right */
    code, pre, .katex, iframe, [data-testid="stDataFrame"], [data-testid="stDataEditor"] { direction: ltr; }
    .katex { unicode-bidi: isolate; }   /* formulas stay LTR inside Hebrew lines (direction alone does not isolate inline math) */
    textarea, input[type="text"] { direction: rtl; text-align: right; unicode-bidi: plaintext; }
    </style>
    """,
    unsafe_allow_html=True,
)

STEPS = ["1. הגדרות הבחינה", "2. העלאת שאלות ועריכת תמונות", "3. פענוח ואימות", "4. בקרת איכות ועריכה", "5. הפקת Word ו-PDF"]
LANGUAGES = ["עברית", "ערבית", "אנגלית", "רוסית", "צרפתית", "ספרדית", "אמהרית", "אוקראינית"]


# ------------------------------------------------------------------
# Session state
# ------------------------------------------------------------------
def init_state() -> None:
    defaults = {
        "step": 1,
        "exam_meta": {},
        "questions_data": [],
        "processed_exam": None,
        "image_store": {},      # qnum -> list[{"id","original","current","history"}]
        "consumed": {},         # qnum -> set(digests) already taken from uploader/camera/paste
        "input_nonce": {},      # qnum -> int (resets uploader/camera widgets after use)
        "editor_epoch": 0,
        "q_version": {},        # qnum -> int (forces fresh editors after re-analysis / rebalance)
        "flash": [],
        "analysis_notes": [],
        "api_key": "",
        "docs_cache": {},
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


init_state()
S = st.session_state


def flash(kind: str, message: str) -> None:
    S.flash.append((kind, message))


def show_flash() -> None:
    for kind, message in S.flash:
        getattr(st, kind, st.info)(message)
    S.flash = []


def go(step: int) -> None:
    S.step = step
    if step == 4:
        # Fresh editor widgets every time step 4 is entered: Streamlit drops widget state of widgets that were
        # not rendered, so re-using old keys with a stored source frame would silently restore stale data.
        S.editor_epoch += 1
        for key in [k for k in S.keys() if str(k).startswith("src_")]:
            del S[key]


def init_key(key: str, value: Any) -> None:
    if key not in S:
        S[key] = value


def get_secret(name: str) -> str:
    try:
        value = st.secrets.get(name)
        return str(value) if value else ""
    except Exception:
        return ""


# ------------------------------------------------------------------
# Image store helpers
# ------------------------------------------------------------------
def store(q: int) -> list[Any]:
    """Editor items of a question. Legacy (pre-5.7.1) plain-dict items are migrated to versioned ImageItems
    (their original is the best available master; an unrecorded edit chain is marked unknown - never guessed)."""
    from image_store import ImageItem

    items = S.image_store.setdefault(q, [])
    for i, it in enumerate(items):
        if not isinstance(it, ImageItem):
            new = ImageItem(str(workspace().root / "images"), it["original"], it["original"], it["id"])
            for h in list(it.get("history", [])):
                new.push(h, None)
            if it.get("current") is not None and it["current"] != it["original"]:
                new.push(it["current"], None)
            if not it.get("history") and it.get("current") == it.get("original"):
                dict.__setitem__(new, "hist", [])
            items[i] = new
    return items


def consumed(q: int) -> set[str]:
    return S.consumed.setdefault(q, set())


def nonce(q: int) -> int:
    return S.input_nonce.setdefault(q, 0)


def add_images(q: int, images: list[bytes], photo: bool = False) -> int:
    """images = FULL-RESOLUTION masters. The working/preview derivative is derived; the master is kept on disk.
    photo=True (upload / camera / paste): the photo is flattened first (perspective, lighting, tilt - reading/rectify),
    so every later step - the AI, the second reader, OCR, figure crops - works on the flat page."""
    from image_store import ImageItem

    added = 0
    for master in images:
        if photo and S.get("auto_rectify", True):
            from reading.rectify import rectify_photo_bytes
            master, info = rectify_photo_bytes(master)
            if info.get("perspective") or info.get("illumination"):
                S.setdefault("rectify_log", []).append({"q": q, **info})
        working = core.pil_to_png_bytes(core.png_bytes_to_pil(master))      # <= MAX_IMAGE_SIDE derivative
        digest = core.image_digest(working)
        if digest in consumed(q):
            continue
        consumed(q).add(digest)
        store(q).append(ImageItem(str(workspace().root / "images"), master, working, uuid.uuid4().hex[:10]))
        added += 1
    return added


def find_item(q: int, item_id: str) -> dict[str, Any] | None:
    return next((it for it in store(q) if it["id"] == item_id), None)


def update_item(q: int, item_id: str, new_bytes: bytes, op: dict | None = None) -> None:
    """New version on disk (history = version ids, no image copies in RAM). `op` = the normalized edit, replayed
    later on the full-resolution master."""
    item = find_item(q, item_id)
    if item is None:
        return
    item.push(new_bytes, op)


def cb_delete(q: int, item_id: str) -> None:
    item = find_item(q, item_id)
    if item is not None:
        consumed(q).discard(core.image_digest(item["original"]))
    S.image_store[q] = [it for it in store(q) if it["id"] != item_id]
    S.input_nonce[q] = nonce(q) + 1
    flash("success", f"התמונה נמחקה משאלה {q}.")


def cb_reset(q: int, item_id: str) -> None:
    item = find_item(q, item_id)
    if item:
        item.reset()
        flash("success", "התמונה הוחזרה למקור.")


def cb_undo(q: int, item_id: str) -> None:
    item = find_item(q, item_id)
    if item and item.undo():
        flash("success", "הפעולה האחרונה בוטלה.")


def cb_clear_all(q: int) -> None:
    S.image_store[q] = []
    consumed(q).clear()
    S.input_nonce[q] = nonce(q) + 1
    flash("success", f"כל התמונות של שאלה {q} נמחקו.")


def cb_rotate(q: int, item_id: str, degrees: float) -> None:
    item = find_item(q, item_id)
    if item:
        update_item(q, item_id, core.rotate_image_bytes(item["current"], degrees), {"type": "rotate", "deg": float(degrees)})
        flash("success", f"התמונה סובבה ב-{abs(degrees):g}°.")


def cb_straighten(q: int, item_id: str) -> None:
    item = find_item(q, item_id)
    if not item:
        return
    fixed, angle = core.auto_straighten_bytes(item["current"])
    if angle:
        update_item(q, item_id, fixed, {"type": "rotate", "deg": float(angle)})
        flash("success", f"התמונה יושרה (תיקון של {angle:+.1f}°).")
    else:
        flash("info", "התמונה כבר ישרה — לא נדרש תיקון.")


@st.cache_data(show_spinner=False, max_entries=64)
def thumb(data: bytes, max_side: int = 420) -> bytes:
    img = core.png_bytes_to_pil(data)
    img.thumbnail((max_side, max_side))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


@st.cache_data(show_spinner=False, max_entries=64)
def editor_preview(data: bytes) -> tuple[Image.Image, float]:
    """Decode/downscale once per image revision; crop/canvas drags then reuse the cached preview."""
    return core.fit_for_editor(core.png_bytes_to_pil(data))


@st.cache_data(show_spinner=False, max_entries=256)
def cached_crop(source: bytes, bbox: tuple[int, ...]) -> bytes:
    return core.crop_figure_bytes(source, list(bbox))


def image_size(data: bytes) -> str:
    with Image.open(io.BytesIO(data)) as im:
        return f"{im.width}×{im.height}"


# ------------------------------------------------------------------
# Sidebar
# ------------------------------------------------------------------
st.sidebar.title("📐 מחולל המבחנים")
st.sidebar.caption(f"גרסה {core.APP_VERSION}")
for idx, label in enumerate(STEPS, 1):
    mark = "🔵" if S.step == idx else ("✅" if S.step > idx else "⚪")
    st.sidebar.markdown(f"{mark} {'**' + label + '**' if S.step == idx else label}")
st.sidebar.divider()
st.sidebar.caption(
    "תמונות השאלות נשלחות ל-Gemini API לצורך הפענוח. אין לכלול בצילומים פרטים מזהים של תלמידים, "
    "ובדקו את תנאי השימוש של Google לגבי השכבה שבה אתם משתמשים."
)

show_flash()


# ==================================================================
# Step 1 — exam settings
# ==================================================================
def import_pdf_questions(pdf_bytes: bytes, selected: list[int]) -> int:
    """PRIMARY use of PDFs: the teacher picks questions from a PDF and ADDS them to the exam being built. Each picked
    question enters the SAME question pipeline (full-resolution PDF evidence, cross-page questions merged)."""
    from document import build_document
    from document.reconstruct import questions_data
    model = build_document(pdf_bytes)
    data = {d["question_number"]: d for d in questions_data(pdf_bytes, model)}
    n0 = int(S.get("s1_n") or 0)
    k = 0
    for src_no in selected:
        if src_no not in data:
            continue
        k += 1
        add_images(n0 + k, data[src_no]["masters"])
        from document.state import source_hash
        payload = {"source_question": src_no, "document_sha256": model.metadata.get("pdf_sha256", ""),
                   "response_templates": data[src_no]["document"]["response_templates"],
                   "text_layer": data[src_no]["document"]["text_layer"], "pages": data[src_no]["document"]["pages"]}
        from document.state import item_ops_hash
        for it in store(n0 + k):                          # evidence keyed by the SOURCE identity, never the number
            S.setdefault("source_evidence", {})[source_hash(it)] = {**payload, "import_ops_hash": item_ops_hash(it)}
    S._pending_s1_n = n0 + k
    return k


def import_full_document(pdf_bytes: bytes) -> int:
    """MODE B: a whole exam PDF -> one editor item per logical question (cropped from the full-resolution page render).
    The teacher can still crop/erase each item; the analysis then runs per question as usual."""
    from document import build_document
    from document.reconstruct import questions_data
    model = build_document(pdf_bytes)
    data = questions_data(pdf_bytes, model)
    from document.reconstruct import templates_by_question
    S.image_store = {}
    S.consumed = {}
    for d in data:
        add_images(d["question_number"], d["masters"])            # full-resolution master; the item derives the working copy
    S.document_model = model.model_dump()                          # CANONICAL Mode-B state (survives every rebuild)
    S.document_templates = templates_by_question(data)
    from document.state import question_payload, source_hash
    S.source_evidence = {}
    for d in data:
        payload = question_payload(S.document_model, d["question_number"], S.document_templates,
                                   {str(d["question_number"]): d["document"]["text_layer"]})
        from document.state import item_ops_hash
        for it in store(d["question_number"]):                   # bound to the imported source, not to the number
            S.source_evidence[source_hash(it)] = {**payload, "import_ops_hash": item_ops_hash(it)}
    from document.reconstruct import text_layers_by_question
    S.document_text_layers = text_layers_by_question(data)
    workspace().store("source_document.pdf", pdf_bytes)             # the original PDF is kept as evidence
    S.meta = {**S.get("meta", {}), "num_questions": len(data)}
    S._pending_s1_n = len(data)          # applied BEFORE the number widget is created (never write a live widget key)
    return len(data)


def step1() -> None:
    if S.get("_pending_s1_n"):
        S.s1_n = S.pop("_pending_s1_n")
    with st.expander("📄 ייבוא מבחן שלם (PDF) — זיהוי אוטומטי של השאלות", expanded=False):
        st.caption("המערכת מזהה עמודי הוראות, שאלות, המשכים בין עמודים, תרשימים ותבניות תשובה. כל שאלה נבנית מחדש — "
                   "הסריקה משמשת רק כראיה.")
        pdf = st.file_uploader("קובץ PDF של מבחן", type=["pdf"], key="s1_pdf")
        if pdf is not None:
            try:
                from document import build_document
                found = [q.number for q in build_document(pdf.getvalue()).questions]
            except Exception:
                found = []
            if found:
                pick = st.multiselect("בחירת שאלות להוספה למבחן", found, default=[], key="s1_pdf_pick")
                if pick and st.button("➕ הוספת השאלות שנבחרו למבחן", key="s1_pdf_add"):
                    k = import_pdf_questions(pdf.getvalue(), sorted(pick))
                    flash("success", f"נוספו {k} שאלות מה-PDF. כל שאלה תשוחזר מחדש בסגנון המבחן.")
                    st.rerun()
        if pdf is not None and st.button("ייבוא כל השאלות מה-PDF (החלפת המבחן)", key="s1_pdf_go"):
            try:
                n = import_full_document(pdf.getvalue())
                flash("success", f"זוהו {n} שאלות. אפשר לעבור לשלב הבא (ולערוך כל שאלה בשלב 2).")
            except Exception:
                flash("error", "לא ניתן היה לקרוא את קובץ ה-PDF. יש לנסות קובץ אחר או להעלות תמונות.")
            st.rerun()
    st.title("שלב 1: הגדרת הבחינה")
    meta = S.exam_meta
    grade_options = ["שכבה ט'", "שכבה י'", 'שכבה י"א', 'שכבה י"ב', "חטיבת ביניים", "אחר"]
    level_options = ["5 יחידות לימוד", "4 יחידות לימוד", "3 יחידות לימוד", "רמה מוגברת", "אחר"]

    init_key("s1_school", meta.get("school_name", ""))
    init_key("s1_exam", meta.get("exam_name", "מבחן במתמטיקה"))
    init_key("s1_grade", meta.get("grade", "שכבה י'") if meta.get("grade", "שכבה י'") in grade_options else "אחר")
    init_key("s1_level", meta.get("level", "5 יחידות לימוד") if meta.get("level", "5 יחידות לימוד") in level_options else "אחר")
    init_key("s1_lang", meta.get("language", "עברית"))
    init_key("s1_teacher", meta.get("teacher_name", ""))
    init_key("s1_duration", int(meta.get("duration", 90)))
    init_key("s1_n", int(meta.get("num_questions", 4)))
    try:
        init_key("s1_date", date.fromisoformat(meta["date"]) if meta.get("date") else date.today())
    except Exception:
        init_key("s1_date", date.today())
    init_key("s1_mode", meta.get("choice_mode", "ללא בחירה"))

    c1, c2 = st.columns(2)
    with c1:
        st.text_input("שם בית הספר", key="s1_school")
        st.text_input("שם הבחינה / נושא", key="s1_exam")
        st.selectbox("שכבה", grade_options, key="s1_grade")
        st.selectbox("רמת לימוד", level_options, key="s1_level")
        st.selectbox("שפת מסמכי הבחינה", LANGUAGES, key="s1_lang")
    with c2:
        st.text_input("שם המורה / רכז המקצוע", key="s1_teacher")
        st.number_input("משך הבחינה (בדקות)", min_value=30, max_value=360, step=5, key="s1_duration")
        st.number_input("מספר שאלות בטופס", min_value=1, max_value=12, step=1, key="s1_n")
        st.date_input("תאריך הבחינה", key="s1_date", format="DD/MM/YYYY")

    n = int(S.s1_n)
    mode = st.radio("מבנה הבחירה", ["ללא בחירה", "בחירה כללית", "קבוצות בחירה"], horizontal=True, key="s1_mode")
    groups: list[dict[str, Any]] = []
    old_groups = meta.get("choice_groups", [])
    if mode == "ללא בחירה":
        groups = [{"name": "כל השאלות", "questions": list(range(1, n + 1)), "required": n}]
    elif mode == "בחירה כללית":
        old_req = int(old_groups[0].get("required", 1)) if old_groups else 1
        init_key("s1_req_all", min(max(1, old_req), n))
        if S.s1_req_all > n:
            S.s1_req_all = n
        req = st.number_input("על כמה שאלות יש לענות?", min_value=1, max_value=n, step=1, key="s1_req_all")
        groups = [{"name": "בחירה כללית", "questions": list(range(1, n + 1)), "required": int(req)}]
    else:
        init_key("s1_groups", max(1, min(n, len(old_groups) or min(2, n))))
        if S.s1_groups > n:
            S.s1_groups = n
        count = int(st.number_input("מספר קבוצות בחירה", min_value=1, max_value=n, step=1, key="s1_groups"))
        all_q = list(range(1, n + 1))
        for gi in range(count):
            old = old_groups[gi] if gi < len(old_groups) else {}
            default = [q for q in old.get("questions", []) if q in all_q] or [q for q in all_q if (q - 1) % count == gi]
            init_key(f"s1_gq_{gi}_{n}", default)
            selected = st.multiselect(f"קבוצה {gi + 1} — שאלות בקבוצה", all_q, key=f"s1_gq_{gi}_{n}")
            max_req = max(1, len(selected))
            init_key(f"s1_gr_{gi}_{n}", min(max(1, int(old.get("required", len(selected) or 1))), max_req))
            if S[f"s1_gr_{gi}_{n}"] > max_req:
                S[f"s1_gr_{gi}_{n}"] = max_req
            req = st.number_input(f"קבוצה {gi + 1} — על כמה שאלות יש לענות?", min_value=1, max_value=max_req, step=1,
                                  key=f"s1_gr_{gi}_{n}")
            groups.append({"name": f"קבוצה {gi + 1}", "questions": selected, "required": int(req)})

    group_errors = core.validate_choice_groups(n, groups)
    for err in group_errors:
        st.error(err)

    suggested = core.build_default_instructions(int(S.s1_duration), groups)
    init_key("s1_show_points", bool(meta.get("show_question_points", False)))
    st.checkbox("הצגת ניקוד כל שאלה במבחן לתלמיד (למשל \"שאלה 1 (20 נקודות)\")", key="s1_show_points",
                help="ניקוד הסעיפים לעולם אינו מוצג לתלמיד; הוא נשמר במחוון ובפתרונות.")
    init_key("s1_keep_lines", bool(meta.get("preserve_source_lines", True)))
    st.checkbox("שמירת שבירות השורה של המקור (כל שורה במבחן תתחיל ותסתיים כמו במקור)", key="s1_keep_lines")
    init_key("s1_instructions", meta.get("instructions", suggested))
    init_key("s1_last_suggested", meta.get("instructions_suggested", S.s1_instructions))
    # Instructions the teacher never edited follow the exam structure automatically (question count, choice, duration).
    if S.s1_instructions == S.s1_last_suggested and suggested != S.s1_last_suggested:
        S.s1_instructions = suggested
    S.s1_last_suggested = suggested if S.s1_instructions == suggested else S.s1_last_suggested

    def refresh() -> None:
        S.s1_instructions = suggested
        S.s1_last_suggested = suggested

    st.button("🔄 רענן הוראות לפי מבנה הבחינה", on_click=refresh)
    st.text_area("הוראות כלליות לתלמיד", key="s1_instructions", height=200)
    if S.s1_instructions.strip() != suggested.strip():
        st.warning("ההוראות נערכו ידנית ואינן מתעדכנות אוטומטית. ודאו שהן תואמות את מבנה הבחינה "
                   f"({n} שאלות, {mode}, {int(S.s1_duration)} דקות), או לחצו 'רענן הוראות'.")

    logo_up = st.file_uploader("לוגו בית הספר (PNG/JPG)", type=["png", "jpg", "jpeg"], key="s1_logo")
    keep_logo = False
    if meta.get("logo_bytes") and not logo_up:
        st.image(meta["logo_bytes"], width=90)
        keep_logo = not st.checkbox("הסר את הלוגו השמור", key="s1_remove_logo")

    if st.button("המשך להעלאת שאלות ⬅️", type="primary", disabled=bool(group_errors)):
        logo = None
        if logo_up:
            try:
                logo = core.image_to_png_bytes(logo_up)
            except Exception as exc:
                st.error(f"לא ניתן לקרוא את קובץ הלוגו: {exc}")
                return
        elif keep_logo:
            logo = meta.get("logo_bytes")
        old_n = int(meta.get("num_questions", n))
        S.exam_meta = {
            "school_name": S.s1_school.strip(), "exam_name": S.s1_exam.strip(), "grade": S.s1_grade,
            "level": S.s1_level, "teacher_name": S.s1_teacher.strip(), "duration": int(S.s1_duration),
            "num_questions": n, "language": S.s1_lang, "date": S.s1_date.isoformat(),
            "instructions": S.s1_instructions, "instructions_suggested": S.s1_last_suggested, "choice_mode": mode, "choice_groups": groups, "logo_bytes": logo,
            "show_question_points": bool(S.get("s1_show_points", False)),
            "preserve_source_lines": bool(S.get("s1_keep_lines", True)),
        }
        if n < old_n:  # drop images of removed questions
            for q in range(n + 1, old_n + 1):
                S.image_store.pop(q, None)
        go(2)
        st.rerun()


# ==================================================================
# Step 2 — upload + image editing
# ==================================================================
def image_inputs(q: int) -> None:
    init_key("auto_rectify", True)
    st.checkbox("ניקוי צילום אוטומטי (יישור פרספקטיבה, איזון תאורה ויישור הטיה)", key="auto_rectify",
                help="מומלץ לצילומי טלפון. סריקה נקייה אינה משתנה.")
    source = st.radio("הוספת תמונות", ["📁 העלאת קבצים", "📷 מצלמה", "📋 הדבקה מהלוח"], horizontal=True, key=f"src_mode_{q}")
    if source.startswith("📁"):
        files = st.file_uploader(f"תמונות לשאלה {q}", type=["png", "jpg", "jpeg", "webp"], accept_multiple_files=True,
                                 key=f"up_{q}_{nonce(q)}", label_visibility="collapsed")
        if files:
            try:
                added = add_images(q, [core.image_to_png_bytes(f, max_side=None) for f in files], photo=True)
                flash("success", f"נוספו {added} תמונות לשאלה {q}." if added else "התמונות כבר קיימות בשאלה.")
            except core.ImageInputError as exc:
                flash("error", str(exc))
            except Exception:
                flash("error", "לא ניתן היה לקרוא את אחד הקבצים. יש להעלות תמונה תקינה.")
            S.input_nonce[q] = nonce(q) + 1  # empty the uploader so deleted images can never come back
            st.rerun()
    elif source.startswith("📷"):
        shot = st.camera_input("צילום", key=f"cam_{q}_{nonce(q)}", label_visibility="collapsed")
        if shot is not None:
            try:
                added = add_images(q, [core.image_to_png_bytes(shot, max_side=None)], photo=True)
                flash("success", "הצילום נוסף." if added else "הצילום כבר קיים.")
            except core.ImageInputError as exc:
                flash("error", str(exc))
            S.input_nonce[q] = nonce(q) + 1
            st.rerun()
    else:
        if paste_image_button is None:
            st.info("רכיב ההדבקה אינו מותקן.")
        else:
            res = paste_image_button("📋 הדבק תמונה מהלוח", background_color="#1E88E5",
                                     hover_background_color="#1565C0", key=f"paste_{q}")
            if getattr(res, "image_data", None) is not None:
                pasted = core.image_to_png_bytes(res.image_data, max_side=None)
                seen = S.setdefault("paste_seen", {}).setdefault(q, set())
                digest = core.image_digest(pasted)
                if digest in seen:
                    return  # same paste value re-sent by the component on a rerun (maybe deleted since)
                seen.add(digest)
                if add_images(q, [pasted], photo=True):
                    flash("success", "התמונה הודבקה.")
                    st.rerun()


def gallery(q: int) -> None:
    items = store(q)
    if not items:
        st.caption("עדיין לא הועלו תמונות לשאלה זו.")
        return
    cols = st.columns(3)
    for idx, item in enumerate(items):
        with cols[idx % len(cols)]:
            with st.container(border=True):
                st.image(thumb(item["current"]), caption=f"תמונה {idx + 1} · {image_size(item['current'])}", width="stretch")
                b1, b2, b3 = st.columns(3)
                b1.button("🗑️ מחק", key=f"del_{item['id']}", on_click=cb_delete, args=(q, item["id"]), width="stretch")
                b2.button("↩️ בטל", key=f"undo_{item['id']}", on_click=cb_undo, args=(q, item["id"]),
                          disabled=not item["history"], width="stretch", help="ביטול הפעולה האחרונה")
                b3.button("⟲ מקור", key=f"reset_{item['id']}", on_click=cb_reset, args=(q, item["id"]),
                          disabled=item["current"] == item["original"], width="stretch", help="חזרה לתמונה המקורית")
    st.button(f"מחק את כל התמונות של שאלה {q}", key=f"clear_{q}", on_click=cb_clear_all, args=(q,))


@st.fragment
def image_editor(q: int) -> None:
    items = store(q)
    if not items:
        return
    st.markdown("**✏️ עריכת תמונה**")
    labels = {it["id"]: f"תמונה {i + 1}" for i, it in enumerate(items)}
    init_key(f"edsel_{q}", items[0]["id"])
    if S[f"edsel_{q}"] not in labels:
        S[f"edsel_{q}"] = items[0]["id"]
    c1, c2 = st.columns([1, 3])
    with c1:
        item_id = st.selectbox("בחר תמונה", list(labels), format_func=labels.get, key=f"edsel_{q}")
    with c2:
        tool = st.radio("כלי", ["✂️ חיתוך", "🧽 מחיקת סימנים", "🔄 סיבוב ויישור"], horizontal=True, key=f"tool_{q}")
    item = find_item(q, item_id)
    if item is None:
        return
    rev = core.image_digest(item["current"])[:8]
    display, scale = editor_preview(item["current"])

    if tool.startswith("✂️"):
        if st_cropper is None:
            st.warning("רכיב החיתוך (streamlit-cropper) אינו מותקן.")
            return
        st.caption("גרור את המסגרת האדומה סביב האזור הרצוי ולחץ 'שמור חיתוך'. החיתוך נשמר ברזולוציה המלאה.")
        box = st_cropper(display, realtime_update=True, box_color="#E53935", aspect_ratio=None, return_type="box",
                         key=f"crop_{item_id}_{rev}")
        if box:
            preview = display.crop((box["left"], box["top"], box["left"] + box["width"], box["top"] + box["height"]))
            st.image(preview, caption=f"תצוגה מקדימה · יישמר בגודל ≈{int(box['width'] * scale)}×{int(box['height'] * scale)}", width=320)
            if st.button("💾 שמור חיתוך", key=f"savecrop_{item_id}_{rev}", type="primary"):
                try:
                    with st.spinner("שומר חיתוך..."):
                        rect = core.crop_box_to_normalized(item["current"], box, scale)
                        update_item(q, item_id, core.crop_full_resolution(item["current"], box, scale), {"type": "crop", "rect": rect})
                    flash("success", "החיתוך נשמר.")
                except Exception as exc:
                    flash("error", f"החיתוך נכשל: {exc}")
                st.rerun()

    elif tool.startswith("🧽"):
        if st_canvas is None:
            st.warning("רכיב המחיקה (streamlit-drawable-canvas) אינו מותקן.")
            return
        m1, m2 = st.columns(2)
        with m1:
            mode = st.radio("צורת מחיקה", ["מלבן", "מכחול חופשי"], horizontal=True, key=f"emode_{q}")
        with m2:
            width = st.slider("עובי מכחול", 6, 80, 24, 2, key=f"ewidth_{q}", disabled=mode == "מלבן")
        st.caption("סמן בוורוד את מה שצריך להעלים (כתמים, סימוני עט, ניקוד תלמיד). בשמירה האזור המסומן יהפוך ללבן.")
        canvas = st_canvas(
            fill_color="rgba(255, 0, 110, 0.45)", stroke_width=width if mode != "מלבן" else 2,
            stroke_color="rgba(255, 0, 110, 0.6)", background_image=display, update_streamlit=True,
            height=display.height, width=display.width, drawing_mode="rect" if mode == "מלבן" else "freedraw",
            return_image_data=True, key=f"canvas_{item_id}_{rev}_{mode}",
        )
        if st.button("💾 שמור מחיקה", key=f"saveerase_{item_id}_{rev}", type="primary"):
            try:
                if canvas is None or canvas.image_data is None:
                    raise ValueError("לא התקבל סימון מהקנבס.")
                with st.spinner("מוחק את האזור המסומן..."):
                    new_bytes, fraction = core.apply_erase_mask(item["current"], canvas.image_data)
                    mask_buf = io.BytesIO()
                    Image.fromarray(np.asarray(canvas.image_data).astype("uint8"), "RGBA").save(mask_buf, format="PNG")
                update_item(q, item_id, new_bytes, {"type": "erase", "mask_id": item.put_blob(mask_buf.getvalue())})
                flash("success", f"האזור המסומן נמחק ({fraction:.1%} מהתמונה).")
            except Exception as exc:
                flash("error", f"המחיקה לא בוצעה: {exc}")
            st.rerun()

    else:
        r1, r2, r3, r4 = st.columns(4)
        # Plain buttons + st.rerun(): callbacks inside an st.fragment only rerun the fragment, which left the
        # gallery thumbnail and the undo button stale after a rotation (5.2-audited).
        if r1.button("↺ 90° שמאלה", key=f"rl_{item_id}", width="stretch"):
            cb_rotate(q, item_id, 90)
            st.rerun()
        if r2.button("↻ 90° ימינה", key=f"rr_{item_id}", width="stretch"):
            cb_rotate(q, item_id, -90)
            st.rerun()
        if r3.button("⟳ 180°", key=f"r180_{item_id}", width="stretch"):
            cb_rotate(q, item_id, 180)
            st.rerun()
        if r4.button("📐 יישור אוטומטי", key=f"straight_{item_id}", width="stretch"):
            with st.spinner("מיישר..."):
                cb_straighten(q, item_id)
            st.rerun()
        angle = st.slider("סיבוב עדין (מעלות, חיובי = עם כיוון השעון)", -15.0, 15.0, 0.0, 0.25, key=f"fine_{item_id}_{rev}")
        if abs(angle) > 0.001:
            st.image(display.rotate(-angle, expand=True, fillcolor=(255, 255, 255)), caption="תצוגה מקדימה", width=380)
            if st.button("💾 שמור סיבוב", key=f"saverot_{item_id}_{rev}", type="primary"):
                with st.spinner("מסובב..."):
                    update_item(q, item_id, core.rotate_image_bytes(item["current"], -angle), {"type": "rotate", "deg": float(-angle)})
                flash("success", f"התמונה סובבה ב-{angle:+.2f}°.")
                st.rerun()


def step2() -> None:
    st.title("שלב 2: העלאת שאלות ועריכת תמונות")
    meta = S.exam_meta
    n = int(meta["num_questions"])
    defaults = core.suggested_points(meta)
    old = {int(q["question_number"]): q for q in S.questions_data}
    st.info("לכל שאלה אפשר לצרף כמה תמונות, ולפני הפענוח לחתוך, לנקות סימנים, לסובב וליישר. "
            "הניקוד שתזינו כאן הוא מקור האמת.")
    # Points for all questions in one compact row (always visible).
    st.markdown("**ניקוד השאלות**")
    pcols = st.columns(min(n, 6))
    for q in range(1, n + 1):
        init_key(f"pts_{q}", float(old.get(q, {}).get("points", defaults[q])))
        pcols[(q - 1) % len(pcols)].number_input(f"שאלה {q}", min_value=0.5, max_value=100.0, step=0.5, format="%.2f",
                                                 key=f"pts_{q}")

    # One question at a time, rendered openly. Custom components (cropper / canvas) must NOT live inside a
    # collapsed expander or an inactive tab: they measure their size while hidden and stay blank (height 0).
    options = [str(q) for q in range(1, n + 1)]
    if str(S.get("s2_sel", "1")) not in options:
        S.s2_sel = "1"
    else:
        S.s2_sel = str(S.get("s2_sel", "1"))
    st.divider()
    # Labels must stay constant between reruns: Streamlit matches radio options by their displayed text,
    # so a label that includes a changing image count loses the selection (and crashed in 5.0).
    sel = int(st.radio("בחר שאלה לעבודה", options, horizontal=True, key="s2_sel", format_func=lambda q: f"שאלה {q}"))
    st.caption("   ".join(f"{'✅' if store(q) else '⬜'} שאלה {q}: {len(store(q))} תמונות" for q in range(1, n + 1)))
    with st.container(border=True):
        st.subheader(f"שאלה {sel}")
        image_inputs(sel)
        gallery(sel)
        image_editor(sel)
    missing_now = [q for q in range(1, n + 1) if not store(q)]
    if missing_now:
        st.caption("שאלות ללא תמונות: " + ", ".join(map(str, missing_now)))

    points = {q: float(S[f"pts_{q}"]) for q in range(1, n + 1)}
    total_errors = core.validate_points_structure(meta, points)
    route_hint = sum(points.values()) if all(int(g["required"]) == len(g["questions"]) for g in meta["choice_groups"]) else None
    if route_hint is not None:
        st.caption(f'סה"כ ניקוד: {route_hint:g}')
    b1, b2 = st.columns(2)
    if b1.button("➡️ חזור להגדרות"):
        go(1)
        st.rerun()
    if b2.button("אישור ומעבר לפענוח ⬅️", type="primary"):
        missing = [q for q in range(1, n + 1) if not store(q)]
        if missing:
            st.error(f"חסרות תמונות לשאלות: {', '.join(map(str, missing))}")
        elif total_errors:
            for err in total_errors:
                st.error(err)
        else:
            from document.state import build_questions_data
            new_data = build_questions_data({q: store(q) for q in range(1, n + 1)}, points, n,
                                            source_evidence=S.get("source_evidence") or {})
            if new_data != S.questions_data:
                S.processed_exam = None
            S.questions_data = new_data
            go(3)
            st.rerun()


# ==================================================================
# Step 3 — Gemini analysis
# ==================================================================
def step3() -> None:
    st.title("שלב 3: פענוח ואימות באמצעות Gemini")
    secret_key = get_secret("GEMINI_API_KEY")
    if secret_key:
        S.api_key = secret_key
        st.success("מפתח Gemini נמצא ב-Secrets.")
    else:
        init_key("api_key_input", S.api_key)
        st.text_input("Gemini API Key", key="api_key_input", type="password",
                      help="המפתח נשמר רק בזיכרון של הסשן הנוכחי.")
        S.api_key = S.api_key_input.strip()
    init_key("model_name", get_secret("GEMINI_MODEL") or core.DEFAULT_MODEL)
    c1, c2 = st.columns(2)
    c1.text_input("מודל Gemini", key="model_name", help="אם המודל אינו זמין למפתח, המערכת תעבור אוטומטית למודל Flash אחר.")
    c2.checkbox("אימות עצמאי של הפתרונות (קריאה נוספת לכל שאלה — מומלץ)", value=True, key="verify_on")
    c2.caption("שחזורי שרטוטים נכנסים למסמך רק אחרי אישור מורה בשלב 4 (אין אישור אוטומטי).")

    n_q = len(S.questions_data)
    calls = core.estimate_calls(n_q, S.verify_on, S.exam_meta.get("language", "עברית"))
    st.caption(
        f"הפענוח ישתמש בכ-{calls} קריאות ל-Gemini. במפתח חינמי (5 קריאות בדקה) זה ייקח כ-{max(1, round(calls / 5))} דקות — "
        "המערכת מזהה את המגבלה ומאטה את הקצב אוטומטית. לחיסכון במכסה אפשר לבטל את האימות העצמאי."
    )

    exam_prev: ExamAnalysis | None = S.processed_exam
    failed = [q.question_number for q in exam_prev.questions if q.analysis_error] if exam_prev else []
    if exam_prev is not None and failed:
        st.warning(f"שאלות שלא פוענחו: {', '.join(map(str, failed))}.")
        for q in exam_prev.questions:
            if q.analysis_error:
                with st.expander(f"שאלה {q.question_number}: {q.analysis_error}"):
                    st.code(q.error_detail or q.analysis_error, language="text")
    elif exam_prev is not None:
        st.info("קיים פענוח קודם לנתונים אלה. אפשר להמשיך לעריכה או לפענח מחדש.")

    def run(only: set[int] | None) -> None:
        bar = st.progress(0.0, text="מתחיל...")
        try:
            import reading
            reading.configure({k: get_secret(k) for k in ("SECOND_READER", "ANTHROPIC_API_KEY", "SECOND_READER_MODEL")})
            service = core.GeminiService(S.api_key, S.model_name.strip() or core.DEFAULT_MODEL, rpm=S.get("rate_rpm"))
            exam, notes = core.run_full_analysis(
                service, S.exam_meta, S.questions_data, verify=S.verify_on,
                progress=lambda frac, msg: bar.progress(frac, text=msg),
                existing=S.processed_exam if only else None, only=only,
            )
        except Exception as exc:
            st.error(core.friendly_error(exc))
            with st.expander("פרטים טכניים"):
                st.code(str(exc), language="text")
            return
        if service.rpm:
            S.rate_rpm = service.rpm  # remember the learned quota for later calls in this session
        S.processed_exam = exam
        S.analysis_notes = notes
        still_failed = [q.question_number for q in exam.questions if q.analysis_error]
        for note in notes:
            flash("info", note)
        if still_failed and len(still_failed) == len(exam.questions):
            flash("error", "אף שאלה לא פוענחה. " + exam.questions[0].analysis_error)
            st.rerun()  # stay in step 3 so the teacher can retry
        if still_failed:
            flash("warning", f"שאלות {still_failed} לא פוענחו. אפשר לנסות שוב כאן או לפענח כל אחת מחדש בשלב 4.")
        else:
            flash("success", f"הפענוח הושלם (מודל: {exam.model_used}).")
        go(4)
        st.rerun()

    b1, b2, b3 = st.columns(3)
    if b1.button("➡️ חזור להעלאה"):
        go(2)
        st.rerun()
    if failed:
        if b2.button(f"🔁 נסה שוב רק את השאלות שנכשלו ({len(failed)})", type="primary", disabled=not S.api_key):
            run(set(failed))
        if b3.button("🚀 פענח את כל השאלות מחדש", disabled=not S.api_key):
            run(None)
    else:
        if b2.button("🚀 התחל פענוח", type="primary", disabled=not S.api_key):
            run(None)
        if exam_prev is not None and b3.button("המשך לעריכה ⬅️"):
            go(4)
            st.rerun()


# ==================================================================
# Step 4 — quality control
# ==================================================================
def make_df(rows: list[dict[str, Any]], columns: dict[str, str]) -> pd.DataFrame:
    data = {c: [r.get(c) for r in rows] for c in columns}
    df = pd.DataFrame(data, columns=list(columns))
    for col, dtype in columns.items():
        if dtype == "float":
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
        elif dtype == "int":
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
        elif dtype == "bool":
            df[col] = df[col].fillna(False).astype("bool")
        else:
            df[col] = df[col].fillna("").astype("str")
    return df


def editor(key: str, rows: list[dict[str, Any]], columns: dict[str, str], config: dict[str, Any]) -> list[dict[str, Any]]:
    """data_editor with a FIXED source frame (created once per key) — edits are never fed back as new input."""
    src_key = f"src_{key}"
    if src_key not in S:
        S[src_key] = make_df(rows, columns)
    edited = st.data_editor(S[src_key], key=key, num_rows="dynamic", width="stretch", hide_index=True, column_config=config)
    return edited.astype(object).where(pd.notnull(edited), None).to_dict(orient="records")


def txt(value: Any) -> str:
    return "" if value is None else str(value).strip()


def reanalyze(qnum: int) -> None:
    exam: ExamAnalysis = S.processed_exam
    source = next(q for q in S.questions_data if int(q["question_number"]) == qnum)
    try:
        service = core.GeminiService(S.api_key, S.get("model_name") or core.DEFAULT_MODEL, rpm=S.get("rate_rpm"))
        new_q = core.analyze_question(service, S.exam_meta, source)
        if S.get("verify_on", True):
            try:
                new_q.verification = core.verify_question(service, S.exam_meta, source, new_q)
            except Exception as exc:
                new_q.verification_error = f"האימות נכשל: {core.friendly_error(exc)}"
        exam.questions = [new_q if q.question_number == qnum else q for q in exam.questions]
        flash("success", f"שאלה {qnum} פוענחה מחדש.")
    except Exception as exc:
        flash("error", f"פענוח מחדש של שאלה {qnum} נכשל: {core.friendly_error(exc)}")
    S.q_version[qnum] = S.q_version.get(qnum, 0) + 1


def rebalance(qnum: int) -> None:
    exam: ExamAnalysis = S.processed_exam
    q = next(q for q in exam.questions if q.question_number == qnum)
    core.rebalance_question(q)
    S.q_version[qnum] = S.q_version.get(qnum, 0) + 1
    flash("success", f"שאלה {qnum}: ניקוד הסעיפים ואחוזי המחוון אוזנו.")


def question_editor(q, source: dict[str, Any]) -> None:
    v = f"{S.editor_epoch}_{q.question_number}_{S.q_version.get(q.question_number, 0)}"
    if q.analysis_error:
        st.error(q.analysis_error)
        if q.error_detail:
            with st.expander("פרטים טכניים"):
                st.code(q.error_detail, language="text")
    a1, a2, a3 = st.columns([2, 1, 1])
    init_key(f"topic_{v}", q.topic)
    q.topic = a1.text_input("נושא (מוצג בפתרון ובמחוון)", key=f"topic_{v}")
    a2.metric("ניקוד השאלה (מהמורה)", core.fmt_points(q.points))
    a3.button("🔁 פענח שאלה זו מחדש", key=f"re_{v}", on_click=reanalyze, args=(q.question_number,),
              disabled=not S.api_key, width="stretch")
    init_key(f"text_{v}", q.text)
    q.text = st.text_area("גזע השאלה (נוסחאות בין \\$...\\$)", key=f"text_{v}", height=110)

    st.markdown("**סעיפים**")
    rows = editor(f"sec_{v}", [s.model_dump() for s in q.sections],
                  {"section_id": "str", "text": "str", "points": "float"},
                  {"section_id": st.column_config.TextColumn("סעיף", width="small"),
                   "text": st.column_config.TextColumn("נוסח", width="large"),
                   "points": st.column_config.NumberColumn("נקודות", min_value=0.0, step=0.5, format="%.2f")})
    q.sections = [QuestionSection(section_id=core.clean_section_id(r["section_id"]), text=txt(r["text"]),
                                  points=core.safe_float(r["points"])) for r in rows if txt(r["section_id"]) or txt(r["text"])]

    with st.expander("👁️ תצוגה מקדימה של השאלה (כפי שתיראה לתלמיד)", expanded=False):
        st.markdown(q.text or "—")
        for sec in q.sections:
            st.markdown(f"**{sec.section_id}.** ({core.fmt_points(sec.points)} נק') {sec.text}")

    st.markdown("**פתרון מלא**")
    rows = editor(f"sol_{v}", [s.model_dump() for s in q.solution_steps],
                  {"section_id": "str", "step_title": "str", "content": "str", "final_answer": "str"},
                  {"section_id": st.column_config.TextColumn("סעיף", width="small"),
                   "step_title": st.column_config.TextColumn("שם השלב", width="small"),
                   "content": st.column_config.TextColumn("הסבר / חישוב", width="large"),
                   "final_answer": st.column_config.TextColumn("תשובה סופית", width="medium")})
    q.solution_steps = [SolutionStep(section_id=core.clean_section_id(r["section_id"]), step_title=txt(r["step_title"]),
                                     content=txt(r["content"]), final_answer=txt(r["final_answer"]))
                        for r in rows if txt(r["step_title"]) or txt(r["content"])]

    st.markdown("**מחוון** — טעויות נפוצות: שורה לכל טעות, בפורמט `תיאור || חומרה || אחוז הורדה`")
    rub_rows = []
    for r in q.rubric_steps:
        d = r.model_dump(exclude={"common_errors"})
        d["common_errors"] = "\n".join(f"{e.error} || {e.severity} || {e.deduction_percent:g}" for e in r.common_errors)
        rub_rows.append(d)
    rows = editor(f"rub_{v}", rub_rows,
                  {"section_id": "str", "stage_desc": "str", "percentage": "float", "full_credit": "str",
                   "partial_credit": "str", "zero_credit": "str", "carried_over_error_policy": "str", "common_errors": "str"},
                  {"section_id": st.column_config.TextColumn("סעיף", width="small"),
                   "stage_desc": st.column_config.TextColumn("שלב"),
                   "percentage": st.column_config.NumberColumn("%", min_value=0.0, max_value=100.0, step=1.0),
                   "full_credit": "ניקוד מלא", "partial_credit": "ניקוד חלקי", "zero_credit": "אפס",
                   "carried_over_error_policy": st.column_config.TextColumn("טעות נגררת", width="medium"),
                   "common_errors": st.column_config.TextColumn("טעויות נפוצות", width="large")})
    new_rub = []
    for r in rows:
        if not txt(r["stage_desc"]):
            continue
        errors = []
        for line in txt(r["common_errors"]).splitlines():
            parts = [p.strip() for p in line.split("||")]
            if parts and parts[0]:
                errors.append(CommonError(error=parts[0], severity=parts[1] if len(parts) > 1 else "",
                                          deduction_percent=min(100.0, max(0.0, core.safe_float(parts[2] if len(parts) > 2 else 0)))))
        new_rub.append(RubricStep(section_id=core.clean_section_id(r["section_id"]), stage_desc=txt(r["stage_desc"]),
                                  percentage=min(100.0, max(0.0, core.safe_float(r["percentage"]))),
                                  full_credit=txt(r["full_credit"]), partial_credit=txt(r["partial_credit"]),
                                  zero_credit=txt(r["zero_credit"]), carried_over_error_policy=txt(r["carried_over_error_policy"]),
                                  common_errors=errors))
    q.rubric_steps = new_rub
    st.button("⚖️ איזון אוטומטי: סעיפים לפי ניקוד השאלה ומחוון ל-100%", key=f"bal_{v}", on_click=rebalance,
              args=(q.question_number,))

    diagram_ui.figures_section(q, source, v, editor, S)
    images = source.get("images", [])

    reading_panel(q, source)

    st.markdown("**בדיקה עצמאית של הפתרון**")
    with st.expander("👁️ תצוגה מקדימה של הפתרון", expanded=False):
        for step in q.solution_steps:
            st.markdown(f"**[{step.section_id}] {step.step_title}:** {step.content}")
            if step.final_answer:
                st.success(f"תשובה סופית: {step.final_answer}")
    if q.verification is not None:
        ver_rows = [{"סעיף": i.section_id, "תשובת הבודק": i.independent_final_answer, "תשובה במפתח": i.proposed_final_answer,
                     "תשובה": "✅" if i.agrees else "❌", "דרך": "✅" if i.reasoning_agrees else "❌",
                     "מקור": "✅" if i.source_text_agrees else "❌", "הערה": i.comment} for i in q.verification.items]
        if ver_rows:
            st.dataframe(pd.DataFrame(ver_rows), hide_index=True, width="stretch")
        if q.verification.notes:
            st.caption(q.verification.notes)
        disagree = (
            not q.verification.overall_agrees
            or not q.verification.reasoning_agrees
            or not q.verification.source_reconstruction_agrees
            or any(not (i.agrees and i.reasoning_agrees and i.source_text_agrees) for i in q.verification.items)
        )
        if disagree:
            st.warning("הבודק העצמאי לא הסכים עם הפתרון. בדקו את החישוב לפני ההפקה.")
    elif q.verification_error:
        st.warning(q.verification_error)
    else:
        st.caption("לא בוצעה בדיקה עצמאית לשאלה זו.")
    init_key(f"tv_{v}", q.teacher_verified)
    checked = st.checkbox("אימתתי ידנית את הפתרון של שאלה זו", key=f"tv_{v}")
    if checked and (not q.teacher_verified or not q.teacher_verified_fp):
        core.mark_teacher_verified(q)                     # binds the confirmation to THIS math content
    elif not checked:
        q.teacher_verified, q.teacher_verified_fp = False, ""
    elif q.teacher_verified_fp != core.verification_fingerprint(q):
        st.warning("המתמטיקה או מבנה הסעיפים שונו אחרי האימות — בטלו וסמנו מחדש את תיבת האימות.")

    with st.expander("תמונות המקור", expanded=False):
        cols = st.columns(min(3, max(1, len(images))))
        for i, img in enumerate(images):
            cols[i % len(cols)].image(img, caption=f"תמונת מקור {i + 1}", width="stretch")


def reading_panel(q: "core.QuestionAnalysis", source: dict[str, Any]) -> None:
    """Second, independent reading of the source vs the reconstruction: every disagreement with its photo crop."""
    import reading
    check = q.reading_check or {}
    if not check:
        return
    st.markdown("**קריאה עצמאית של המקור**")
    if check.get("error"):
        st.error(f"הקריאה העצמאית נכשלה: {check['error']} — יש לבדוק את השאלה מול המקור ולאשר ידנית.")
        return
    report = reading.refresh_report(q) or {}
    who = {"pdf-text-layer": "שכבת הטקסט של ה-PDF", "gemini-lines": "קריאה שנייה (Gemini, שורה-שורה)",
           "claude-lines": "קריאה שנייה (Claude, שורה-שורה)"}.get(check.get("reader", ""), check.get("reader", ""))
    conflicts = report.get("conflicts", [])
    if not conflicts:
        st.success(f"✅ השחזור תואם ל{who} (כיסוי {report.get('coverage', 0):.0%}).")
        return
    st.warning(f"⚠️ {len(conflicts)} אי-התאמות מול {who}. תקנו את הנוסח (הבדיקה מתעדכנת מעצמה) או אשרו ידנית.")
    images = source.get("images", [])
    for k, cf in enumerate(conflicts[:30]):
        with st.container(border=True):
            st.markdown(cf["message"].split(": ", 1)[-1])
            idx, box = cf.get("image_index"), cf.get("norm_bbox") or []
            if idx and len(box) == 4 and 0 < idx <= len(images):
                try:
                    st.image(core.crop_figure_bytes(images[idx - 1], box, max_side=None), width="stretch")
                except Exception:
                    pass


def step4() -> None:
    st.title("שלב 4: בקרת איכות ועריכה")
    exam: ExamAnalysis | None = S.processed_exam
    if exam is None:
        st.error("אין נתוני פענוח.")
        if st.button("חזור לשלב 3"):
            go(3)
            st.rerun()
        return
    meta = S.exam_meta
    ep = S.editor_epoch
    with st.expander("כותרות המסמך", expanded=False):
        for field, label in [("translated_exam_name", "שם הבחינה במסמך"), ("translated_grade", "שכבה במסמך"),
                             ("translated_level", "רמה במסמך")]:
            init_key(f"{field}_{ep}", getattr(exam, field))
            setattr(exam, field, st.text_input(label, key=f"{field}_{ep}"))
        init_key(f"instr_{ep}", exam.translated_instructions)
        exam.translated_instructions = st.text_area("הוראות הבחינה במסמך", key=f"instr_{ep}", height=160)

    source_by_num = {int(q["question_number"]): q for q in S.questions_data}
    q_options = [str(q.question_number) for q in exam.questions]
    sel_key = f"quality_question_{ep}"
    if str(S.get(sel_key, q_options[0])) not in q_options:
        S[sel_key] = q_options[0]
    # Labels must stay constant: a label that changes (e.g. a ⚠️ that disappears after re-analysis)
    # makes Streamlit lose the option and crash with "'שאלה N' is not in list".
    selected_num = int(st.radio("בחר שאלה לעריכה", q_options, horizontal=True, key=sel_key,
                                format_func=lambda n: f"שאלה {n}"))
    failed_now = [q.question_number for q in exam.questions if q.analysis_error]
    if failed_now:
        st.caption("⚠️ שאלות שלא פוענחו: " + ", ".join(map(str, failed_now)))
    selected_q = next(q for q in exam.questions if q.question_number == selected_num)
    question_editor(selected_q, source_by_num.get(selected_q.question_number, {}))

    errors, warnings = core.validate_exam(exam, meta, S.questions_data)
    st.divider()
    if errors:
        st.error("יש לתקן לפני הפקה:\n\n" + "\n".join(f"- {e}" for e in errors))
    else:
        st.success("כל בדיקות החובה עברו.")
    if warnings:
        with st.expander(f"הערות שאינן חוסמות ({len(warnings)})"):
            for w in warnings:
                st.write("• " + w)
    b1, b2 = st.columns(2)
    if b1.button("➡️ חזור לפענוח"):
        go(3)
        st.rerun()
    if b2.button("אישור והפקת קבצים ⬅️", type="primary", disabled=bool(errors)):
        go(5)
        st.rerun()


# ==================================================================
# Step 5 — documents
# ==================================================================
def docs_signature(exam: ExamAnalysis, meta: dict[str, Any], show_topic: bool) -> str:
    h = hashlib.sha256()
    h.update(exam.model_dump_json().encode())
    h.update(json.dumps({k: v for k, v in meta.items() if k != "logo_bytes"}, ensure_ascii=False, sort_keys=True).encode())
    h.update(core.image_digest(meta.get("logo_bytes") or b"").encode())
    for q in S.questions_data:
        for img in q["images"]:
            h.update(core.image_digest(img).encode())
    h.update(str(show_topic).encode())
    return h.hexdigest()


def workspace():
    """Per-session workspace (heavy exports are files, not session_state blobs)."""
    from workspace import SessionWorkspaceManager, cleanup_stale

    if "ws_id" not in S:
        S.ws_id = __import__("uuid").uuid4().hex
        cleanup_stale()
    return SessionWorkspaceManager(S.ws_id)


class _Paths(dict):
    """dict of kind -> file path whose item access returns the file BYTES (download buttons stay unchanged)."""

    def __getitem__(self, key):
        return Path(dict.__getitem__(self, key)).read_bytes()


def step5() -> None:
    st.title("שלב 5: הפקת הקבצים")
    exam: ExamAnalysis = S.processed_exam
    meta = S.exam_meta
    errors, _ = core.validate_exam(exam, meta, S.questions_data)
    if errors:
        st.error("הנתונים אינם עוברים בדיקה — חזרו לשלב 4.")
        if st.button("חזור לעריכה"):
            go(4)
            st.rerun()
        return
    show_topic = st.checkbox("הצג את נושא השאלה גם בטופס הבחינה לתלמיד", value=False, key="show_topic")
    sig = docs_signature(exam, meta, show_topic)
    cache = S.docs_cache
    if cache.get("sig") != sig:
        with st.spinner("מייצר מסמכי Word..."):
            docs, warns = {}, []
            for kind in ("exam", "solution", "rubric"):
                data, w = core.create_word_document(exam, meta, S.questions_data, kind, show_topic_in_exam=show_topic)
                docs[kind] = workspace().store(f"{sig[:16]}_{kind}.docx", data)     # file on disk, only the path in session
                warns += w
        workspace().invalidate("pdf_")
        S.docs_cache = cache = {"sig": sig, "docx": _Paths(docs), "warnings": warns, "pdf": {}}
    if cache["warnings"]:
        with st.expander(f"⚠️ הערות הפקה ({len(cache['warnings'])})"):
            for w in cache["warnings"]:
                st.write("• " + w)

    base = core.sanitize_filename(exam.translated_exam_name or "מבחן")
    names = {"exam": "מבחן", "solution": "פתרונות", "rubric": "מחוון"}
    mime_docx = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    st.subheader("Word לעריכה")
    cols = st.columns(3)
    for col, kind in zip(cols, names):
        col.download_button(f"⬇️ {names[kind]} (Word)", cache["docx"][kind], file_name=f"{base}_{names[kind]}.docx",
                            mime=mime_docx, width="stretch", key=f"dl_docx_{kind}", on_click="ignore")

    st.subheader("PDF להדפסה")
    if core.soffice_executable() is None:
        st.info("LibreOffice אינו מותקן בסביבה ולכן PDF אינו זמין (ב-Streamlit Cloud הוא מותקן דרך packages.txt).")
    else:
        if not cache["pdf"] and st.button("🖨️ הפק PDF", type="primary"):
            pdfs = {}
            with st.spinner("ממיר ל-PDF..."):
                for kind in names:
                    pdf, err = core.docx_to_pdf_bytes(cache["docx"][kind], f"{base}_{names[kind]}")
                    if pdf is None:
                        st.error(f"{names[kind]}: {err}")
                    else:
                        pdfs[kind] = pdf
            cache["pdf"] = _Paths({k: workspace().store(f"pdf_{sig[:16]}_{k}.pdf", v) for k, v in pdfs.items()})
        if cache["pdf"]:
            cols = st.columns(3)
            for col, kind in zip(cols, names):
                if kind in cache["pdf"]:
                    col.download_button(f"⬇️ {names[kind]} (PDF)", cache["pdf"][kind], file_name=f"{base}_{names[kind]}.pdf",
                                        mime="application/pdf", width="stretch", key=f"dl_pdf_{kind}", on_click="ignore")

    zip_key = f"zip_{len(cache['pdf'])}"
    if zip_key not in cache:  # build once: identical bytes on every rerun keep the download link stable
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for kind in names:
                doc_info = zipfile.ZipInfo(f"{base}_{names[kind]}.docx", date_time=(2026, 1, 1, 0, 0, 0))
                doc_info.compress_type = zipfile.ZIP_DEFLATED
                zf.writestr(doc_info, cache["docx"][kind])
                if kind in cache["pdf"]:
                    pdf_info = zipfile.ZipInfo(f"{base}_{names[kind]}.pdf", date_time=(2026, 1, 1, 0, 0, 0))
                    pdf_info.compress_type = zipfile.ZIP_DEFLATED
                    zf.writestr(pdf_info, cache["pdf"][kind])
        cache[zip_key] = buf.getvalue()
    n_figs = sum(len(q.figures) for q in exam.questions)
    if n_figs:
        if "diagram_bundle" not in cache:
            cache["diagram_bundle"] = diagram_ui.bundle(exam, S.questions_data)
        st.download_button(f"🗂️ חבילת ביקורת שרטוטים ({n_figs}) — מקור, JSON, SVG, PNG ותוצאות בדיקה", cache["diagram_bundle"],
                           file_name=f"{base}_שרטוטים.zip", mime="application/zip", key="dl_diagrams", on_click="ignore")
    st.download_button("📦 הורד הכל (ZIP)", cache[zip_key], file_name=f"{base}.zip", mime="application/zip", key="dl_zip",
                       on_click="ignore")

    st.divider()
    b1, b2 = st.columns(2)
    if b1.button("➡️ חזור לעריכה"):
        go(4)
        st.rerun()
    if b2.button("🆕 צור מבחן חדש"):
        keep = {k: meta.get(k) for k in ("school_name", "teacher_name", "logo_bytes", "language")}
        api_key = S.api_key
        for key in list(S.keys()):
            del S[key]
        init_state()
        S.exam_meta = keep
        S.api_key = api_key
        st.rerun()


{1: step1, 2: step2, 3: step3, 4: step4, 5: step5}[S.step]()

