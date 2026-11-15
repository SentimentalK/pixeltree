---
license: agpl-3.0
library_name: ultralytics
pipeline_tag: object-detection
tags:
  - yolo11
  - ultralytics
  - gui
  - screen-parsing
  - ui-element-detection
  - gui-agent
  - accessibility
  - screenshot
---

# pixeltree-detector-v1

A 19 MB YOLO11s detector that finds every visible UI element in a desktop or web screenshot and gives it one of 16 roles. Together with OCR (in the [pixeltree](https://github.com/SentimentalK/pixeltree) code) it turns a screenshot into a text list of elements — "the tree" — that a GUI agent can read.

It is a research release. The accompanying [short paper](https://github.com/SentimentalK/pixeltree/blob/main/PAPER.md) explains which agents benefited from the tree and which did not.

## Roles (classes)

| id | role | id | role |
|---|---|---|---|
| 0 | `aria:button` | 8 | `aria:slider` |
| 1 | `aria:link` | 9 | `aria:progressbar` |
| 2 | `aria:menuitem` | 10 | `aria:gridcell` |
| 3 | `aria:tab` | 11 | `aria:listitem` |
| 4 | `aria:checkbox` | 12 | `aria:heading` |
| 5 | `aria:radio` | 13 | `aria:img` |
| 6 | `aria:textbox` | 14 | `vax:visibleText` (one line of visible text) |
| 7 | `aria:combobox` | 15 | `other:visible` (any other visible element) |

The model outputs boxes and roles only. It outputs no names and no states.

## How to use

Boxes and roles with plain Ultralytics:

```python
from huggingface_hub import hf_hub_download
from ultralytics import YOLO
boxes = YOLO(hf_hub_download("{{REPO_ID}}", "pixeltree-detector-v1.pt")).predict("screenshot.png", imgsz=1280, conf=0.25)[0].boxes
```

Screenshot → element tree (detector + OCR names), with the pixeltree code:

```sh
git clone https://github.com/SentimentalK/pixeltree && cd pixeltree
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu && pip install -e ".[perceive]"
python -m pixeltree.perceive screenshot.png --weights "$(python -c 'from huggingface_hub import hf_hub_download as d; print(d("{{REPO_ID}}", "pixeltree-detector-v1.pt"))')"
```

Each output line is `role [id] "name" @(left, top, width, height) c=(centre_x, centre_y)`. Names come only from OCR; an icon without readable text gets `""`. We used `imgsz=1280` and `conf=0.25` in all agent experiments.

## Training data and labels

- **Data.** 2,782 training screenshots, plus a 130-image internal validation split. Sources:
  - screenshots of open-source Linux desktop apps, captured by us in virtual displays with synthetic data;
  - a subset of the public GroundCUA desktop dataset (MIT);
  - screenshots of public websites.

  The training images are not redistributed; see [DATA.md](https://github.com/SentimentalK/pixeltree/blob/main/DATA.md).
- **Labels.** Every image was labelled by Claude Opus under one written [box convention](https://github.com/SentimentalK/pixeltree/blob/main/labeling/box_convention_v1.md) ("the tight box of what is painted now"), with Claude Sonnet QA on a sample and a fix round. No human labels.
- **Recipe.** YOLO11s at imgsz 1280, 40 epochs, batch 12, `last.pt`, about 21 minutes on one A100. The start checkpoint was our own YOLO11s pre-trained on synthetic and web pages (not released). Starting from public COCO YOLO11s instead scores 0.848 vs 0.854 on the held-out Linux apps.
- **Split.** By application: no exam app or website was seen in training.

## Scores

Protocol:
- Greedy one-to-one matching at IoU ≥ 0.5.
- *Class-agnostic* F1 ignores the role; *strict* F1 requires the same role.
- Confidence thresholds 0.25 and 0.45 are both reported and were not tuned on the exam.
- Labels: Claude Opus under the same convention.

Sources: [results/D1_detector.md](https://github.com/SentimentalK/pixeltree/blob/main/results/D1_detector.md) and [results/D2_detector_side.md](https://github.com/SentimentalK/pixeltree/blob/main/results/D2_detector_side.md).

| exam | images | class-agnostic F1 @0.25 / @0.45 | strict F1 @0.25 |
|---|---|---|---|
| held-out Linux apps (10 apps) | 258 | 0.854 / 0.874 | 0.798 |
| held-out websites (3 sites) | 45 | 0.787 / 0.813 | — |
| gold set (Linux 72 + macOS 114) | 186 | 0.815 / 0.826 | 0.737 |
| start checkpoint, not fine-tuned (Linux apps) | 258 | 0.489 / 0.212 | — |

- **Second labeller** (50 exam images). The detector agrees with Opus labels at 0.855 and with independent Claude Sonnet labels at 0.853. The two labellers agree at 0.955, so the model is about 0.1 below label consistency.
- **Data curve.** 25 % / 50 % / 100 % of the training data give F1 0.815 / 0.827 / 0.845 on the 303-image exam; it is still rising.
- **Environment shift.** A dark theme costs −0.019 and a 1366×768 screen −0.024.
- **Same exam, other parsers.** Classical CV + OCR scores 0.623 and OmniParser v2's detector 0.586.
- **Speed.** 44 ms per frame on an RTX 2060 and 260 ms on a laptop CPU (detector only, imgsz 1280).

## Known weaknesses

These are visible in the trees that agents read; see [PAPER.md §6](https://github.com/SentimentalK/pixeltree/blob/main/PAPER.md).

- **Icons without names, or with garbled names.** Names come from OCR, so a pure icon gets `""`, and some glyphs are read as characters: a search icon as `"Q √"`, a menu icon as `"目"`, a view toggle as `"业"`.
- **No state.** Nothing says whether a checkbox is checked, a toggle is on, or a row is selected.
- **Duplicate rows.** The detector sometimes boxes both a whole row and its parts, so one control can appear as two or three lines, for example a checkbox, its list row and its label.
- **Weak classes** (strict F1 on held-out apps): progressbar 0.145, slider 0.528, tab 0.533, combobox 0.583. Tabs are often called buttons.
- **Dimmed backgrounds.** Content under a dimming overlay is sometimes boxed.
- **Narrow domain.** Mostly light-theme Linux (GTK / Qt / Electron) apps and web pages at 1920×1080. Windows and macOS are under-represented.

## Not intended for

- Accessibility-compliance decisions, or replacing an application's real accessibility tree for assistive-technology users.
- Unattended control of real user desktops, or security-relevant automation. All our agent runs were in isolated virtual displays with synthetic data.
- Reading element state or icon meaning: the model has neither.

## Licence

AGPL-3.0. The model is a fine-tune of Ultralytics YOLO11 (AGPL-3.0), and the code that runs it uses the Ultralytics library. Third-party notices: [NOTICE](https://github.com/SentimentalK/pixeltree/blob/main/NOTICE).

## Links

- Code, testbench, replay viewer, result tables: https://github.com/SentimentalK/pixeltree
- Short paper: [PAPER.md](https://github.com/SentimentalK/pixeltree/blob/main/PAPER.md)
- Model card in the repository: [weights/MODEL_CARD.md](https://github.com/SentimentalK/pixeltree/blob/main/weights/MODEL_CARD.md)
