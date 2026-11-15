# D2 — Detector side experiments: data size, seed variance, baselines, post-processing, label agreement, environment shift

## Source and protocol

- **Experiment:** D2 is a set of seven supplementary checks on the detector arms of D1 (training-data size curve, seed variance, classical CV + OCR baseline, two post-processing rules, a second labeler for agreement, environment shift, and OmniParser v2 as a baseline).
- **Date:** 2026-11-11.
- **Answers:** `score114.py predict`, image size 1280, NMS IoU 0.7, max 1,000 detections, all detections with confidence ≥ 0.05 stored. The YOLO models run on an RTX 2060; the CV baseline runs on CPU.
- **Exam sets:** exam_v1 with 303 images (atspi118 held-out applications 258, web121 held-out sites 45) and gold 119 with 186 images (Linux 72, macOS 114). The environment-shift set is described in item 6.
- **Matching:** IoU ≥ 0.5, greedy one-to-one. Class-agnostic scores ignore the class; strict scores require the same class over 16 classes.
- **Thresholds:** confidence 0.25 and 0.45 are reported side by side. Neither the model nor the threshold was chosen on an exam set; `last.pt` is used throughout.
- **Reference arms** (from D1): A (initialized from the synthetic base S50_s, trained on Opus train v1), C (COCO yolo11s initialization), and the baseline S50_s without fine-tuning.
- **Unless stated otherwise,** F1 means class-agnostic F1 at confidence 0.25.
- **Costs:** API-equivalent labeling costs are given in the sections below (second-labeler run $9.04; environment-shift labeling and QA $11.81).

**Table summary.** Seven items. "Key numbers" lists the measured values.

| Item | Question | Key numbers |
|---|---|---|
| 1 | Is 2,782 training images enough? | 25 % 0.815 → 50 % 0.827 → 100 % 0.845 / 0.850 |
| 2 | Is A − C beyond seed variation? | Seed differences 0.005–0.006; A − C on exam_v1 +0.002 / +0.013 and on gold +0.011 / +0.015 |
| 3 | CV + OCR on the same exam set | 0.623 (P 0.722 / R 0.548) |
| 4 | Two post-processing rules | Both together: exam_v1 P +0.043, R −0.016, F1 +0.018; gold F1 +0.004 |
| 5 | Does A learn Opus's habits or does it see correctly? | Opus vs Sonnet 0.955; A vs Sonnet 0.853; A vs Opus 0.855 |
| 6 | Unseen environments | Dark theme −0.019; 1366×768 −0.024 |
| 7 | OmniParser v2 baseline | exam_v1 0.586 (R 0.547), gold 0.614 |

## 1. Training-data size curve

Question: how much does A's score drop when trained on 25 % or 50 % of the training data, and is 2,782 images saturated?

Method: subsets are stratified by (origin, group), 148 groups in total, shuffled with seed 0; each group keeps the first round(n × f) images (at least 1). This gives 712 images (25 %) and 1,404 images (50 %), and the 25 % subset is contained in the 50 % subset. Training uses the same recipe as A (S50_s initialization, 40 epochs, batch 12, close_mosaic 5, same internal validation set) on Modal A100.

**Table size_curve.** Scores by training-set fraction.

| Training data | exam_v1 P / R / F1 | atspi118 | web121 | gold | GroundCUA (original) | exam_v1 strict | exam_v1 at 0.45 |
|---|---|---|---|---|---|---|---|
| 25 % (712) | 0.745 / 0.899 / **0.815** | 0.820 | 0.780 | 0.786 | 0.473 | 0.728 | 0.838 |
| 50 % (1,404) | 0.762 / 0.905 / **0.827** | 0.834 | 0.785 | 0.803 | 0.511 | 0.749 | 0.847 |
| 100 % (2,782), seed 0 / 1 | 0.783 / 0.919 / **0.845** · 0.850 | 0.854 · 0.859 | 0.787 · 0.789 | 0.815 · 0.810 | 0.556 · 0.535 | 0.783 · 0.789 | 0.866 · 0.871 |

**Table size_boot.** Paired bootstrap of the per-image differences (2,000 resamples, seed 0).

| Set | 100 % − 50 % [95 % CI] | 50 % − 25 % [95 % CI] |
|---|---|---|
| exam_v1 | +0.018 [+0.010, +0.027] | +0.013 [+0.006, +0.019] |
| gold | +0.012 [+0.004, +0.020] | +0.018 [+0.010, +0.025] |

Reading: each doubling adds about 0.012–0.018 and both intervals exclude 0. The curve rises roughly log-linearly and does not flatten after 50 %. GroundCUA gains the most (0.473 → 0.556). Caveats: one seed (the seed difference, about 0.005, is not small compared with the 0.012–0.018 steps); the number of epochs is fixed at 40, so smaller subsets also get fewer iterations; the stratification is by application, so "more applications" and "more images per application" are not separated.

## 2. Seed variance

Question: is the A − C difference of D1 (+0.006) beyond seed variation? A and C use the same recipe; only the seed override (`seed: 1`, deterministic mode) changes.

**Table seeds.**

| | exam_v1 | gold | GroundCUA |
|---|---|---|---|
| A seed 0 / 1 | 0.845 / 0.850 | 0.815 / 0.810 | 0.556 / 0.535 |
| C seed 0 / 1 | 0.843 / 0.837 | 0.805 / 0.794 | 0.461 / 0.464 |
| A − C, seed 0 [95 % CI] | +0.002 [−0.005, +0.008] | +0.011 [+0.003, +0.018] | +0.095 |
| A − C, seed 1 [95 % CI] | +0.013 [+0.007, +0.018] | +0.015 [+0.008, +0.022] | +0.071 |
| Same recipe, seed difference | A 0.005 · C 0.006 | A 0.005 · C 0.010 | A 0.021 · C 0.003 |

At confidence 0.45, A − C is +0.003 / +0.014 on exam_v1 and +0.016 / +0.024 on gold. The strict-score sign agrees (exam_v1 seed 0 +0.003; gold seed 0 +0.014).

Reading: A is at least as high as C in all 8 cells (2 seeds × 2 sets × 2 thresholds), by +0.002 to +0.024, the same order as the seed differences (0.004–0.014). On GroundCUA, A leads clearly (+0.07 to +0.10). The synthetic base S50_s gives a small, stable advantage of about +0.01 on these sets, larger on GroundCUA-style interfaces. Whether +0.01 justifies maintaining the base is an engineering decision, not a statistical one. Caveats: two seeds do not give a variance estimate; per-image bootstrap captures only which images were chosen, not training randomness (C seed 0 vs seed 1 differs by +0.006, which the per-image bootstrap also calls significant, so it understates real model-to-model uncertainty).

## 3. Classical CV + OCR baseline on the same exam set

Question: how does the frozen CV + OCR pipeline (text-line detection with rapidocr, pixel candidates, and a frozen keep / merge classifier, confidence 0.30) score on this exam set?

Method: the frozen parameters are run unchanged on the 303 exam_v1 images on CPU. Scoring is class-agnostic (CV has no ARIA class).

**Table cv.**

| Subset | CV + OCR at 0.30 P / R / F1 | A at 0.25 P / R / F1 |
|---|---|---|
| exam_v1 (all) | 0.722 / 0.548 / **0.623** | 0.783 / 0.919 / **0.845** |
| atspi118 | 0.723 / 0.525 / 0.608 | 0.794 / 0.923 / 0.854 |
| web121 | 0.721 / 0.713 / 0.717 | 0.705 / 0.892 / 0.787 |

CV's F1 is 0.624 at 0.25 and 0.607 at 0.45, nearly flat. CPU time: 1.20 s per image (OCR 1.02 s).

Reading: CV + OCR is 0.22 below A, mostly in recall (0.55 vs 0.92); precision is of the same order. Caveats: 166 of the 303 exam_v1 images also appear in the exam set of an earlier CV experiment; CV scores 0.643 on those and 0.601 on the other 137. Scores from the CV scorer and the common scorer were not matched TP by TP.

## 4. Two post-processing rules

Question: the error analysis of D1 attributes about 16 % of errors each to "content under a dimming layer" and to "duplicate parent and child boxes". Can zero-cost post-processing rules remove them?

Rules (implemented in the post-processing script of the detector experiments, which is not included; its 12 unit tests passed):
- **(a) `drop_under_scrim`:** from pixels, detect a bright dialog over a dimmed light interface, and drop boxes whose center lies outside the dialog. The threshold was set on a development set of 109 images without a scrim and 38 with one (71 of them dark themes), then frozen before the exam run. Development result: TP 23, FN 15, FP 3, TN 106; no false positives on dark themes.
- **(b) `dedupe_nested`:** a fixed table of "outer class × inner class → which to drop", written from the labeling convention before the run, with a containment threshold of 0.9.

**Table postproc.** Class-agnostic F1 for A, with each rule alone and both together.

| Set | No rule P / R / F1 | (a) only | (b) only | (a) + (b) | (a) + (b), strict |
|---|---|---|---|---|---|
| exam_v1 at 0.25 | 0.783 / 0.919 / 0.845 | 0.851 | 0.857 | **0.826 / 0.903 / 0.863** | 0.783 → 0.791 |
| gold at 0.25 | 0.773 / 0.862 / 0.815 | — | — | 0.797 / 0.843 / **0.819** | 0.737 → 0.733 |

The CLI rerun of (a) + (b) at 0.25 on exam_v1 gives 0.8259 / 0.9025 / 0.8625, the same values. The full tables (including 0.45, subsets and per-row ablations) are in the results of the postproc evaluation.

Reading:
- **Rule (a) is precise but narrow.** It fired on 6 of 489 images. The 5 exam_v1 firings are all gnome-calendar light dialogs, and none of the removed boxes was a true positive. The one gold firing (a macOS sheet) removed 20 true positives, because the gold labels include a toolbar outside the sheet that is not dimmed. Dark scrims and dialogs over photos on websites, where most false positives on exam_v1 occur (gnome-calendar dark, ted, usagov), are not covered. A version 2 needs a development set with dark scrims.
- **Rule (b) trades recall for precision.** Of the 1,217 boxes it removed, 43 % were true positives. The labels themselves often box text inside buttons and nested same-class elements separately, so the convention is not applied consistently. On gold's strict score, rule (b) is negative.
- Suggested handling: do not add rule (b) to the toolchain; keep rule (a) as an optional switch. The more useful fix is to make the "text inside button / nested same-class" convention consistent during label QA; that is a labeling issue.

Caveat: the class table of rule (b) was not tuned on any data (it was written from the convention). Adding a condition such as "drop the outer box only if its confidence is clearly higher" might keep recall, but it was not tested, to avoid tuning on the exam set.

## 5. Second labeler

Question: does A learn Opus's habits, or does it see correctly?

Method: 50 images stratified from exam_v1 by (origin, group), covering all 20 groups. The second labeler is Claude Sonnet 5.5, with the same rules file as the exam labels, the same effort setting, the same cropped frame, whole-image mode, and an empty trial directory; only the first round, with no QA or fixes. Agreement: one side is treated as truth and the other as prediction, scored with the common scorer (F1 is symmetric). The Opus labels are the final QA'd labels; Opus first round is the labels before QA.

**Table agreement.** Agreement on 50 images.

| Pair | Class-agnostic F1 | Strict F1 |
|---|---|---|
| Opus final vs Sonnet | **0.955** | 0.874 |
| Opus first round vs Sonnet | 0.954 | 0.873 |
| Opus final vs Opus first round (how much QA changed) | 0.999 | 0.999 |
| A at 0.25 vs Opus | **0.855** | 0.767 |
| A at 0.25 vs Sonnet | **0.853** | 0.785 |
| A at 0.45 vs Opus / vs Sonnet | 0.876 / 0.866 | 0.791 / 0.800 |

Mean boxes per image: Opus 55.1, Sonnet 56.2, A at 0.25 64.3, A at 0.45 55.5.

Reading: A agrees with the two labelers almost equally (0.853 vs 0.855; under the strict score A is closer to Sonnet). A therefore does not specifically learn Opus's habits. The gap of about 0.15 between A and the labels is mostly A's own error, and it is much larger than the gap between the two labelers (0.045). Label noise therefore bounds A's score near 0.95, which is well above where A is now.

Checks on the 0.955 agreement:
1. **No leakage found in the recorded inputs.** The prompt contains only the rules path, image path and output path; none of the 50 batch prompts mentions a first round, a fix pass or existing boxes; the trial directory was empty. The labeling sessions were restricted to reading and writing files and did not keep transcripts, so individual tool calls could not be audited afterwards. All 50 sessions finished in 4 turns (read image, write JSON, reply).
2. **Same pipeline on both sides.** Both label sets went through the same merging and geometry post-processing, which raises agreement without being leakage.
3. **Metric and convention differ from earlier single-image estimates.** An earlier one-image estimate (about 0.82) used an older labeling convention and a different metric (matches divided by the larger box count); the two numbers are not comparable.
4. **Per image:** the worst Opus–Sonnet image has F1 0.850; all 50 images are at or above 0.85.

Other notes: a third labeler run was stopped after 33 of 50 images and its agreement is not reported. A repeat of Opus on the same 50 images was not run, so 0.955 has no Opus-vs-Opus ceiling for comparison. Sonnet and Opus come from the same provider with the same rules and prompt, so high agreement shows that both follow the same convention consistently, not that either labels correctly. API-equivalent cost of the second-labeler run: $9.04.

## 6. Environment shift

Question: does the score hold in environments the detector has not seen?

Method: four held-out applications (drawing and gitg, GTK; okular and keepassxc, Qt) were captured in a private virtual display with the same screen-capture tooling, six images per application per variant, 48 images in total. Variant 1 is a dark theme at 1920×1080 (no scaling); variant 2 is a light theme at 1366×768. Every frame passed the window rule (whole windows, no cropping). Labels: Opus with the same rules file and high effort; Sonnet QA on 10 of 48 images (20.8 %), all 10 passed. Scoring on CPU for A, C and the baseline, compared with 158 original-environment images of the same four applications from exam_v1.

Note: the dark-theme capture for drawing and keepassxc did not turn dark (mean brightness 143 and 247), so existing dark-variant images for those applications in the training set are not dark; the coverage was added by application in this test.

**Table envshift.** Scores by environment (confidence 0.25 unless stated).

| Model | Original (158 images) | Dark (24 images) | ΔF1 | 1366×768 (24 images) | ΔF1 |
|---|---|---|---|---|---|
| A at 0.25 | 0.801 / 0.920 / **0.856** | 0.775 / 0.910 / **0.837** | −0.019 | 0.776 / 0.896 / **0.832** | −0.024 |
| C at 0.25 | 0.846 | 0.839 | −0.007 | 0.812 | −0.033 |
| Baseline (S50_s) at 0.25 | 0.553 | 0.555 | +0.003 | 0.490 | −0.063 |
| A at 0.45 | 0.879 | 0.856 | −0.023 | 0.877 | −0.001 |

A preliminary check with no labeling cost: in exam_v1 there are already 20 images each of gnome-calendar dark (with 1.25× text) and gnome-calendar; A's ΔF1 is +0.005 at 0.25 and +0.018 at 0.45. Other applications did not have 5 or more images in both groups.

Reading: under dark theme and 1366×768, A drops by about 0.02, and C drops by 0.01–0.03; both are within the noise of 24-image sets. The drop visible in overlays comes from box granularity (list rows versus cells, icon subcontrols), not from missed controls. The unfine-tuned baseline drops clearly only at 1366×768 (−0.06), and at 0.45 its recall collapses.

Caveats:
- The test is not fully unseen: the training set already has 159 dark-variant frames from other applications and a 1280-wide calculator set. It measures unseen applications with seen kinds of variation, not unseen variations.
- Each variant has 24 images; no interval was computed. An absolute ΔF1 of 0.03 or less should be read as "no change detected".
- New frames (for example, a keepassxc with an empty database) may be simpler than the original exam frames.
- The labels come from the same Opus pipeline as the original exam labels; shared labeling bias cancels out in ΔF1 but affects absolute values.

API-equivalent cost: $11.81 (labeling $10.86 plus QA $0.95).

## 7. OmniParser v2 baseline (box level)

Question: how does OmniParser v2 score on the same exam set under the same convention?

Method: default configuration of OmniParser (microsoft/OmniParser at commit 3540212, HF weights at f55d0750, icon_detect_v3 YOLOv9-E, box threshold 0.05, EasyOCR), with no parameter changes. Run through the resident server used in R1 on the local RTX 2060. Mapping: each element becomes one box; `text` → class 14, `icon` → class 0, confidence 1.0. OmniParser does not give comparable confidences, so the 0.25 / 0.45 thresholds do not apply.

**Table omni.** Class-agnostic scores.

| Set | P | R | F1 | A at 0.25 F1 |
|---|---|---|---|---|
| exam_v1 (303) | 0.631 | **0.547** | **0.586** | 0.845 |
| exam_v1 atspi118 / web121 | 0.635 / 0.606 | 0.539 / 0.603 | 0.583 / 0.604 | 0.854 / 0.787 |
| gold 119 (186) | 0.652 | **0.580** | **0.614** | 0.815 |

Using only one class of boxes: text boxes reach recall 0.14 (exam_v1) and 0.19 (gold); icon boxes reach 0.41 and 0.39. Median time per image: 1.65–1.90 s (including the Florence-2 captions).

Reading: OmniParser is 0.20–0.26 below A, mainly in recall (about 0.6 times A's recall). It rarely outputs one box per text line: text is often merged into icon boxes or several lines are combined into one box. This is a convention difference; the figure should be reported as "scored under our convention", not as OmniParser's quality under its own convention.

Caveats: strict scores at 0.30 and 0.35 are compared only for the text and icon classes and are for reference only. One gold image (3584×2140) made OmniParser fail with an error and was counted as zero boxes.
