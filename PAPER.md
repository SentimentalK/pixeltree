# pixeltree: distilling "look at the screen" into a small local model — what worked, what did not

*A short technical report. Status: research prototype. Chinese version: [PAPER.zh.md](PAPER.zh.md).*

**Summary.** We trained a small object detector (YOLO11s, 19 MB) on 2,782 desktop and web screenshots labelled by a frontier model (Claude Opus) under a written box convention, and combined it with OCR to turn any screenshot into a text list of on-screen elements ("the tree"). On 10 Linux applications never seen in training it finds elements with class-agnostic F1 0.854 against the same labelling convention. We then built a testbench of 48 programmatically graded tasks in 8 unseen Linux desktop apps and asked whether agents do better reading our tree, the system accessibility tree, or a plain screenshot. The answer depends on the reader. A Claude-class agent (Claude Haiku) does best with the screenshot alone (86 %) and gains nothing from adding our tree. One non-Claude model that can see images (GLM 5.3 Flash) did better with the screenshot plus our tree than with the screenshot alone (+15 points, 95 % interval 2 to 27, 48 tasks); for another (DeepSeek V4.1 Flash) the tree helped only as a direction. A text-only model (LongCat 2.0) can use the desktop only through a tree: ours worked where the system tree was empty, while elsewhere the system tree did as well or better. The tree's weaknesses are concrete: icons have no names or garbled names, controls have no state, some elements appear twice, and a token-saving cleaning rule we wrote deleted the close button's "×" and made agents close the app. We release the detector, the screenshot-to-tree code, the testbench, a replay viewer with example episodes, the labelling recipe and all result tables, as a starting point for teams who can take it further.

All numbers below come from tables in [`results/`](results/README.md); each is followed by the file it comes from.

---

## 1. Problem and motivation

GUI agents need to know what is on the screen: which elements exist, what they are called, where they are, and what state they are in. Three sources are common:

1. **The screenshot itself**, read by a multimodal model.
2. **The system accessibility tree** (AT-SPI on Linux, UIA on Windows, AX on macOS). It is exact when apps implement it, but coverage is uneven: in our exam two GTK4 apps report no usable coordinates at all ([results/R1_main_exam.md](results/R1_main_exam.md)).
3. **A screen parser** that turns pixels into a list of elements, such as OmniParser [1] or Screen2AX [2].

Our question was whether option 3 could be a *small local model* that distils the frontier model's ability to "look at the screen" into a text tree, so that an agent — possibly one that cannot see images at all — reads only the tree. If that worked, the tree would be cheaper than pixels, work where the accessibility tree is broken, and let text-only or small models drive a desktop.

We tested this end to end: label → train → build the tree → let agents use it on real tasks with programmatic grading. Section 5 says where the idea held and where it did not.

## 2. What the tree is

For every screenshot the detector proposes boxes with one of 16 roles (ARIA-like: `aria:button`, `aria:textbox`, `aria:listitem`, `vax:visibleText`, …). OCR reads the text inside each box; that text is the element's name. Names never come from guessing: an icon without readable text gets an empty name. Each element becomes one line:

```
role [id] "name" @(left, top, width, height) c=(centre_x, centre_y)
```

A real example — the first lines GLM 5.3 Flash received for the Drawing app just after launch (screenshot + tree condition, coordinates in the 1280×720 frame; replay: [`examples/episodes/r5__glm__drawing_no_ctrl_zoom__H_ours__r0`](examples/episodes/)):

```
aria:button [e1] "Open" @(7,7,44,22) c=(29,18)
aria:combobox [e2] "" @(57,7,37,22) c=(75,18)
aria:button [e3] "Q √" @(57,7,37,22) c=(75,18)
aria:button [e4] "" @(99,7,23,22) c=(110,18)
aria:button [e5] "" @(123,7,23,22) c=(134,18)
vax:visibleText [e6] "Drawing" @(620,7,39,10) c=(639,12)
aria:button [e7] "Save" @(1119,7,43,22) c=(1140,18)
aria:button [e8] "目" @(1165,7,24,23) c=(1177,18)
aria:button [e11] "×" @(1254,10,16,15) c=(1262,17)
```

**Good:** buttons with text ("Open", "Save") are boxed tightly and named correctly, and their centres can be clicked directly. GLM used the centre of `目` to open the menu at its second step and finished the task in five steps.

**Bad**, all visible in nine lines:
- icon buttons have no name (`e4`, `e5`);
- names that exist are often OCR of a glyph: the search icon reads `"Q √"`, the menu icon `"目"`;
- the same place appears twice (`e2` and `e3` have identical boxes);
- nothing says whether a toggle is on or off.

The format, the JSON form, a compact variant and a delta encoding are documented in [docs/tree_format.md](docs/tree_format.md).

## 3. How it was built

### 3.1 Box convention

Labels from different sources (DOM, human datasets, accessibility trees, model labellers) draw boxes differently: loose margins, invisible row widths, containers versus leaves. We wrote one convention — "the tight box of what is painted now" — with rules for rows, text lines, icons, overlays and dimmed backgrounds, and used it for every label ([labeling/box_convention_v1.md](labeling/box_convention_v1.md)).

### 3.2 Frontier-model labelling

Claude Opus labelled each screenshot from a fixed prompt that states the convention ([labeling/prompts/label_rules_v1_1.md](labeling/prompts/label_rules_v1_1.md)); large screens are labelled in tiles and merged. Claude Sonnet re-checked a sample for quality, and flagged images went through a fix round. In total 3,215 images (2,912 training, 303 exam) cost $1,044.74 in API-equivalent terms, about $0.32 per image including QA and fixes ([results/labeling_cost.md](results/labeling_cost.md)). Sources: real Linux app screenshots captured in private virtual displays, screenshots from the public GroundCUA dataset, and public websites (see [DATA.md](DATA.md)).

How good are the labels? A second labeller (Claude Sonnet, same prompt, 50 exam images) agrees with the Opus labels at class-agnostic F1 0.955 ([results/D2_detector_side.md](results/D2_detector_side.md)). Both labellers come from the same model family and read the same rules, so this measures consistency, not correctness.

### 3.3 Detector

YOLO11s at 1280 px input, fine-tuned for 40 epochs on 2,782 labelled images (21 minutes on one A100) ([results/D1_detector.md](results/D1_detector.md)). Evaluation: greedy one-to-one matching at IoU ≥ 0.5; "class-agnostic" ignores the role, "strict" requires it; thresholds 0.25 and 0.45 are both reported and were never tuned on the exam ([results/D1_detector.md](results/D1_detector.md)).

| | held-out Linux apps (10 apps, 258 images) | held-out websites (3 sites, 45 images) |
|---|---|---|
| fine-tuned detector, class-agnostic F1 @0.25 / @0.45 | **0.854 / 0.874** | 0.787 / 0.813 |
| same, strict F1 @0.25 | 0.798 | — |
| start checkpoint without fine-tuning | 0.489 / 0.212 | 0.549 / 0.510 |

([results/D1_detector.md](results/D1_detector.md))

- **Labelling gap.** The detector agrees with each labeller at about 0.85 (0.855 with Opus, 0.853 with Sonnet), while the two labellers agree at 0.955. The model is about 0.1 below label consistency, so labels are not yet the ceiling ([results/D2_detector_side.md](results/D2_detector_side.md)).
- **The starting checkpoint matters little.** Our start checkpoint was pre-trained on synthetic and web data that we do not release. Starting from the public COCO YOLO11s gives 0.848 on the held-out apps, 0.006 lower ([results/D1_detector.md](results/D1_detector.md)); across two seeds the gap stays about 0.01 ([results/D2_detector_side.md](results/D2_detector_side.md)).
- **Data curve.** On the 303-image exam, 25 % / 50 % / 100 % of the training set give F1 0.815 / 0.827 / 0.845. Each doubling still adds about 0.012–0.018, with bootstrap intervals above zero, so the curve has not flattened ([results/D2_detector_side.md](results/D2_detector_side.md)).
- **Robustness.** A dark theme costs −0.019 and a 1366×768 screen −0.024 ([results/D2_detector_side.md](results/D2_detector_side.md)).
- **Baselines on the same exam.** A classical CV + OCR pipeline scores 0.623 and OmniParser v2's detector 0.586; the gap is almost all recall ([results/D2_detector_side.md](results/D2_detector_side.md)).
- **Speed.** 44 ms per frame on an RTX 2060 and 260 ms on a laptop CPU for the detector ([results/D1_detector.md](results/D1_detector.md)); with OCR, a full observation took about 0.45 s in the agent runs ([results/R1_main_exam.md](results/R1_main_exam.md); see the device note there).

## 4. Testbench

[`bench/`](bench/README.md) is a research testbench, not a product.

- **Apps and tasks.** 8 Linux desktop apps that are not in the detector's training data: Drawing, gitg, KeePassXC, Lutris, Obsidian, Okular — whose accessibility trees work — and GNOME Calendar and GNOME Contacts, whose GTK4 accessibility trees report no coordinates. Each app has 6 tasks (2 easy, 3 medium, 1 hard), 48 in total, frozen before the first run ([bench/TASKS.md](bench/TASKS.md)).
- **Grading.** After the agent finishes, the app is closed and an oracle reads the state the app actually saved: files, SQLite, iCalendar / vCard via the data server, the KeePass database via its CLI, git, PDF annotations, settings. No human or model judge. Every oracle was checked against a scripted positive run (must pass) and a no-op run (must fail). After the first run an audit found one parser bug (Okular annotations saved as a new PDF object generation); oracle v1.1 fixes only that, and every episode was re-graded from its archived end state.
- **Environment.** Every episode runs in a private Xvfb display at 1920×1080 with a fresh sandbox HOME, and the app is relaunched each time.
- **Tools.** The agent gets exactly six tools through one MCP server: `observe`, `click(x, y)`, `type`, `key` (a whitelist with no shortcuts), `scroll`, `done`, with a limit of 20 calls.
- **Conditions** differ only in what `observe` returns and in one paragraph of the system prompt:
  - `S_shot`: a 1280×720 screenshot;
  - `T_ours`: our tree as text only;
  - `T_atspi`: the system accessibility tree as text only;
  - `T_omni`: OmniParser v2's output as text only;
  - `H_ours` / `H_atspi`: the screenshot plus a tree, in one coordinate frame.

  The AT-SPI baseline is deliberately simple: a flat list of role, name and box, clicked by coordinates, with no control states and no "act on element" interface.
- **Lockdown.** The agent CLI is started with every built-in tool disabled and only the six tools allowed, in an empty working directory. A probe asking the agent to read files, write files, run a shell or browse passed in every condition.
- **Shells.** Two agent shells were used: `claude -p` (R1, R3) and OMP (R5, for non-Claude models through an OpenAI-style provider). For OMP we (a) replaced its added system-prompt blocks with the benchmark prompt through a request hook, (b) turned off its automatic behaviours, and (c) added an ordering gate (§6.4). We calibrated the shell by running Claude Haiku through both ([results/R5_four_readers.md](results/R5_four_readers.md)).

Experiment codes used throughout:

| code | what | reader(s) | size |
|---|---|---|---|
| R1 | main exam, 7 conditions | Claude Haiku (Sonnet for one condition), `claude -p` | 48 tasks × 3 runs, 1,008 episodes |
| R2 | offline token accounting of tree formats | — (no model calls) | 1,826 archived observations |
| R3 | tree-first agent with hover / look | Claude Haiku, `claude -p` | 48 tasks × 3 runs, 768 episodes |
| R4 | Gemini through another CLI | Gemini 3.8 Flash | 1 complete task (quota ran out) |
| R5 | four readers through one shell | GLM 5.3 Flash, DeepSeek V4.1 Flash, LongCat 2.0 (text only), Claude Haiku, OMP | 48 tasks × 1 run |
| D1 | detector training arms | — | 303-image exam |
| D2 | detector side experiments | — | same exam + 50-image second labeller |

## 5. Results

Read each model only against itself. Do not compare absolute numbers across models or shells. R5 has one run per cell on 48 tasks; we report 95 % bootstrap intervals over tasks and treat a difference whose interval includes 0 as a direction only ([results/R5_four_readers.md](results/R5_four_readers.md)).

### 5.1 Claude-class agents do not need the tree

R1, Claude Haiku, 48 tasks × 3 runs, success with 95 % task-bootstrap intervals ([results/R1_main_exam.md](results/R1_main_exam.md)):

| condition | success | $ per success |
|---|---|---|
| screenshot only | **86 %** [78, 94] | 0.0057 |
| screenshot only, Claude Sonnet | 85 % [75, 94] | 0.0721 |
| screenshot + AT-SPI tree | 84 % [74, 92] | 0.0113 |
| screenshot + our tree | 81 % [70, 90] | 0.0146 |
| our tree only | 57 % [44, 69] | 0.0146 |
| AT-SPI tree only | 52 % [39, 65] | 0.0133 |
| OmniParser v2 tree only | 44 % [31, 56] | 0.0170 |

- **Adding our tree does not help.** Screenshot + our tree vs screenshot alone: −5.6 points [−13.2, +1.4]; with the AT-SPI tree −2.1 [−7.6, +2.1] ([results/R1_main_exam.md](results/R1_main_exam.md)).
- **Mechanism (exploratory).** On the 16 tasks where our tree alone always failed, adding it to the screenshot hurt (−20.8 [−37.5, −4.2]); on the other 32 it was neutral (+2.1 [−2.1, +7.3]). A wrong tree misleads; a right tree repeats the pixels ([results/R1_main_exam.md](results/R1_main_exam.md)).
- **Tree only vs the alternatives.** Our tree alone is level with the flat AT-SPI list overall (+4.9 [−9.7, +20.1]) and beats OmniParser v2 (+13.2 [+2.1, +24.3]). On the two apps whose accessibility tree is empty it is +52.8 [+25.0, +77.8] ahead ([results/R1_main_exam.md](results/R1_main_exam.md)).
- **Why our tree fails.** In a sample of failures it rarely missed the element (0 of 8). It named it wrongly — for example gitg's stage-view button OCR'd as "业" — or the agent mis-planned ([results/R1_main_exam.md](results/R1_main_exam.md)).
- **Same ranking through the other shell.** Through OMP, Haiku again ranks the screenshot above the tree: 0 wins, 12 losses, 36 ties over 48 tasks, −25 points (95 % interval −38 to −12), and screenshot + tree equals the screenshot (+2, −4 to 8). Haiku through OMP stays within 5 points of Haiku through `claude -p` in every condition, all intervals including 0 ([results/R5_four_readers.md](results/R5_four_readers.md)). Replay: [`r5__haiku__gitg_commit_readme__T_ours__r0`](examples/episodes/) fails after cycling between the file list and the bottom buttons; [`r5__haiku__gitg_commit_readme__S_shot__r0`](examples/episodes/) succeeds; the `claude -p` episodes `r1__haiku__gitg_commit_readme__{T_ours,S_shot}__r0` go the same way.

**Tree-first does not rescue it either (R3).** We gave Haiku a cleaned, compact tree that sends only changes after each action, plus a `hover` tool and a `look` tool that returns a screenshot on demand ([results/R3_tree_first.md](results/R3_tree_first.md)):
- It succeeded 71 % [59, 83] against 82 % [72, 91] for the screenshot agent in the same batch, a difference of −11.1 [−19.4, −4.2].
- It was cheaper (0.75× cost per episode) but slower (26.0 vs 21.8 s).
- It did not really work tree-first: 91 % of its episodes looked at the screenshot at least once.

### 5.2 One non-Claude reader does better with the tree added

R5, 48 tasks, one run per cell, through OMP; 95 % intervals in brackets ([results/R5_four_readers.md](results/R5_four_readers.md)):

| reader | screenshot | our tree | screenshot + our tree | AT-SPI tree |
|---|---|---|---|---|
| GLM 5.3 Flash | 34/48 (56–83 %) | 34/48 (58–83 %) | **41/48** (75–94 %) | – |
| DeepSeek V4.1 Flash | 34/48 (58–83 %) | 37/48 (65–88 %) | **39/48** (69–92 %) | – |
| LongCat 2.0 (no image input) | – | **33/48** (54–81 %) | – | 29/48 (46–75 %) |
| Claude Haiku (shell calibration) | 39/48 (71–92 %) | 27/48 (44–71 %) | **40/48** (73–92 %) | – |

- **GLM.** Screenshot + tree is its best condition: 15 points above the screenshot alone (95 % interval 2 to 27), with 9 wins, 2 losses and 37 ties by task. This is the one difference between conditions of a non-Claude reader in R5 whose interval excludes 0. Tree alone ties with the screenshot (0, −12 to 15). On the first 27 tasks the hybrid gain was 26 points; on the 21 later tasks both conditions scored 17/21.
- **DeepSeek.** Tree alone is 6 points above the screenshot (8 wins / 5 losses / 35 ties; interval −8 to 21), and screenshot + tree 10 points above it (0 to 21). Both intervals reach 0, so we read them as directions only (11 points for the tree on the first 27 tasks).
- **Example (gitg, "stage only README.md").** DeepSeek with the screenshot used all 20 steps and staged nothing. With the tree it also flailed for 12 steps; at step 13 it clicked the button named "业" (the stage-view toggle). The next tree contained "Staged" and "Stage selection", and it finished at step 18. Replay: [`r5__deepseek__gitg_stage_readme__S_shot__r0`](examples/episodes/) vs [`r5__deepseek__gitg_stage_readme__T_ours__r0`](examples/episodes/); all readers on this task side by side on the viewer's task page.
- **Not just poor clicking.** Why these models benefit is not separated by our data. A click audit found DeepSeek's screenshot clicks on target 24 of 24 times, so imprecise clicking alone does not explain it ([results/R5_four_readers.md](results/R5_four_readers.md)).
- **Gemini (R4).** Only one complete task before the CLI quota ran out. Pooling every graded episode on 5 tasks gives screenshot 3/7, tree 5/5, screenshot + tree 5/5 — a direction, not a result ([results/R4_gemini.md](results/R4_gemini.md)).

### 5.3 A text-only model can use the desktop through the tree, including where the system tree is empty

LongCat 2.0 cannot take images. Reading our tree it completed 33 of 48 tasks; reading the AT-SPI list, 29 of 48; by task 10 wins, 6 losses, 32 ties, +8 points with an interval of −8 to 25, so only a direction overall ([results/R5_four_readers.md](results/R5_four_readers.md)). Twelve of its tree episodes hit the 10-minute cap.

The whole difference comes from GNOME Contacts and GNOME Calendar, where the AT-SPI list scored 0/6 and 0/6 because it contains no elements (our tree: 6/6 and 3/6). On the other six apps the AT-SPI list was ahead, 29/36 against 24/36 ([results/R5_four_readers.md](results/R5_four_readers.md)). Replay: [`r5__longcat__gnome_contacts_email__T_atspi__r0`](examples/episodes/) receives "0 elements" at every step and can only press Tab and Escape blindly; [`r5__longcat__gnome_contacts_email__T_ours__r0`](examples/episodes/) creates the contact in 8 steps.

### 5.4 Cost and tokens

- **The raw tree is not cheaper than pixels.** Our tree averaged about 2,040 tokens per step, 1.6× a 1280×720 screenshot (about 1,154 tokens), because it lists every element in full ([results/R1_main_exam.md](results/R1_main_exam.md)).
- **Compact formats on archived observations (R2, no model calls).** Episode-mean tokens per step ([results/R2_token_accounting.md](results/R2_token_accounting.md)):
  - original format: 2,122;
  - compact lines: 818;
  - compact + cleaning: 594;
  - compact + cleaning + only-what-changed: 271.
- **Measured in a live run (R3).** The change-only lists cost 385 tokens per list step: tokens per character were about 15 % higher than estimated, and more steps fell back to a full list ([results/R3_tree_first.md](results/R3_tree_first.md)).
- **But the agent spent the savings.** The agent took more steps and asked for screenshots, so cost fell only to 0.75× while success dropped (§5.1).

### 5.5 A side finding: drop the redundant observe call

In R1, Haiku's screenshot agent made 573 `observe` calls in 1,694 tool calls: 144 were the first call of an episode and the other 429 came right after an action, which already returns a fresh observation ([results/R3_tree_first.md](results/R3_tree_first.md)). Removing the `observe` tool and attaching the first screenshot to the task message made the screenshot agent both better and cheaper ([results/R3_tree_first.md](results/R3_tree_first.md)):
- success 89 % [82, 95], +6.9 [+1.4, +13.2] over the standard screenshot agent;
- 9.0 steps instead of 11.5;
- $0.0038 per episode instead of $0.0048.

## 6. Negative results and defects

### 6.1 Tree-first did not pass

The working hypothesis — "a small local model builds the tree, the language model reads only the tree" — does not hold for Claude-class agents on these apps. Neither tree-only nor tree-first matched the screenshot (§5.1).

### 6.2 What the tree lacks

Each item has a replayable episode:

1. **Icons without names, or with garbled names.**
   - gitg's key toggle is "业", and DeepSeek needed 12 steps before trying it ([`r5__deepseek__gitg_stage_readme__T_ours__r0`](examples/episodes/), step 13).
   - In R1's failure sample, wrong or garbled names, not missing boxes, were the tree's main failure cause ([results/R1_main_exam.md](results/R1_main_exam.md)).
2. **No control state.**
   - KeePassXC's "Backup database file before saving" checkbox appears in the tree with no checked / unchecked state.
   - GLM ticked it at step 4, clicked it again at step 5 (the screenshots go unchecked → checked → unchecked) and failed the task ([`r5__glm__keepassxc_enable_backup__T_ours__r0`](examples/episodes/), step 5).
   - With the screenshot it succeeded.
3. **Duplicate rows.**
   - The same checkbox is listed three times: as a checkbox, as a list item and as text, with near-identical boxes.
   - Drawing's search field appears twice (§2).
   - This inflates the tree.

### 6.3 Our own cleaning rule broke the close button

To save tokens, the R3 cleaning rules blank the names of small non-text elements and of pure-symbol names. That also blanked the title-bar close button "×":
- Haiku took the rightmost unnamed button for a menu and closed the app in 39 of 144 episodes, all of them failures. With the uncleaned tree it happened 0 times in 144 ([results/R3_tree_first.md](results/R3_tree_first.md)). Replay: [`r3__haiku__drawing_no_ctrl_zoom__X1__r2`](examples/episodes/), step 2.
- Our offline guard did not catch it. The guard only checked elements that successful agents had clicked, and agents reading "×" never clicked it.

The cleaning code ships in `pixeltree/formats/clean.py` as experimental and off by default.

### 6.4 Two harness defects worth knowing about

1. **OMP ran tool calls out of order.** OMP sent all tool calls of one model message to the MCP server at once, and they executed in whatever order threads won the lock. Haiku batches calls, so text was typed before a field was focused.
   - On the first 24 tasks this cost Haiku 25–45 points: 42 / 33 / 46 % with racing calls vs 83 / 58 / 83 % in order ([results/R5_four_readers.md](results/R5_four_readers.md)).
   - Fix: the server executes calls in the order the model wrote them, recorded by a shell hook.
   - With the fix, OMP reproduces the `claude -p` numbers within a few points.
2. **Calls after the step limit.** With OMP's loop guard off, GLM kept calling `done` about 350 times after the 20-call limit. The runner now stops the shell once the limit is reached ([results/R5_four_readers.md](results/R5_four_readers.md)).

Also: a CLI agent started inside a project directory can pick up project-level context files. Run agents from an empty directory.

## 7. Limitations

- **R5 has one run per cell.** 48 tasks, one run per model and condition; the intervals resample tasks and do not include run-to-run variation on the same task ([results/R5_four_readers.md](results/R5_four_readers.md)).
- **Narrow coverage.** 8 Linux apps with fairly sparse screens: on average 26–103 detected elements per screen, depending on the app ([results/R2_token_accounting.md](results/R2_token_accounting.md)). Dense UIs, high-DPI screens, Windows and macOS are untested.
- **The AT-SPI baseline is only the flat form.** Role, name and box, clicked by coordinates, with no states and no element actions. It is not a ceiling for what system accessibility APIs can offer.
- **Gemini is anecdotal.** One complete task ([results/R4_gemini.md](results/R4_gemini.md)).
- **Readers are cloud models.** No small local model has been tested as the tree's reader.
- **Isolated runs.** All episodes run in isolated virtual displays with the app relaunched each time. Real desktops with several windows, notifications and personal data are untested.
- **Fixed dates.** Calendar tasks assume runs in the week of 2026-11-08 to 2026-11-14; the oracles use real dates (see [bench/README.md](bench/README.md)).
- **Labels and convention.** The detector scores are against labels from one model family under our convention; they say nothing about other conventions such as GroundCUA's human boxes (see [results/D1_detector.md](results/D1_detector.md)).

## 8. Directions for whoever continues

1. **Distil "what is it" and "what state is it in", not only "where is it".** Boxes are mostly solved for these apps; the failures are icon meaning and control state. A small model that names icons and reports checked / selected / expanded / disabled would address the defects in §6.2 directly. Our labelling recipe can be extended with those fields.
2. **Per-app adaptation.** The data curve is still rising (§3.3), and the training set covers 148 app groups with about 20 frames each on average ([results/labeling_cost.md](results/labeling_cost.md)). Adapting to a new app may need only on the order of 100–250 automatically labelled frames of that app. This is untested: our estimate, not a result.
3. **Who benefits.** Trees helped two non-Claude image models and made a text-only model usable. Small local readers, and the reasons behind the benefit (perception vs grounding vs planning), are the open questions.
4. **Real time.** The viewer replays finished episodes. A live mode and a resident perception service (the detector + OCR loaded once) are natural next steps; per-episode model loading added about 12 s to the first step in R1 ([results/R1_main_exam.md](results/R1_main_exam.md)).
5. **Do not clean by rule.** If you compress the tree, measure harm on failed episodes too, not only on successful clicks (§6.3).

## 9. Related work

- [1] **OmniParser** (Lu et al., arXiv:2408.00203) parses screenshots into interactable regions with captions for vision-based GUI agents. We use its v2 release as a baseline, as a detector (§3.3) and as an agent's text input (§5.1).
- [2] **Screen2AX** (Muryn et al., arXiv:2507.16704) generates hierarchical macOS accessibility metadata from a screenshot.
- [3] **OSWorld** (Xie et al., arXiv:2404.07972) is a benchmark of open-ended tasks in real computer environments with execution-based evaluation. Our testbench follows the same idea of grading the app's real end state.
- [4] **OS-Harm** (Kuntz et al., arXiv:2506.14866) builds a safety benchmark for computer-use agents on top of OSWorld.
- [5] **OSWorld-Human** (Abhyankar et al., arXiv:2506.16042) measures agent efficiency against human trajectories and finds agents take far more steps than needed; compare our observation-step finding in §5.5.
- [6] **"Do GUI Agents Believe Their Eyes?"** (Zhang et al., arXiv:2607.04334) diagnoses whether agents trust pixels or structural text and finds they often trust stale or wrong structure. This matches our finding that a wrong tree misleads a screenshot-capable agent (§5.1).

## 10. What is in this repository

See [README.md](README.md) for the layout and quick start, [weights/MODEL_CARD.md](weights/MODEL_CARD.md) for the detector, and [DATA.md](DATA.md) for data sources and what is (not) redistributed.
