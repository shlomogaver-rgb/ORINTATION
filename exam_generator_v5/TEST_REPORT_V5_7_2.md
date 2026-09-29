# TEST REPORT — 5.7.2
Environment: Linux sandbox, Python 3.12, Streamlit 1.64, Tesseract 5.3.4 (heb+eng), OpenCV 4.13, LibreOffice. Gemini MOCKED.

| Total | Passed | Failed | Skipped |
|---|---|---|---|
| 588 | 588 | 0 | 0 |

Browser E2E (Playwright): PASSED — upload, crop, erase, straighten, undo, analysis, approve, explicit raster override, real mouse
drag in the SVG component (constraint kept, approval invalidated), LaTeX edit, re-approve, Word/PDF/ZIP. compileall OK, ruff clean.

## Real model E2E
| Item | Status |
|---|---|
| PASS 1 (real) | NOT TESTED — no Gemini credentials / network |
| PASS 2 (real) | NOT TESTED |
| 14 (16) original images × 5 runs = 80 real runs | NOT TESTED — harness ready: `GEMINI_API_KEY=... python eval/real_eval.py --runs 5 --set fixed` |
| Holdout | NOT DONE — eval/holdout/index.json is empty (no unseen real images supplied); harness reports it explicitly |
Deterministic pipeline on the 16 real crops with a SIMULATED PASS-2 proposal: 15 PASS + 1 SAFE FALLBACK (REAL_IMAGE_ACCEPTANCE_REPORT_V5_7_2.md).

## Bar CV
| Case | Orientation | Calibration | Categories | Values | Result |
|---|---|---|---|---|---|
| synthetic 4 bars RED/BLUE/GREEN/PINK | VERTICAL | OCR ticks, R² ≥ 0.999 | bound by OCR | match | VERIFIED |
| same, RED/BLUE values swapped in spec | VERTICAL | ok | bound | swapped detected | CONFLICT → blocked |
| horizontal bars | HORIZONTAL | ok | axis order (bottom→top) | match | PARTIAL_BAR_VERIFICATION → review |
| real scanned bar chart | — | — | — | — | NOT TESTED (none supplied) |

## 3D camera consistency
| Camera | Projection source | Visibility source | Depth source | Result |
|---|---|---|---|---|
| OBLIQUE_RIGHT / ISOMETRIC / ORTHO_FRONT | scene camera | same | same | PASS (screen coords == cam.project) |
| PERSPECTIVE ×8 positions | scene camera | same (per-face vectors) | same | PASS vs ray-cast ground truth |
| cylinder under non-oblique camera | — | — | — | CYLINDER_GENERIC_CAMERA_UNSUPPORTED → teacher |

## RequiredFacts criticality
Reconstruction facts: stem + declarative subparts. Solution facts: requests (חשב/מצא/הבע/הוכח…). Context: the rest.
False blocking in tests: 0 (the 5.7.1 false block of "מצא את AD" is fixed). Missed critical subpart fact in tests: 0 (FE declarative blocks).

## OCR coverage (independent)
| Family | Verified | Conflicted | Unresolved | N/A |
|---|---|---|---|---|
| labels (geometry/generic/spatial) | confirmations + MISSING_FROM_SPEC inventory | — | weak letters (A14) | — |
| table cells | numeric cells | yes (header-named) | wrapped Hebrew headers | — |
| percentages (normal) | 11/12 real | yes | 1 | — |
| ticks | scatter axes, bar calibration | — | — | — |
| dimensions (spatial) | values | radius/diameter semantic | — | — |
| lengths / angles (geometry) | yes | LENGTH/ANGLE_VALUE_CONFLICT | OCR_UNRESOLVED | — |
| bar values | CV + OCR ticks | BAR_VALUE_CONFLICT | BAR_CV_UNAVAILABLE | — |

## Topology
Junctions / degrees / components: gating for generic + straight-line geometry (exact match measured on A06, A08); circle geometry and
3D: report-only (A14 correct render 10 vs 5 junctions). Circle counts: gating for geometry. Graph branches / x-axis contacts: gating for
formula graphs (A04 exact), report-only for schematic graphs (A01 unreliable).

## SVG
| Check | Result |
|---|---|
| DOCX SVG part / relationship / content type / svgBlip reference | PASS (structural test) |
| LibreOffice → PDF vector (no raster except logo), 800 % zoom | PASS |
| Word Desktop / Word Web | NOT TESTED (not available) |
