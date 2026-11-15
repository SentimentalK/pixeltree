# Data, sources and licences

**This first release redistributes no training or exam images.** It contains:
- the trained detector weights, as a release asset rather than in git;
- the labelling recipe;
- result tables;
- 15 example agent episodes, recorded inside our sandboxed test apps;
- one example screenshot.

Licence statements for third-party projects below are our reading of their public repositories and dataset cards. Verify them yourself before relying on them.

## 1. Detector training and exam data

| source | what | images used | original licence / owner | redistributed here? |
|---|---|---|---|---|
| Linux app captures (ours) | Screenshots of open-source Linux desktop apps (65 app groups in train, where a group can be a dark-theme or narrow-window variant of an app), captured in private virtual displays with synthetic sandbox data | train 1,031 · exam 258 (10 held-out apps) | Screenshots are ours; the app UIs belong to their projects (mostly GPL / LGPL) | **No.** Possible in a later release after a per-app check |
| GroundCUA | Public desktop-app screenshot dataset with human boxes (`ServiceNow/GroundCUA` on Hugging Face); we relabelled a subset with our convention | train 1,707 (72 apps); its own 15-app exam split was used only as a cross-convention reference | MIT (dataset card) | **No images.** Our labels could be published later keyed by GroundCUA image IDs |
| Public websites | Headless-browser screenshots of public pages, no login | train 174 (11 sites) · exam 45 (3 held-out sites) | Copyright of each site's owner | **No**, and we do not plan to |
| Second-labeller sample | 50 exam images relabelled by Claude Sonnet for the agreement measurement | 50 | as above | No |
| Gold set | 186 images (72 Linux, 114 macOS: own captures and a Screen2AX-derived subset) labelled under the same convention, used only as an extra exam | 186 | ours / Screen2AX dataset terms | No |

Counts are from [results/labeling_cost.md](results/labeling_cost.md) and [results/D1_detector.md](results/D1_detector.md). The detector was trained on 2,782 images: the 2,912 training images minus a 130-image internal validation split.

All labels were produced by Claude Opus under the [box convention](labeling/box_convention_v1.md) and [prompt](labeling/prompts/label_rules_v1_1.md) in `labeling/`, with Claude Sonnet QA. No human labelling.

### Start checkpoint

The fine-tuned detector starts from an earlier checkpoint of ours: YOLO11s pre-trained on synthetic component-library pages, public web pages and GroundCUA. That checkpoint and its data are not released.

Starting from the public COCO YOLO11s instead costs about 0.006–0.01 F1 on the held-out Linux apps ([results/D1_detector.md](results/D1_detector.md), [results/D2_detector_side.md](results/D2_detector_side.md)).

## 2. Agent testbench

| item | source | licence | in this repo |
|---|---|---|---|
| 48 task sentences, oracles, positive scripts | ours | AGPL-3.0 (this repo) | yes (`bench/`) |
| Oracle test fixtures (`bench/tests/fixtures/*.tar.gz`) | end states produced in sandbox HOMEs with synthetic data ("Test User", `demo-repo`, …) | ours | yes |
| Apps under test: Drawing, gitg, KeePassXC, Lutris, Obsidian, Okular, GNOME Calendar, GNOME Contacts | installed from distribution packages / Flatpak | their own licences (Obsidian is proprietary freeware; the others are GPL-family) | **not included**; `bench/README.md` says how to install them |
| OmniParser v2 (baseline condition `T_omni`) | microsoft/OmniParser and its Hugging Face weights | see upstream | **no code or weights included**; only a client and setup notes |

## 3. Example episodes and screenshot

- `examples/episodes/` holds 15 episodes recorded on our testbench: Drawing, gitg, GNOME Contacts, KeePassXC.
  - Screenshots are 1280×720 WebP re-encodings of the sandboxed app windows. They show only synthetic sandbox data.
  - The episodes keep the agent's tool calls, its visible text and the grader's verdict.
  - Raw API logs and sandbox home directories are not included.
- `examples/screenshots/gitg.png` is one sandbox screenshot (gitg on a synthetic repository).
- The screenshots show the apps' own UIs, which remain under their projects' licences.

## 4. What could be released later — decisions for the owner

1. Our labels for the GroundCUA subset (1,707 train images), keyed by GroundCUA IDs. GroundCUA is MIT, so this looks straightforward.
2. Our own Linux app captures (1,289 images), with labels. Needs a per-app look at the UI content; the sandbox data is synthetic.
3. The 303-image exam with labels: the 258 Linux captures; the 45 website images would be withheld.
4. The full archive of agent episodes (~2,000 episodes) as trace directories, after the same scrub as the examples.
5. Website screenshots: not planned.

## 5. Model outputs used as labels

Labels and QA verdicts were generated with Claude models through the official CLI. Check the provider's current terms for your intended use of model-generated labels before redistributing derived datasets.
