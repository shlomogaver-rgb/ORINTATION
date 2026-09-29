"""MODE B acceptance: the six supplied full exam PDFs -> FullDocumentModel (structure; formulas/visual semantics need the
real model). Ground truth: tests/documents/expected_structure.json (hand-authored)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from document import PageRole, VisualRole, build_document  # noqa: E402

DOCS = ROOT / "tests" / "documents"
EXP = json.loads((DOCS / "expected_structure.json").read_text(encoding="utf-8"))
BBOX = json.loads((DOCS / "figure_bboxes_pt.json").read_text(encoding="utf-8"))
PDFS = [k for k in EXP if k.endswith(".pdf")]


@pytest.fixture(scope="module")
def models():
    return {name: build_document((DOCS / name).read_bytes()) for name in PDFS}


@pytest.mark.parametrize("name", PDFS)
def test_question_count_and_sequence(models, name):
    m = models[name]
    assert [q.number for q in m.questions] == list(range(1, EXP[name]["questions"] + 1))
    assert not any("QUESTION_COUNT_MISMATCH" in w for w in m.warnings)


@pytest.mark.parametrize("name", PDFS)
def test_cross_page_continuity(models, name):
    m = models[name]
    for qn, pages in EXP[name]["multi_page"].items():
        q = next(q for q in m.questions if q.number == int(qn))
        assert q.pages == pages and q.continuation_metadata["spans_pages"]


@pytest.mark.parametrize("name", PDFS)
def test_page_roles(models, name):
    m = models[name]
    roles = {p.index: p.role for p in m.pages}
    for p in EXP[name]["workspace_pages"]:
        assert roles[p] == PageRole.RESPONSE_WORKSPACE, (p, roles[p])
    for p in EXP[name].get("admin_pages", []):
        assert roles[p] == PageRole.ADMINISTRATIVE
    for p in EXP[name].get("draft_pages", []):
        assert roles[p] in (PageRole.DRAFT, PageRole.RESPONSE_WORKSPACE)
    first_q = min(q.start["page"] for q in m.questions)
    assert all(roles[i] in (PageRole.INSTRUCTIONS, PageRole.ADMINISTRATIVE) for i in range(1, first_q))
    for q in m.questions:
        for v in q.response_regions:
            assert v.visual_role in (VisualRole.RESPONSE_TEMPLATE, VisualRole.ANSWER_BOX, VisualRole.GRAPH_PAPER, VisualRole.ANSWER_WORKSPACE)


@pytest.mark.parametrize("name", PDFS)
def test_known_figures_bound_to_the_right_question(models, name):
    m = models[name]
    for fig, qn in EXP[name]["figures"].items():
        page = int(fig.split("_")[1][1:])
        x0, y0, x1, y1 = BBOX[fig]
        hits = []
        for q in m.questions:
            for v in q.visual_objects:
                ox = max(0, min(x1, v.bbox[2]) - max(x0, v.bbox[0]))
                oy = max(0, min(y1, v.bbox[3]) - max(y0, v.bbox[1]))
                if v.page == page and ox * oy > 0.2 * (x1 - x0) * (y1 - y0):
                    hits.append(q.number)
        assert hits and set(hits) == {qn}, (fig, hits, qn)


def test_generalises_to_an_unseen_synthetic_document():
    """Rules never tuned on this: other font, 4 questions over 3 pages, an empty answer box."""
    import pymupdf
    doc = pymupdf.open()
    for _ in range(3):
        page = doc.new_page(width=595, height=842)
        page.insert_text((250, 30), "Sample exam header", fontname="helv", fontsize=8)
    doc[0].insert_text((545, 120), "1.", fontname="helv", fontsize=12)
    doc[0].insert_text((545, 400), "2.", fontname="helv", fontsize=12)
    doc[1].insert_text((545, 300), "3.", fontname="helv", fontsize=12)
    doc[2].insert_text((545, 200), "4.", fontname="helv", fontsize=12)
    doc[0].draw_rect(pymupdf.Rect(100, 600, 450, 760), color=(0, 0, 0), width=1)
    m = build_document(doc.tobytes())
    assert [q.number for q in m.questions] == [1, 2, 3, 4]
    q2 = m.questions[1]
    assert any(v.visual_role == VisualRole.ANSWER_BOX for v in q2.response_regions) and not q2.visual_objects
