# pixeltree

**Screenshot → element tree for GUI agents, a Linux desktop agent testbench, and an offline replay viewer.**

We distilled a frontier model's "look at the screen" ability into a 19 MB local detector. With OCR, it turns any screenshot into a text list of elements, one line per element:

```
aria:button [e7] "Save" @(1119,7,43,22) c=(1140,18)
```

We then measured, on 48 programmatically graded tasks in 8 unseen Linux apps, which agents actually benefit from such a tree. This repository is a research release: the code, the weights, the testbench, example episodes and every result table, so that others can continue. The full write-up is **[PAPER.md](PAPER.md)** (中文：[PAPER.zh.md](PAPER.zh.md)).

## Findings in one page

- **The detector.** YOLO11s fine-tuned on 2,782 screenshots labelled by Claude Opus (about $0.32 per image, API-equivalent). On 10 Linux apps never seen in training it finds elements at class-agnostic F1 **0.854**. Two independent model labellers agree at 0.955, so there is headroom ([results/D1](results/D1_detector.md), [D2](results/D2_detector_side.md)).
- **Claude-class agents do not need the tree.**
  - Claude Haiku with only a screenshot: **86 %**. With only our tree: 57 %. Screenshot + tree: 81 %, no gain.
  - A "tree first, look when needed" agent was cheaper but 11 points worse ([results/R1](results/R1_main_exam.md), [R3](results/R3_tree_first.md)).
- **One other reader does better with it** (48 tasks, one run per cell, through the OMP CLI; 95 % intervals over tasks):
  - GLM 5.3 Flash: 41/48 with screenshot + tree vs 34/48 with the screenshot only, +15 points (2 to 27).
  - DeepSeek V4.1 Flash: 37/48 with the tree vs 34/48, +6 points (−8 to 21), a direction only.
  - Text-only LongCat 2.0: 33/48 with our tree vs 29/48 with the flat system accessibility tree, +8 points (−8 to 25), a direction only; the whole difference is on two GTK4 apps where that tree is empty ([results/R5](results/R5_four_readers.md)).
- **What the tree lacks.** Icons have no names or OCR-garbled names, controls have no state, and some elements appear twice. A token-saving cleaning rule of ours blanked the close button "×", and agents closed the app in 39 of 144 episodes ([PAPER §6](PAPER.md#6-negative-results-and-defects)).
- **A cheap fix for screenshot agents.** Drop the redundant `observe` tool and send the first screenshot with the task: 89 % vs 82 %, fewer steps and lower cost ([results/R3](results/R3_tree_first.md)).

## What is here

| path | what |
|---|---|
| [`PAPER.md`](PAPER.md), [`PAPER.zh.md`](PAPER.zh.md) | the short report (English / Chinese) |
| [`results/`](results/README.md) | every table the paper cites, Markdown + CSV, with source and protocol |
| [`pixeltree/perceive/`](pixeltree/perceive/) | screenshot → tree (detector + OCR); `python -m pixeltree.perceive shot.png` |
| [`pixeltree/formats/`](pixeltree/formats/) | compact tree format and change-only deltas; cleaning rules are experimental and off by default |
| [`pixeltree/trace/`](pixeltree/trace/), [`pixeltree/viewer/`](pixeltree/viewer/) | episode trace format and the offline replay viewer |
| [`weights/`](weights/MODEL_CARD.md) | model card, download script and checksum (weights are a release asset) |
| [`bench/`](bench/README.md) | the Linux desktop agent testbench: 48 tasks, oracles, Xvfb harness, six-tool MCP server, `claude -p` and OMP runners |
| [`labeling/`](labeling/README.md) | box convention, labelling prompt, labelling / QA / export / training / scoring scripts |
| [`examples/`](examples/) | one sandbox screenshot with its tree, and 15 recorded agent episodes |
| [`docs/`](docs/) | tree format and trace format |
| [`DATA.md`](DATA.md) | data sources, licences, and what is (not) redistributed |
| [`tools/scrub_check.py`](tools/scrub_check.py) | the pre-publication scrub check run in CI |

## Quick start

Python 3.11+. The OCR and detector run on CPU by default.

```sh
git clone https://github.com/SentimentalK/pixeltree && cd pixeltree
python3.11 -m venv .venv && . .venv/bin/activate
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu   # CPU wheels; skip if you have torch
pip install -e ".[perceive,dev]"
python weights/download.py                      # -> ~/.cache/pixeltree/pixeltree-detector-v1.pt, sha256-checked
```

While the repository is private, anonymous downloads of the release asset return 404. Use the GitHub CLI while logged in instead: `gh release download v0.1.0 -R SentimentalK/pixeltree -p pixeltree-detector-v1.pt -D ~/.cache/pixeltree`, then `python weights/download.py --check ~/.cache/pixeltree/pixeltree-detector-v1.pt`.

**1. Screenshot → tree**

```sh
python -m pixeltree.perceive examples/screenshots/gitg.png              # tree as text on stdout
python -m pixeltree.perceive examples/screenshots/gitg.png --json tree.json --text tree.txt
```

The expected output is in [`examples/screenshots/gitg.tree.txt`](examples/screenshots/gitg.tree.txt). Use `--weights PATH` or `PIXELTREE_WEIGHTS` for a local weight file, and `--device 0` or `PIXELTREE_DEVICE=0` for a CUDA GPU.

**2. Replay the example episodes**

```sh
python -m pixeltree.viewer build --traces examples/episodes --out site
# open site/index.html in a browser: a static site, works from file://, no network
```

**3. Tests**

```sh
pip install -e ".[dev,bench]"
python -m pytest -q
python tools/scrub_check.py
```

**4. The testbench** needs Xvfb, the eight apps and an agent CLI. It is a research testbench, not a product; see [bench/README.md](bench/README.md).

### Platform notes

- **Linux x86-64** is what we used and tested.
- **macOS and Windows.** The detector and OCR should install wherever `torch`, `onnxruntime` and `rapidocr` do. The testbench is Linux-only (Xvfb, AT-SPI).
- **Python versions.** The pinned `rapidocr==3.10.0` / `ultralytics==8.4.182` were used with Python 3.11–3.14. If `onnxruntime` has no wheel for your Python version, use 3.11.

## Status

Research prototype, released to show the idea and its limits — not a maintained product. Numbers in the paper are from the runs described there; the repository reproduces the code paths, not the runs' exact model versions or API behaviour.

## Licence

AGPL-3.0 ([LICENSE](LICENSE)). The detector is a derivative of Ultralytics YOLO11 (AGPL-3.0). Third-party notices are in [NOTICE](NOTICE), data terms in [DATA.md](DATA.md).

## How to cite

```bibtex
@misc{xu2026pixeltree,
  author       = {Xinghan Xu},
  title        = {pixeltree: distilling "look at the screen" into a small local model --- what worked, what did not},
  year         = {2026},
  howpublished = {\url{https://github.com/SentimentalK/pixeltree}},
  note         = {arXiv: to be added}
}
```
