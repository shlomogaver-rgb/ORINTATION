"""Regression from the 035571 demonstration (summer 2022): 8 questions / 35 subparts / 6 figures, PASS-1/2 content written
in the model's exact structure, verified against the REAL question crops of the PDF by the real pipeline. This run exposed 3
engine bugs (definition clauses, 'הוכיחו:' split at the colon, LINE-vs-segment wording) - all must stay fixed."""
from __future__ import annotations

import io
import re
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))
pytest.importorskip("pymupdf")


@pytest.fixture(scope="module")
def built():
    import diagram_engine as de
    import exam_core as c
    import exam_035571_content as content
    from diagram_engine.schemas import DiagramSpec
    from document import build_document
    from document.reconstruct import questions_data
    pdf = (ROOT / "tests" / "documents" / "dev" / "questionnaire (22).pdf").read_bytes()
    qd = questions_data(pdf, build_document(pdf))
    for d in qd:
        d["points"] = 20.0
    qs, decisions = [], {}
    for i, raw in enumerate(content.QUESTIONS):
        q = c.postprocess_question(c.QuestionAI.model_validate(raw), i + 1, 20.0, len(qd[i]["images"]))
        q.analysis_input_hashes = [c.image_digest(b) for b in qd[i]["images"]]
        for fig, spec in zip(q.figures, content.SPECS.get(i + 1, [])):
            q.diagram_specs[fig.figure_id] = DiagramSpec.model_validate(spec)
        c.attach_diagrams(q, qd[i]["images"], masters=qd[i]["masters"])
        c.check_formulas(q, qd[i]["document"]["text_layer"])
        for fig in q.figures:
            rec = q.diagrams[fig.figure_id]
            decisions[(i + 1, fig.figure_id)] = (rec.decision.action, list(rec.comparison.critical), de.approve(rec))
        q.teacher_verified = True
        qs.append(q)
    exam = c.ExamAnalysis(translated_exam_name="035571", translated_grade="", translated_level="", translated_instructions="",
                          labels=c.HEBREW_LABELS, questions=qs)
    meta = {"school_name": "", "exam_name": "035571", "grade": "", "level": "5", "teacher_name": "", "duration": 210,
            "num_questions": 8, "language": "עברית", "date": "", "instructions": "",
            "choice_groups": [{"questions": list(range(1, 9)), "required": 5}], "logo_bytes": None}
    return exam, meta, qd, decisions


def test_every_figure_reconstructed_and_approvable(built):
    _, _, _, decisions = built
    assert len(decisions) == 6
    for key, (action, critical, approved) in decisions.items():
        assert action != "original" and not critical and approved, (key, action, critical)


def test_exam_validates_and_word_is_clean(built):
    import exam_core as c
    exam, meta, qd, _ = built
    errors, _ = c.validate_exam(exam, meta, qd)
    assert errors == []
    data, warns = c.create_word_document(exam, meta, qd, "exam")
    z = zipfile.ZipFile(io.BytesIO(data))
    xml = z.read("word/document.xml").decode()
    assert xml.count("<m:oMath") >= 40 and sum(n.endswith(".svg") for n in z.namelist()) == 6
    assert not [w for w in warns if "לא הומרה" in w]                      # every formula became a Word equation


def test_formula_pipeline_on_the_real_exam(built):
    exam, _, _, _ = built
    checks = [f for q in exam.questions for f in q.formula_checks]
    assert len(checks) > 60
    ok = sum(1 for f in checks if f["status"] == "OK") / len(checks)
    assert ok > 0.6, ok                                                       # the rest is shown to the teacher, never trusted silently
