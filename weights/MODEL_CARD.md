# Model card: pixeltree-detector-v1

| | |
|---|---|
| file | `pixeltree-detector-v1.pt` (19 MB), GitHub Release `v0.1.0` asset; not in git history |
| sha256 | see [`SHA256SUMS`](SHA256SUMS); `python weights/download.py` downloads and verifies |
| architecture | Ultralytics YOLO11s object detector, input 1280 px |
| task | detect every visible UI element in a desktop or web screenshot and give it one of 16 roles |
| licence | AGPL-3.0 (derivative of Ultralytics YOLO11; see [NOTICE](../NOTICE)) |
| intended use | research on screen parsing and GUI agents; producing an element list ("tree") from a screenshot together with OCR (`pixeltree.perceive`) |
| not intended for | accessibility compliance decisions; security-relevant automation; unattended control of real user desktops |

## Classes

0 `aria:button`, 1 `aria:link`, 2 `aria:menuitem`, 3 `aria:tab`, 4 `aria:checkbox`, 5 `aria:radio`, 6 `aria:textbox`, 7 `aria:combobox`, 8 `aria:slider`, 9 `aria:progressbar`, 10 `aria:gridcell`, 11 `aria:listitem`, 12 `aria:heading`, 13 `aria:img`, 14 `vax:visibleText` (a line of visible text), 15 `other:visible` (any other visible element). The model outputs no names and no states; names come from OCR in `pixeltree.perceive`.

## Training

- **Data.** 2,782 screenshots plus a 130-image internal validation split. Sources:
  - our captures of Linux desktop apps (atspi118 source);
  - a GroundCUA subset;
  - public websites.

  All were labelled by Claude Opus under [box convention v1](../labeling/box_convention_v1.md) with the [labelling prompt](../labeling/prompts/label_rules_v1_1.md), with Claude Sonnet QA on a sample and a fix round. No human labels. Total labelling cost for 3,215 images (train + exam) was $1,044.74 API-equivalent ([results/labeling_cost.md](../results/labeling_cost.md)).
- **Recipe.** Start from our unreleased YOLO11s checkpoint (pre-trained on synthetic component pages, web pages and GroundCUA). Train 40 epochs, batch 12, imgsz 1280, close_mosaic 5, and use `last.pt` (no epoch picked on the exam). Training took 20.9 min on one A100-40GB ([results/D1_detector.md](../results/D1_detector.md)). Starting from public COCO YOLO11s instead gives F1 0.848 vs 0.854 on held-out Linux apps.
- **Split.** By application: no app or website in the exam appears in training.

## Evaluation

Protocol for all scores below:
- Greedy one-to-one matching at IoU ≥ 0.5.
- *Class-agnostic* F1 ignores the role; *strict* F1 requires the same role.
- Confidence thresholds 0.25 and 0.45 are both reported and were not tuned on the exam.
- Labels: Claude Opus under the same convention.

| exam | images | class-agnostic F1 @0.25 / @0.45 | strict F1 @0.25 |
|---|---|---|---|
| held-out Linux apps (10 apps) | 258 | 0.854 / 0.874 | 0.798 |
| held-out websites (3 sites) | 45 | 0.787 / 0.813 | — |
| gold set (Linux 72 + macOS 114) | 186 | 0.815 / 0.826 | 0.737 |

Source: [results/D1_detector.md](../results/D1_detector.md).

Further measurements, all from [results/D2_detector_side.md](../results/D2_detector_side.md):
- **Second labeller.** On 50 exam images the detector agrees with Opus labels at 0.855 and with independent Sonnet labels at 0.853; Opus and Sonnet agree with each other at 0.955.
- **Environment shift.** A dark theme costs −0.019 F1 and a 1366×768 screen −0.024.
- **Other parsers on the 303-image exam.** Classical CV + OCR scores 0.623 and OmniParser v2's detector 0.586, against 0.845 for this model.
- **Data curve.** 25 % / 50 % / 100 % of the training data give 0.815 / 0.827 / 0.845 and are still rising.

**Speed** (from [results/D1_detector.md](../results/D1_detector.md)): 44 ms per 1920×1080 frame on an RTX 2060 and 260 ms on a laptop CPU (i7-10750H), detector only. With OCR, a full observation took about 0.45 s in our agent runs (GPU path; see the device note in [results/R1_main_exam.md](../results/R1_main_exam.md)). The archived experiment trees are reproduced exactly by the GPU path; CPU output differs slightly (see [docs/tree_format.md](../docs/tree_format.md)).

## Known weaknesses

- **Rare and variable classes are weak.** Strict F1 on the held-out apps: progressbar 0.145, slider 0.528, tab 0.533, combobox 0.583. Tabs are often called buttons ([results/D1_detector.md](../results/D1_detector.md)).
- **Dimmed backgrounds and nesting.** It sometimes boxes content under a dimming overlay, and sometimes boxes both a whole row and its parts.
- **Not a fair score on other conventions.** It scores lower against labelling conventions with looser margins or no per-line text, such as GroundCUA's human boxes.
- **No names, no states.** Icon meaning and checked / selected / expanded state are outside the model. In the agent exam these, not missing boxes, were the main failure causes; see [PAPER.md](../PAPER.md) §6.
- **Narrow training domain.** Linux (GTK / Qt / Electron) and web, mostly light themes at 1920×1080. Windows and macOS are under-represented (macOS gold-set F1 is about 0.75–0.80).
- **Label limits.** Labels come from one model family under one convention; agreement between labellers measures consistency, not correctness.
