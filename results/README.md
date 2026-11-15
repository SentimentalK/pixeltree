# Results

Measured numbers from the experiments of the project, copied from the verified reports. Each file starts with
a "Source and protocol" section (what was run, on which tasks or images, how success or score was defined,
how intervals were computed, and the sample size), followed by the tables. Table values are copied as
reported; nothing was recomputed or rounded.

Machine-readable copies of every table are in [`csv/`](csv/), one file per table, named
`<file>__<table>.csv`.

## Experiment codes

| Code | What it is | Date | Sample |
|---|---|---|---|
| R1 | Main agent exam on held-out Linux desktop apps: screenshot, detector tree, AT-SPI tree and OmniParser tree as the agent's observation (Claude Haiku 5.5, `claude -p`; one condition with Sonnet 5.5) | 2026-11-11 | 48 tasks × 7 conditions × 3 repetitions = 1,008 episodes, 8 apps |
| R2 | Offline token accounting for four text formats of the R1 tree (no model call, no application started) | 2026-11-12 | 144 R1 tree episodes, 1,826 observation steps |
| R3 | Tree-first observation with change-only updates, hover and on-demand look, against screenshot-only agents (Claude Haiku 5.5; one condition with Sonnet 5.5) | 2026-11-12 / 13 | 48 tasks; 144 episodes per Haiku condition, 48 for Sonnet, 768 total |
| R4 | Gemini 3.8 Flash as an agent through a command-line wrapper (agy) | 2026-11-13 | **Incomplete**: 1 valid task triplet of 48; direction only on 5 tasks |
| R5 | Four model families as readers of screenshot, tree and hybrid observations (GLM 5.3 Flash, DeepSeek V4.1 Flash, LongCat 2.0 text-only, Claude Haiku 5.5 as shell calibration) | 2026-11-13 | **Partial**: 27 of 48 tasks, one run per cell, no intervals |
| D1 | Detector: three training arms (A: synthetic base + labels, C: COCO start, B: A plus replayed data) and an untuned baseline, evaluated on held-out Linux apps, a web set, a gold set with macOS screens and a GroundCUA set | 2026-11-10 / 11 | 2,782 training images; exam sets of 303, 186 and 8,255 images |
| D2 | Detector side experiments: data-size curve, seed variance, CV + OCR baseline, two post-processing rules, second labeler, environment shift, OmniParser v2 baseline | 2026-11-11 | the same exam sets as D1; second labeler on 50 images; environment shift on 48 images |

Other tables:

- [`labeling_cost.md`](labeling_cost.md): images and boxes per source and split of the first labelled set (3,215
  images), and the API-equivalent labelling cost by role.

## Files

- [`R1_main_exam.md`](R1_main_exam.md): main table with 7 conditions, paired differences, per-app and per-difficulty
  success, cost and time, failure causes.
- [`R2_token_accounting.md`](R2_token_accounting.md): observation tokens per step for four formats, per app, the
  change-only behaviour, and two guardrails (losslessness, click safety).
- [`R3_tree_first.md`](R3_tree_first.md): conditions, main table, pass rule, paired differences, per app, stop
  reasons, look and hover, token and wall-clock tables, cleared-name clicks and failure classes.
- [`R4_gemini.md`](R4_gemini.md): the incomplete Gemini run, with its protocol constraints and the sensitivity table.
- [`R5_four_readers.md`](R5_four_readers.md): scope tables for 24 and 27 tasks, paired differences, shell fix and
  reruns, steps and tokens, click checks.
- [`D1_detector.md`](D1_detector.md): arm definitions, main F1 table, per-group, box-size recall, training curves,
  wall-clock time and latency.
- [`D2_detector_side.md`](D2_detector_side.md): seven supplementary checks, each with its key numbers.

## How to read the numbers

- **Compare conditions only within one model and one shell.** Absolute numbers across models or across shells
  are not comparable. In R5, Claude Haiku 5.5 through the second shell is a calibration of that shell, not a model result.
- **Read R5 with its size in mind.** Each cell is one run over 27 tasks, and there are no intervals. Differences
  under about 15 percentage points are not treated as findings.
- **R4 is direction only.** It has one complete valid task and a sensitivity view over five tasks with one
  repetition each. It supports no ranking.
- **Intervals** in R1, R2 and R3 are percentile bootstraps over tasks (2,000 resamples, seed 0), 95 %. Paired
  differences are computed on the same tasks.
- **Costs** are API-equivalent (priced at API list rates from the usage the provider reported). They are not
  billed amounts.
- **Exam sets are labelled by a model** under one written box convention, and the detector arms are trained on
  labels of the same kind. Scores measure agreement with that labeller, not with human ground truth; D2 measures
  agreement between two labellers. See the caveats in D1 and D2.
- **GroundCUA columns** in D1 and D2 use a different box convention from the exam labels; they are a cross-convention
  reference and are not part of the decision.
