# T02 Raw QC Triage — Individual PoC Report

## 00 · Submission status

| Item | Status |
|---|---|
| Track | T02 · Raw QC Triage |
| Owner | Trinh Xuan Toan · individual implementation |
| Group ID / Git URL | Not provided |
| Demo/final tags | Not created |
| Evaluation date | 2026-11-15 |

This report records the local implementation and reproducibility checks. Official
Defect Recall@20 and Precision@20 are **not reported** because the instructor-only
ground-truth overlay is absent from this student checkout.

## 01 · Problem and policy

Rank raw images likely to be blurred, too dark, or locally saturated so a reviewer
can inspect the 20 highest-risk images first. An incorrect KEEP may release unusable
data; an incorrect RECAPTURE wastes collection time.

The PoC combines normalized heuristic risks:

`score = 0.55 * blur_risk + 0.30 * dark_risk + 0.15 * glare_risk`

Higher scores are reviewed first. These are fixed heuristics, not probabilities and
not trained on the eval split. The release policy is conservative: HOLD while any
item in the 20-image priority queue remains unreviewed or escalated/skipped; REWORK
if a reviewer marks a priority item RECAPTURE; GO if every item in that fixed-budget
queue has been reviewed and marked KEEP. Lower-ranked images remain outside the
review budget.

## 02 · Data and protocol

Input is the synthetic CC0 fixture in `fixtures/t02_raw_qc/`: 96 images at
320×180 with `image_id`, relative path, camera, light, and split metadata.
The split is by source scene:

| Split | N | Day | Dusk | Night | Camera A | Camera B |
|---|---:|---:|---:|---:|---:|---:|
| dev | 56 | 36 | 16 | 4 | 36 | 20 |
| eval | 40 | 20 | 4 | 16 | 28 | 12 |

All 14 fixture manifests verified successfully with
`python -m tools.verify_manifests`. `fixtures/t02_raw_qc/gt/labels.csv` is absent;
the official evaluator therefore exits 2 with the expected “ground truth is not
distributed” message. No hidden-eval score is claimed, and no eval labels were used.

The contract is Defect Recall@B with B=20: defects in the top 20 divided by all
defects in eval, matched by exact `image_id`; Precision@20 is secondary. Protocol,
budget, split, and score weights are recorded in `reports/metric_contract.md`.

## 03 · Baseline and PoC

| Run | Method | Items | Review budget | Status | Runtime |
|---|---|---:|---:|---|---:|
| Baseline | Inverse whole-image Laplacian variance | 96 | 20 | HOLD | 0.5781 s |
| PoC | Blur + dark + saturation heuristic score | 96 | 20 | HOLD | 0.5658 s |

Both runs used the same fixture, seed 42, offline mode, and review budget. Runtime
is end-to-end `src.main` runtime from `run_info.json` on this machine; it is not an
official hardware-normalized benchmark. Eval metric comparison remains pending the
instructor overlay.

The generated PoC score means by light/camera are descriptive score diagnostics,
not accuracy measurements:

| Light | Camera | N | Mean score |
|---|---|---:|---:|
| day | cam_A | 44 | 0.1598 |
| day | cam_B | 12 | 0.2264 |
| dusk | cam_A | 12 | 0.1330 |
| dusk | cam_B | 8 | 0.3224 |
| night | cam_A | 8 | 0.3009 |
| night | cam_B | 12 | 0.2928 |

These slices have not been compared against ground truth; they must not be
interpreted as defect recall or false-alarm rates.

## 04 · Human review and audit

Each run writes `ranked_review.csv`, `review_queue.csv`, an offline
`contact_sheet.html`, `decision.json`, and `decision_log.csv` under its output
directory. Review `approve` maps to KEEP, `reject` maps to RECAPTURE, and `edit`
requires an explicit KEEP/RECAPTURE override. Review actions are appended to
`audit_log.jsonl`. The automated tests exercised an approve override, audit logging,
and the all-priority-items-KEEP GO path; a real human review of the generated queue
is still pending.

## 05 · Reliability and reproduction

Implemented in `src/pipeline.py` and
`src/examples/t02_laplacian_baseline.py`. The pipeline validates input columns,
image IDs, provenance, image file paths, and blocks paths escaping the input folder.
It never reads ground truth and is run with the offline network guard enabled.

Validation completed:

- `python -m tools.verify_manifests`: 14 manifests, 0 failing.
- `python -m tools.preflight`: 0 failures; optional real-data/model warnings only.
- `python -m pytest -q`: passed; ground-truth-dependent cases skipped as designed.
- `python -m compileall -q src tests`: passed.
- Baseline and PoC end-to-end runs: both exit 0; each produced 96 predictions and
  a 20-item queue.
- Official eval attempt: exit 2 because instructor-only GT is absent.

Machine: Windows 10, Python 3.13.14, AMD64. Git SHA at run time: `b0ce8bf`.
With this machine's limited available memory, tests were run with
`OPENBLAS_NUM_THREADS=1` and `OMP_NUM_THREADS=1`.

Windows checkout note: fixture files are byte-hashed by their manifests. The
`.gitattributes` rule for `fixtures/**` disables line-ending conversion so
`core.autocrlf` cannot silently invalidate those hashes.

## 06 · Limitations, failure modes, and next steps

- The heuristic has not been validated against GT; whole-image brightness may miss
  a small glare region and may flag useful night images. Camera-specific optics may
  also shift sharpness scores.
- Inspect and record at least two concrete image IDs from the contact sheet before
  claiming these failure modes were observed.
- The contract evaluator cannot run until the instructor provides the GT overlay.
- No real-person or license-plate data was used. This PoC is not a legal-compliance
  determination and must not be presented as GDPR or Vietnamese-law certification.
- Next: conduct and record a real review, analyze failure examples, obtain the
  instructor overlay, run baseline and PoC evaluation on the unchanged eval split,
  then update this report with script-generated metric outputs.

## 07 · Individual contribution

Trinh Xuan Toan implemented the T02 scoring pipeline, Laplacian baseline, review
override/audit path, tests, and protocol documentation. Git author/email and commit
evidence still need to be recorded after creating a substantive commit; no commit
was created as part of this work.
