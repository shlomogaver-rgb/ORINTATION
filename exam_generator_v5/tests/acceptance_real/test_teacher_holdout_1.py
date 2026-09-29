"""FORMER HOLDOUT #1: five teacher screenshots (box+vectors, |f| options, log options, circle+equilateral, cubic+line).
First blind run (BLIND_RUN_1.json): 0 wrong accepted, 2 FALSE BLOCKS, 3 false contradictions, 6 unparsed formulas.
The generic fixes they exposed are tested here and in test_holdout1_generalization; this set is now REGRESSION."""
from __future__ import annotations

import io
import re
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
D = Path(__file__).parent / "teacher_holdout_1"
sys.path.insert(0, str(ROOT))
IMGS = ["h1_box_vectors.png", "h2_abs_options.png", "h3_log_options.png", "h4_circle_equilateral.png", "h5_cubic_line.png"]


@pytest.fixture(scope="module")
def built():
    import importlib.util

    import diagram_engine as de
    import exam_core as c
    from diagram_engine.schemas import DiagramSpec
    spec_ = importlib.util.spec_from_file_location("holdout1_content", D / "content.py")
    content = importlib.util.module_from_spec(spec_)
    spec_.loader.exec_module(content)
    qs, recs = [], []
    for i, raw in enumerate(content.QUESTIONS):
        img = (D / IMGS[i]).read_bytes()
        q = c.postprocess_question(c.QuestionAI.model_validate(raw), i + 1, 20.0, 1)
        q.analysis_input_hashes = [c.image_digest(img)]
        for f, spec in zip(q.figures, content.SPECS.get(i + 1, [])):
            q.diagram_specs[f.figure_id] = DiagramSpec.model_validate(spec)
        c.attach_diagrams(q, [img], masters=[img])
        c.check_formulas(q, None)
        for f in q.figures:
            rec = q.diagrams[f.figure_id]
            recs.append((i + 1, rec, de.approve(rec)))
        q.teacher_verified = True
        qs.append(q)
    exam = c.ExamAnalysis(translated_exam_name="", translated_grade="", translated_level="", translated_instructions="",
                          labels=c.HEBREW_LABELS, questions=qs)
    meta = {"school_name": "", "exam_name": "t", "grade": "", "level": "5", "teacher_name": "", "duration": 180, "num_questions": 5,
            "language": "עברית", "date": "", "instructions": "", "choice_groups": [], "logo_bytes": None}
    qd = [{"question_number": i + 1, "points": 20.0, "images": [(D / IMGS[i]).read_bytes()]} for i in range(5)]
    return exam, meta, qd, recs


def test_all_five_reconstructions_are_approvable_without_false_conflicts(built):
    *_, recs = built
    assert len(recs) == 5
    for qn, rec, ok in recs:
        assert ok and rec.decision.action != "original" and not rec.comparison.critical and not rec.validation.errors, (qn, rec.decision)
        assert not [x for x in rec.contradictions if "MISSING_FROM_SPEC" in x], (qn, rec.contradictions)


def test_every_formula_parsed_and_the_exam_validates(built):
    import exam_core as c
    exam, meta, qd, _ = built
    assert all(f["status"] == "OK" for q in exam.questions for f in q.formula_checks)
    assert c.validate_exam(exam, meta, qd)[0] == []


def test_word_output_is_vector_and_native(built):
    import exam_core as c
    exam, meta, qd, _ = built
    data, warns = c.create_word_document(exam, meta, qd, "exam")
    z = zipfile.ZipFile(io.BytesIO(data))
    xml = z.read("word/document.xml").decode()
    pics = re.findall(r"<pic:pic>.*?</pic:pic>", xml, re.S)
    assert len(pics) == 5 and all("svgBlip" in p for p in pics)             # every figure redrawn, none is a source image
    assert xml.count("<m:oMath") >= 80 and "<m:acc>" in xml and "<m:bar>" in xml   # vectors / underlines as native Word math
    assert not warns
