# Real-model evaluation
* `fixed_regression_set` = the 16 figures of the six supplied questionnaires (manifests in tests/acceptance_real/manifests).
* `holdout/` = put UNSEEN real images here as `<id>.png` + `<id>_expected.json` (hand-written; same format as the manifests,
  plus `question_text`). If a holdout image is used for development, move it to the regression set and add a new one.
* Run: `GEMINI_API_KEY=... python eval/real_eval.py --runs 5 --set fixed` (and `--set holdout`).
* Status in this delivery: harness implemented and tested against the mock client; **NOT RUN against the real API**
  (no credentials / network in the build environment). The holdout folder is EMPTY: new real images are needed.
