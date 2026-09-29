# CHANGELOG — 5.7.2 (remaining verified gaps only)

| Issue | Confirmed in 5.7.1? | Fix | Regression test | Status |
|---|---|---|---|---|
| Real E2E bypassed PASS 1 / used manual text | yes (harness fed manifest text to PASS 2) | eval/real_eval.py starts from 16 full source pages (200 dpi) through analyze_question: PASS 1 → bbox → master ROI → PASS 2 → pipeline; PASS1/PASS2/SAFETY metrics; stability; holdout slot | test_real_full_e2e_pass1_to_pass2 (spy proves no manual text is sent), test_eval_sets_have_exact_real_pages... | DONE (not run on the real API) |
| Bar CV unused in production | yes | pipeline: bar_cv.verify → VERIFIED / PARTIAL_BAR_VERIFICATION / CONFLICT / BAR_CV_UNAVAILABLE; conflicts block | test_bar_cv_pipeline_integration_and_category_binding, test_bar_conflict_blocks_approval... | DONE |
| Bar values without category binding; reverse-order acceptance | yes | category OCR per bar + fuzzy binding; axis-direction order; no blind reverse | test_bar_category_binding_catches_swapped_values... | DONE |
| 3D visibility camera ≠ render projection | yes (oblique() positions) | scene_camera: one camera → positions, depth, visibility; manifest projection_source == visibility_camera | test_camera_projection_visibility_consistency ×3 | DONE |
| Perspective back-face test used a constant view direction | found in 5.7.2 | per-face view vector | test_camera_rotation_same_source_of_truth (ray-cast ground truth, 8 cameras) | DONE |
| Cylinder bypasses generic camera | yes | CYLINDER_GENERIC_CAMERA_UNSUPPORTED → teacher (fail closed) | test_cylinder_projection_policy | DONE (limitation declared) |
| All subpart facts reconstruction-critical | yes ("מצא את AD" blocked a correct figure) | split_by_role: requests → REQUIRED_FOR_SOLUTION (non-blocking); declarative subparts → REQUIRED_FOR_RECONSTRUCTION | test_solution_only_fact_does_not_block, test_required_fact_reconstruction_vs_solution, test_section_only_FE_is_required | DONE |
| "מאונך ל-BC" (hyphen) unparsed | found in 5.7.2 | parser pattern | test_hebrew_parser_v2 (2 new cases) | DONE |
| Geometry lengths/angles not OCR-verified | yes | ocr/verify: length_labels, dimensions, angle values (° substitutions); CONFIRMED / CONFLICT / OCR_UNRESOLVED | test_geometry_length_ocr_conflict, test_geometry_angle_ocr_conflict, test_ocr_failure_is_unresolved... | DONE |
| Topology = circle count only | yes | junctions, degrees, connected components; gating only where measured reliable (generic, geometry without circles) | test_topology_junction_mismatch, test_topology_connectivity_mismatch | PARTIAL (circle/3D report-only) |
| No pixel-level graph evidence | yes | graph_cv: branches + x-axis contacts vs analytic model; gating for formula graphs | test_graph_cv_axis_crossing, test_graph_cv_branch_count | PARTIAL (schematic report-only) |
| Inflection / concavity missing | yes | function_validator.concavity (sign change required; poles excluded); marked inflection checked | test_analytic_inflection_validation ×6, test_analytic_concavity_intervals | DONE |
| Table semantics only in unit tests | yes | pipeline table_semantic (frequency vs generic); OCR conflicts named by headers | test_table_semantic_mapping_pipeline | DONE |
| SVG in DOCX not structurally tested | yes | — (no code bug) | test_docx_contains_real_svg (part, rel, content type, svgBlip refs) | DONE |
| UI claimed automatic raster | yes (9 messages) | messages match the fail-closed policy; LEGACY-only texts labelled | test_exam_quality_ui_does_not_claim_auto_raster | DONE |
| Voxel edge cases | — | none needed | test_voxel_edge_cases | DONE |
| Scale invariance end-to-end | partially | none needed | test_real_scale_regression_same_decision ×4 | DONE |
