# D1 — Detector: three training arms on held-out applications

## Source and protocol

- **Experiment:** D1 trains a YOLO11s detector for UI elements under three initialization and data arms, and evaluates them on held-out Linux applications, a held-out web set, a gold set with macOS screens, and a GroundCUA set. It asks which arm to use and whether the training base matters.
- **Date:** training 2026-11-10 to 2026-11-11; report 2026-11-11.
- **Training data:** 2,782 images labeled by Claude Opus 5.5 under one written box convention (`box_convention_v1`), split into 980 AT-SPI-derived Linux images, 1,637 GroundCUA images and 165 web images. An internal validation set of 130 images (5 % stratified by app) was used only for training curves; it was not used to choose models.
- **Arms:**

**Table arms.** Arm definitions.

| Arm | Initialization | Training data |
|---|---|---|
| A | S50_s (yolo11s, initialized from our synthetic + web + GroundCUA base) | Opus train v1: 2,782 images (atspi118 980 / GroundCUA 1,637 / web121 165); internal validation 130 |
| C | yolo11s COCO weights | Same as A |
| B | S50_s | Same as A + 2,912 images replayed from the v17 set (seed 0). GroundCUA rows train boxes only (`cls_mask`); their classes are unknown |
| Baseline | S50_s, no fine-tuning | — |

- **Evaluation:** `score114.py predict` on one RTX 2060: image size 1280, NMS IoU 0.7, max 1,000 detections, all detections with confidence ≥ 0.05 stored. Thresholds 0.25 and 0.45 are reported side by side. The thresholds were not tuned on the exam sets. `last.pt` (last epoch) is used for every arm; no epoch was chosen on the exam sets.
- **Split:** application-level hold-out (no application appears in both training and exam).
- **Matching:** IoU ≥ 0.5, greedy one-to-one. **Class-agnostic** scores ignore class; **strict** scores require the same class (16 classes).
- **Exam sets:** exam_v1 atspi118 (258 images, 10 held-out Linux applications); exam_v1 web121 (45 images, 3 held-out websites); the gold set of 186 images (72 Linux, 114 macOS) labeled under the same convention; GroundCUA exam_v2 with 8,255 images (original and shrunk box variants). The GroundCUA set does not follow the same box convention; it is a cross-convention reference and is not part of the decision.
- **Set names:** exam_v1 is the held-out exam split of the first labelled set (its atspi118 part, from Linux desktop captures, and its web121 part). Gold 119 is a separate set of 186 images labelled under the same convention, and is used as a second exam.
- **Label agreement:** Label agreement was later measured in D2 (inter-annotator F1 0.955); see `D2_detector_side.md`.
- **Limitations (from the report):**
  1. The exam and training labels were produced by the same labeler (one model, one convention), so the scores measure agreement with that labeler, not with human ground truth.
  2. Application-level hold-out is not environment-level hold-out: the held-out Linux frames come from the same capture pipeline, machine and GNOME theme as the training frames. The macOS gold set is the closest to a new environment.
  3. Some groups are small (ktouch 2 images, gnome-contacts 5, rhythmbox gold 3); websites are 3.
  4. One seed per arm (seed 0). The difference between A and C (0.006) is within unmeasured seed variance; the result shows no detectable difference, not that A is better.
  5. The task-success half of the decision criterion was not measured here; F1 does not predict agent task success (see R1 and R3 for task results).
  6. The replay ratio of B was tried at one value only (1:1).

## Results

**Table main.** Class-agnostic F1 (IoU ≥ 0.5, greedy one-to-one). Unless stated otherwise, the first value of a cell is at confidence 0.25 and the second at 0.45.

| Arm | Exam_v1 atspi118 (258 images, 10 held-out Linux apps) | Exam_v1 web121 (45 images, 3 held-out sites) | Gold 119 (186 images: Linux 72 / macOS 114) | GroundCUA exam_v2 (8,255 images; original / shrunk labels) |
|---|---|---|---|---|
| A | **0.854 / 0.874** | 0.787 / 0.813 | 0.815 / 0.826 (0.867 / 0.781 at conf 0.25) | 0.556 / 0.595 at conf 0.25 |
| C | 0.848 / 0.868 | **0.809 / 0.830** | 0.805 / 0.811 (0.858 / 0.769) | 0.461 / 0.493 |
| B | 0.854 / 0.839 | 0.753 / 0.744 | 0.791 / 0.769 (0.852 / 0.748) | **0.577 / 0.630** |
| Baseline (S50_s, no fine-tuning) | 0.489 / 0.212 | 0.549 / 0.510 | 0.444 / 0.171 (0.435 / 0.450) | **0.692** / 0.603 |

In the Gold 119 column, the first two values are at confidence 0.25 and 0.45 over all 186 images; the parenthesized values are the Linux subset (72 images) and the macOS subset (114 images), both at confidence 0.25. The GroundCUA column gives its values at confidence 0.25 only.

Strict F1 at confidence 0.25 (same class required): exam_v1 atspi118: A 0.798, C 0.791, B 0.790, baseline 0.188. Gold 119: A 0.737, C 0.723, B 0.714, baseline 0.087. GroundCUA: all below 0.21 (class conventions differ; see the GroundCUA note above).

## Per application and site

**Table groups.** Exam_v1, 13 groups, sorted by A's F1 at confidence 0.25. Parentheses give precision / recall where recorded.

| Group | Images | A | C | B | Baseline |
|---|---|---|---|---|---|
| ktouch | 2 | 0.696 (0.53/1.00) | 0.683 | 0.762 | 0.696 |
| usagov (web) | 15 | 0.743 (0.62/0.93) | 0.777 | 0.731 | 0.601 |
| ted (web) | 15 | 0.803 (0.73/0.89) | 0.781 | 0.761 | 0.599 |
| applestore (web) | 15 | 0.815 | 0.881 | 0.766 | 0.396 |
| gitg | 40 | 0.817 | 0.799 | 0.793 | 0.384 |
| okular | 40 | 0.819 | 0.822 | 0.853 | 0.635 |
| gnome-calendar | 40 | 0.828 | 0.824 | 0.836 | 0.257 |
| gnome-contacts | 5 | 0.837 | 0.827 | 0.791 | 0.554 |
| obsidian | 20 | 0.862 | 0.891 | 0.878 | 0.527 |
| keepassxc | 40 | 0.866 | 0.854 | 0.869 | 0.657 |
| lutris | 19 | 0.887 | 0.894 | 0.883 | 0.464 |
| rhythmbox | 12 | 0.895 | 0.867 | 0.888 | 0.597 |
| drawing | 40 | 0.919 | 0.911 | 0.907 | 0.530 |

The three lowest groups for A are ktouch (2 images, too few to be reliable), usagov and ted, both websites; the errors on the websites are mostly false positives (precision 0.62 and 0.73 with recall 0.93 and 0.89). The lowest Linux application is gitg at 0.817. Gold-set groups: macOS 120 (34 images) 0.745; Screen2AX macOS 0.795; atspi118 applications 0.852–0.899.

## Box size and classes

**Table size_recall.** Class-agnostic recall at confidence 0.25, by box size (small = longer side < 24 px).

| Set | Small | Medium | Large |
|---|---|---|---|
| exam_v1 A / C / B / baseline | **0.876** / 0.841 / 0.797 / 0.173 | 0.943 / 0.955 / 0.908 / 0.450 | 0.912 / 0.913 / 0.894 / 0.463 |
| Gold A / C / B / baseline | 0.764 / 0.717 / 0.698 / 0.134 | 0.897 / 0.889 / 0.799 / 0.296 | 0.853 / 0.852 / 0.812 / 0.406 |

Small icons are the only place where A clearly leads C (+0.035 on exam_v1, +0.047 on gold). B is weakest on small icons.

Class results (strict F1, exam_v1, A): strong classes are menuitem 0.915, visibleText 0.846 and button 0.811; these three make up 65 % of ground-truth boxes. Weak classes: progressbar 0.145 (72 boxes, recall 0.08), slider 0.528 (30 boxes; gold 0.048), tab 0.533 (400 boxes), combobox 0.583, gridcell 0.699 (gold 0.439), img (gold 0.423). Among boxes matched by IoU, the class agrees for 0.899 of exam_v1 true positives and 0.866 of gold true positives. The largest confusion is tab → button (145 boxes; gold 137).

## Training curves and wall-clock time

**Table curves.** Validation mAP50-95 for the internal validation set (130 images, used only to read curves) at epochs 10, 20, 30 and 40.

| Arm | Epochs 10 / 20 / 30 / 40 | Best epoch (value) | Last − best | Reading |
|---|---|---|---|---|
| A | 0.534 / 0.608 / 0.642 / 0.646 | 35 (0.647) | −0.001 | Plateau after about 30 epochs |
| C | 0.417 / 0.551 / 0.589 / 0.614 | 40 (0.614) | 0 | Still rising at 40 epochs |
| B | 0.518 / 0.578 / 0.603 / 0.611 | 33 (0.619) | −0.008 | Plateau; the validation set uses the Opus convention, and the replay data pulls B down on it, as expected |

**Table wallclock.** Training wall-clock time on one A100-40GB (staged data, batch 12).

| Arm | Wall-clock time |
|---|---|
| A | 20.9 min |
| C | 22.4 min |
| B | 41.7 min (twice the data) |

Four smoke runs took under 1 minute each.

## Latency

**Table latency.** Per-frame latency of arm A on exam_v1 (first 30 frames, first 3 frames discarded as warm-up). Each frame includes decoding, preprocessing, inference and NMS.

| Device | Median | p90 | Of which inference (median) |
|---|---|---|---|
| RTX 2060 | **44 ms** | 50 ms | 18 ms |
| CPU i7-10750H (8 torch threads) | **260 ms** | 279 ms | 230 ms |

For comparison, the observer of the v1_4 pipeline took 1.4 s per frame on CPU, dominated by OCR; the detector is not the bottleneck. ONNX and smaller image sizes were not measured.
