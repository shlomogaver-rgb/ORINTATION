# REAL IMAGE ACCEPTANCE REPORT — V5.7

Source images: figure crops extracted from the six supplied Bagrut questionnaires (vector PDFs, 170 dpi).
Pipeline: the PRODUCTION pipeline (no ground truth passed in). Result checked afterwards against hand-authored manifests
(`tests/acceptance_real/manifests/*_expected.json`).

**NOT TESTED – REAL VISION EXTRACTION:** no Gemini credentials/network in this environment. The structured proposal fed
to the pipeline is a SIMULATED vision proposal written by hand (`tests/diagram_engine/acceptance/cases.py`). Text parsing,
deterministic CV (scatter), validation, rendering, comparison, decision and export gating are REAL.

| Test | Source | Class / subtype | Req. facts | Text facts | CV/math facts | Vision-only | Indep. coverage | Ambig. | Contradictions | Critical | Decision | Final conf. | Export before / after approval | Result |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A01 | q14_p2_8.png | graph / qualitative_graph | 3 | 2 | 0 | 2 | 50% | 0 | 0 | 0 | review | 0.5 | no / yes | **PASS** |
| A02 | q16_p7_3.png | graph / multi_choice_graphs | 4 | 5 | 0 | 4 | 50% | 0 | 0 | 0 | review | 0.5 | no / yes | **PASS** |
| A03 | q14_p3_4.png | graph / multi_choice_graphs | 4 | 5 | 0 | 4 | 50% | 0 | 0 | 0 | review | 0.5 | no / yes | **PASS** |
| A04 | q14_p7_3.png | graph / formula_graph | 1 | 5 | 0 | 0 | 100% | 0 | 0 | 0 | review | 0.9 | no / yes | **PASS** |
| A05 | q16_p3_2.png | chart / scatter_plot | 0 | 0 | 6 | 0 | 100% | 0 | 0 | 0 | review | 0.9 | no / yes | **PASS** |
| A06 | q16_p8_2.png | generic / schematic | 9 | 8 | 4 | 0 | 100% | 0 | 0 | 0 | review | 0.9 | no / yes | **PASS** |
| A07 | q18_p12_4.png | table / numeric_table | 0 | 0 | 0 | 7 | 53% | 0 | 0 | 0 | review | 0.533 | no / yes | **PASS** |
| A07b | q19_p4_6.png | table / numeric_table | 0 | 0 | 0 | 6 | 50% | 0 | 0 | 0 | review | 0.5 | no / yes | **PASS** |
| A08 | q16_p5_2.png | geometry / analytic_geometry | 14 | 36 | 19 | 6 | 74% | 0 | 1 | 0 | review | 0.739 | no / yes | **PASS** |
| A09 | q15_p2_6.png | spatial / cuboid | 8 | 8 | 8 | 12 | 40% | 0 | 0 | 0 | review | 0.4 | no / yes | **PASS** |
| A09b | q17_p3_2.png | spatial / vector_box | 8 | 9 | 9 | 14 | 39% | 0 | 3 | 0 | review | 0.391 | no / yes | **PASS** |
| A10 | q15_p5_5.png | graph / multi_choice_graphs | 4 | 5 | 0 | 4 | 50% | 0 | 0 | 0 | review | 0.5 | no / yes | **PASS** |
| A11 | q19_p8_4.png | chart / normal_distribution_schematic | 0 | 0 | 0 | 2 | 83% | 0 | 0 | 0 | review | 0.833 | no / yes | **PASS** |
| A12 | q19_p12_2.png | spatial / voxel_structure | 0 | 0 | 0 | 0 | 0% | 0 | 2 | 0 | original | 0.0 | no / — | **SAFE FALLBACK PASS** |
| A13 | q19_p14_2.png | spatial / cylinder_in_box | 3 | 3 | 3 | 4 | 43% | 0 | 2 | 0 | review | 0.429 | no / yes | **PASS** |
| A14 | q14_p5_2.png | geometry / circle_geometry | 14 | 31 | 22 | 9 | 65% | 1 | 0 | 0 | review | 0.654 | no / yes | **PASS** |
