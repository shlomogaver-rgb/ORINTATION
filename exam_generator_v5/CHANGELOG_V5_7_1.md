# CHANGELOG — 5.7.1 (reliability closure)

| File | Function/Class | Old behaviour | New behaviour | Reason |
|---|---|---|---|---|
| exam_core.py | image_to_png_bytes / add_images (app) | every upload downsampled to 2600 px | ORIGINAL_MASTER kept full-res; working derivative ≤2600 | no early information destruction |
| image_store.py (new) | ImageItem / ImageStore | full image bytes + 3 history frames in session_state | versioned files on disk, ids in session, edit ops recorded | memory + master replay |
| exam_core.py | crop_normalized, apply_master_op, figure_source_crop | ROI from the working image | ROI cropped from the master-edited asset | high-res recognition |
| exam_core.py | extract_diagrams_pass2, DIAGRAM_SYSTEM_PROMPT | one call returned text AND diagram (spec_json string) | PASS 1 text only; PASS 2 separate typed call per ROI | no correlated failure / no JSON string |
| diagram_engine/ai_schema.py (new) | AIDiagramSpec, to_spec | — | Gemini-safe schema derived from DiagramSpec | native structured output |
| exam_core.py | figure_bytes_for_document | approved + render failure → original crop | EXPORT_BLOCKED + placeholder | no automatic raster |
| exam_core.py | embed_svg_in_picture | PNG only in DOCX | SVG (svgBlip) primary, PNG fallback; PDF vector | vector export |
| exam_core.py | paginate_questions | uncontrolled page splits | question = unit; long questions split between subparts only | pagination |
| diagram_engine/text_facts.py | P regex, dimensions | A''/A_1 collided; ordinal/entity missing; ס''מ | prime-safe ids; entity_index; morphology; extents | parser |
| diagram_engine/verification.py | target_entity_ids, extent checks | dimension bound by kind only | exact entity id; ambiguity → review; SEGMENT/RAY/LINE | binding |
| diagram_engine/graph/function_validator.py (new) | check_points, text_claims | — | MATHEMATICAL_CONFLICT / SOURCE_CONFLICT (no auto-fix) | symbolic validation |
| diagram_engine/ocr/verify.py | run | verified only AI-proposed labels; failure = no text | source label inventory (MISSING_FROM_SPEC); states | independent OCR |
| diagram_engine/ocr/engine.py | _img, cell/region scaling, budget | fixed 3×/4× upscale, pixel thresholds | resolution-normalized; budget/regions/PSM caps; cache by config | DPI independence, performance |
| diagram_engine/topology_extractor.py (new) | extract/compare | — | independent circle counts (reliable families only) | topology |
| diagram_engine/geometry/solver.py | derived_points, solve | midpoint/ratio only; no degeneracy code | + intersection, foot, centroid, circum/incenter, 3-point circle centre; DEGENERATE_GEOMETRY; pinned drag | exact construction |
| diagram_engine/graph/evaluator.py | branch_samples | linspace + jump cut | branch-aware adaptive sampling + viewport clipping | no spikes / no cross-branch lines |
| diagram_engine/graph/qualitative_parser.py | validate | could draw an unmarked root | SCHEMATIC_ROOT_MISMATCH | no invented roots |
| diagram_engine/charts/bar_cv.py (new) | detect/compare | bar values AI-only | CV + OCR tick calibration, vertical/horizontal | independent numbers |
| diagram_engine/spatial/camera.py, voxel_scene.py (new) | Camera, edge_visibility, LabelPlacer, VoxelGrid | hidden edges from the AI; fixed projection; x+y order | computed hidden lines, partial occlusion, cameras, views, delta | 3D integrity |
| diagram_engine/notation.py (new) | Profile, apply_profile, inconsistencies | — | semantic MEAN/SD, ISRAEL_HIGH_SCHOOL x̄/S, SOURCE_FAITHFUL, gate | localization |
| diagram_engine/fact_graph.py | Fact, reconciliation | — | provider/pass_id, criticality, per-fact status | evidence independence |
| components/geo_drag (new), diagram_ui.py | drag editor, LaTeX editor, text panel | freedraw canvas | real SVG drag component, solver re-imposes constraints; LaTeX preview | teacher review |
| eval/real_eval.py (new) | harness | — | real-API eval, raw outputs, metrics, 5-run stability | release evidence |
Dependencies: none new at runtime beyond 5.7 (pytesseract, opencv-python-headless, Tesseract packages).
