# DELIVERY REPORT — 5.7.4 (production wiring; question-to-clean-exam)

Product definition followed: the PRIMARY product is QUESTION → CLEAN EXAM (teacher pastes/uploads questions from any source,
sometimes PDF). Full-document import is SECONDARY and serves question extraction + evidence.

## A. Production wiring matrix
| Feature | Engine | AI schema (PASS 2) | Production parser/bridge | Validator | Renderer | DOCX | Tests | Status |
|---|---|---|---|---|---|---|---|---|
| Complex numbers (rect/polar/roots → Gauss-plane polygon) | yes | `semantics.complex_plane` | bridge BUILDS geometry or VERIFIES points | COMPLEX_POINT_CONFLICT critical | geometry SVG | yes | unit+schema+pipeline+variants | **PRODUCTION WIRED** (real model not run) |
| Conics (circle/ellipse/parabola/hyperbola) | yes | `semantics.conics` | bridge BUILDS graph or VERIFIES foci/kind | CONIC_* critical | exact branches, SVG | yes | 5 kinds + conflicts + unsupported | **PRODUCTION WIRED** (loci: engine only) |
| Vectors (symbol ↔ edge ↔ coordinates) | yes | `semantics.vectors` | claim verification (parallel/perp/ratio/combination) | SEMANTIC_CLAIM_CONFLICT | — (no drawing built from vectors) | via existing spatial | 5 claims | **PARTIALLY WIRED** |
| Analytic 3D (points/lines/planes, angles, distances) | yes | `semantics.space3d` | claim verification | SEMANTIC_CLAIM_CONFLICT | existing camera renderer (not built from Space3D) | via spatial | 4 claims | **PARTIALLY WIRED** |
| Function dependency graph | yes | `semantics.function_relations` | checked on the DRAWN curves | FUNCTION_RELATION_CONFLICT | graph | yes | 4 relations | **PRODUCTION WIRED** (verification) |
| ExpressionAST / formulas | new structural parser `latex_ast.py` + SymPy check | `semantics.formulas` (figure) + all question text | every formula of every question (`check_formulas`) | UNPARSED → warning; PDF disagreement → error until teacher confirms | — | OMML still generated from LaTeX (AST validates, does not generate) | 409/409 formulas of 035571; 20 unseen notations; broken → UNPARSED | **PARTIALLY WIRED** |
| Formula cross-validation | — | — | PDF text layer of the question region | FORMULA_UNCERTAIN blocks until teacher_verified | — | — | exponent misread caught | **WIRED for PDF sources**; images: no independent formula evidence |
| Multi-visual + visual→subpart | — | `FigureRef.section_id` | — | — | — | figure placed after its subpart | yes | **PRODUCTION WIRED** |
| k-of-n subparts | — | `QuestionAI.required_sections` | — | points = total/K, rubric = 100·N/K | — | — | yes | **PRODUCTION WIRED** |
| Mode-B document state | FullDocumentModel | — | `document/state.py` single rebuild function | — | — | response templates → empty Word tables | real AppTest UI flow | **PRODUCTION WIRED** |
| PDF question picking (primary PDF use) | — | — | `import_pdf_questions` | — | — | same question pipeline | AppTest mixed exam | **PRODUCTION WIRED** |
| Raw model evidence | — | — | `GeminiService.raw_log` → `q.model_evidence` | — | — | — | yes | **PRODUCTION WIRED** |

## B. Files changed
| File | Function | Old | New | Why |
|---|---|---|---|---|
| app.py | step 3 rebuild | questions_data rebuilt without `document` | `document.state.build_questions_data` re-attaches canonical model | metadata loss (P0, reproduced: KeyError) |
| app.py | import_full_document | wrote live widget key `s1_n` → Streamlit exception | pending value applied before widget creation | real bug found by the UI test |
| app.py | import_pdf_questions (new), step-1 PDF picker | — | pick questions from a PDF into the current exam | primary product flow |
| document/state.py (new) | question_payload, build_questions_data | — | canonical Mode-B state | P0-5/10 |
| document/reconstruct.py | page_master_region | fixed 200-dpi page render as master | vector: 450-dpi ROI from original PDF; scan: original embedded raster, native pixels; text layer per region | P0-8/9 |
| diagram_engine/schemas.py | SemanticSpec (+ items), MultiGraphSpec.rtl | — | typed semantics; RTL options | P0-1/2 |
| diagram_engine/semantic/bridge.py (new) | apply | engines used only by tests | build / verify inside `de.process` | P0-1 |
| diagram_engine/pipeline.py | process/_finish | semantic results could be lost on early exits | merged into EVERY decision | found while wiring |
| diagram_engine/latex_ast.py (new) | Parser | only algebra via SymPy (44% of real formulas) | structural LaTeX → AST for all exam notation | P0-3 |
| diagram_engine/formula_pipeline.py (new) | analyse, cross_check | — | AST + symbolic check + PDF cross-validation; never crashes | P0-3/4 |
| diagram_engine/text_facts.py | clauses | "נסמן …" = given; split at ":" turned claims into givens | DEFINITION clauses; colon never splits | bugs found by the 035571 run |
| diagram_engine/verification.py | extent | "הישר AD" vs drawn segment = hard block | teacher review (LINEAR_EXTENT_REVIEW) | Hebrew usage |
| exam_core.py | FigureRef.section_id, required_sections, check_formulas, add_figures(section), validate_exam, GeminiService.raw_log, PROMPT_VERSION, add_response_templates | — | see matrix | P0/P1 |
| graph/renderer.py | render_multi | options left→right | right→left (Hebrew) | demo finding |
| requirements.txt | — | pymupdf missing | pymupdf==1.28.2 | deployment bug |
| tests/conftest.py (new) | — | missing deps looked like failures | NOT RUN — dependency unavailable, reported | P2-25 |

## C. Real question pipeline (and Mode-B state)
IMAGE/PDF question → (PDF: region from the ORIGINAL PDF at 450 dpi / original scan pixels, text layer kept as evidence) →
image store master → PASS 1 (QuestionAI incl. section_id per figure, required_sections) → formula AST check (+ PDF cross-check) →
PASS 2 on high-res ROI (AIDiagramSpec incl. typed semantics) → semantic bridge (build/verify) → OCR/CV → verification → decision →
teacher approval → Word (native text, OMML, SVG, native tables, empty response templates).
Mode-B state lives in `S.document_model` (+ `document_templates`, `document_text_layers`, `pdf_question_evidence`); every rebuild
goes through `document.state.build_questions_data`.

## D. Formula pipeline (real example, 035571 Q1ב)
source `f(x)=\left(2-\frac{1}{x}\right)^{3}` → latex_ast: Equation[FunctionApplication(f,x), Power(Group(Sum(2, Negative(Fraction(1,x)))), 3)]
→ validate OK → SymPy check OK → OMML (existing LaTeX→OMML) → Word equation. On 035571: 409/409 formulas parsed structurally.

## E. Visual reconstruction pipeline — unchanged (semantic/vector); engines now build complex-plane polygons and conics directly.

## F. Redrawn-from-scratch output — exam 035571: 6 SVG figures, 0 source images (see previous delivery).

## G. Regression from the supplied exams
12 PDFs: structure tests (38) + 035571 through the real pipeline (3: all 6 figures approvable with 0 critical; validate_exam clean;
≥40 OMML equations, 6 SVG, every formula converted) + 16 real crops (acceptance). Several capabilities are tested with the exam
content as ONE instance plus unseen variants (see H).

## H. Unseen generalization tests
Structural LaTeX: 20 notations not used to build the parser (conics, polar complex, vectors, limits, sums, log bases, PQR∼KLM,
probability ∩/|, max, ratios, quadratic formula, nth roots, |x|, binomials, f'', Hebrew \text). Engines: roots of 4 equations,
5 conic types, vector/3D claims with true/false cases. **True holdout of new real exams: NONE (NOT RUN).**

## I. Original failure regressions — all kept (16 crops, 12 PDFs, 035571 demo bugs, swapped-OCR, graph-CV, bar-CV, clause parsing).

## J. Real model E2E — **NOT EXECUTED** (no credentials). Harness keeps raw PASS 1/2 texts, model, prompt version, hashes.
## K. 5-run stability — **NOT EXECUTED**.

## H2. TEACHER HOLDOUT #1 — five unseen teacher screenshots (blind, then fixed → regression)
PASS-1/2 content authored in the model's structure BEFORE any run (no real Gemini). First run with NO code change (BLIND_RUN_1.json):
| # | Source | Blind result | Class |
|---|---|---|---|
| 1 | box + vectors | review, approvable; false MISSING_FROM_SPEC E, F; 6 formulas unparsed (\underline) | SAFE REVIEW |
| 2 | f=(3x²−a)eˣ, |f| options I–IV | BLOCKED: branch toward y=0 "undefined asymptote" | FALSE BLOCK |
| 3 | x²/(−6+4ln x), options I–IV | BLOCKED: default tick step on range [−40, 80] | FALSE BLOCK |
| 4 | equilateral triangle in a circle | review, approvable, 0 conflicts | PASS |
| 5 | (4x−2)³ and y=3x+b | review, approvable; false MISSING_FROM_SPEC 'X' (axis letter) | SAFE REVIEW |
**WRONG_ACCEPTED = 0**; false blocks 2/5. Generic fixes: automatic 1-2-5 tick step (explicit invalid steps still errors); y=0 is the
x-axis asymptote; spatial label inventory includes points on edges/diagonals/segments; axis letters are not entities; structural
parser supports \underline/\overline/\vec…; OMML: vector arrows → m:acc (stretched), over/under lines → m:bar (was a small centred
limUpp/limLow). After fixes: 5/5 approvable, 0 contradictions, 85/85 formulas, exam validates; Word: 5 SVG figures, 85 OMML, 0 source
images. The five images are now REGRESSION (tests/acceptance_real/teacher_holdout_1); **a new holdout is required.**

## Test results (exactly as executed)
| Suite | PASSED | FAILED | SKIPPED | NOT RUN |
|---|---|---|---|---|
| diagram_engine (excl. fuzz/acceptance) | 451 | 0 | 0 | 0 |
| core + app + legacy engine + fuzz | 232 | 0 | 0 | 0 |
| acceptance (16 real crops) + acceptance_real (+035571, +teacher holdout #1) + full-document (6+2 PDFs) | 103 | 0 | 0 | 0 |
| full-document dev (4 PDFs) + Mode-B UI state/pick tests | 14 | 0 | 0 | 0 |
| full PDF → DOCX structural E2E | 1 | 0 | 0 | 0 |
| **Total** | **801** | **0** | **0** | **0** |
Browser E2E (Playwright, real Streamlit): PASSED. compileall OK, ruff (E9,F) clean. Real-model E2E / stability / holdout: NOT RUN.

## L. Remaining limitations / blockers
- Real Gemini PASS 1/2 never executed; 5-run stability not measured; holdout empty.
- OMML is still generated from LaTeX (the AST validates but is not yet the generator).
- For image sources there is no independent formula evidence (only PDF text layers are cross-checked).
- Vectors / 3D analytic verify claims but do not build drawings; conic loci are engine-only.
- Word Desktop / Word Web rendering not verified here.
**Release decision: NOT READY — BLOCKERS REMAIN.**
