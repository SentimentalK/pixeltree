# R1 — North-star agent exam on held-out Linux desktop apps

## Source and protocol

- **Experiment:** R1, the main agent exam. It asks whether an agent can finish real tasks in Linux desktop apps it was never trained on, using (a) a small local detector plus OCR to build a UI tree, (b) the system accessibility tree (AT-SPI), (c) a screenshot, and (d) combinations and an OmniParser v2 baseline.
- **Date:** report dated 2026-11-11.
- **Agent:** Claude Haiku 5.5 in every condition except `S_shot_strong` (Claude Sonnet 5.5, screenshot only). Each episode is one `claude -p` run with a single MCP server exposing six tools (observe, click, type, key, scroll, done). Built-in tools are disabled; the agent can act only through the app UI.
- **Shell:** Each episode runs in a fresh, neutral working directory with a fresh sandbox HOME; the app is launched inside a private virtual X display, relaunched per episode, and closed gracefully before grading.
- **Tasks and split:** 48 frozen tasks in 8 held-out apps, 6 tasks per app (2 at difficulty 1, 3 at difficulty 2, 1 at difficulty 3). Apps are split into an AT-SPI "good" tier (drawing, gitg, keepassxc, lutris, obsidian, okular; 36 tasks) and a "poor" tier (gnome-calendar, gnome-contacts; 12 tasks, where AT-SPI boxes are missing or have zero extents). Tasks, oracles and the agent system prompt were frozen before the first episode.
- **Success definition:** an oracle program reads the app's real saved state (files, SQLite, iCalendar/vCard via EDS, KeePass database via keepassxc-cli, git repositories, PDF, XML, GSettings keyfile). No LLM judge. Each oracle was self-tested: a positive UI script passes it on 48/48 tasks, and a 5-second no-op fails it on 48/48.
- **Rate:** the mean over tasks of each task's mean over 3 repetitions. Each condition has 48 tasks × 3 reps = 144 episodes; 1,008 graded episodes in total.
- **Interval method:** percentile bootstrap over tasks, 2,000 resamples, seed 0. Intervals are 95 %.
- **Cost:** API-equivalent `total_cost_usd` from the Claude stream-json output. Pricing used: Haiku 5.5 $0.10 / $0.50 per million input / output tokens; Sonnet 5.5 $2 / $10; cache reads 0.1×, one-hour cache writes 2×.
- **Sample size:** 48 tasks, 8 apps, one Linux desktop, 1920×1080 display. The poor tier has 2 apps and 12 tasks, so its intervals are wide.

Conditions:

**Table conditions.** Conditions and what the agent sees.

| Code | What the agent sees |
|---|---|
| `S_shot` | Screenshot scaled to 1280×720 |
| `S_shot_strong` | Screenshot scaled to 1280×720, Sonnet 5.5 |
| `H_atspi` | Screenshot plus AT-SPI tree |
| `H_ours` | Screenshot plus our tree |
| `T_ours` | Our tree only (text) |
| `T_atspi` | AT-SPI tree only (text) |
| `T_omni` | OmniParser v2 tree only (text) |

Tree sources: `T_ours` and `H_ours` use the detector arm A from the detector experiment D1, conf 0.25, imgsz 1280, with names from OCR only (no guessed names for icons). `T_atspi` is the subtree of the last showing top-level window, showing nodes with positive width and height. `T_omni` is OmniParser v2 (icon detector v3, Florence-2 captions, EasyOCR, box threshold 0.05). Tree conditions receive one text line per element (`role [id] "name" @(x,y,w,h) c=(cx,cy)`, at most 400 lines); hybrid conditions receive the same screenshot plus the tree with every box converted to the 1280×720 frame.

Protocol notes:

1. **Context isolation.** In an early pilot the agent process inherited project context from its working directory and refused a task citing it. The fix runs every episode in a neutral directory, and the runner marks any episode whose initial working directory differs as an error. Pilot runs are excluded from all numbers.
2. **Oracle version 1.1.** A post-run audit found that oracle v1 read a PDF note with a regex that missed re-added notes, which failed 4 `S_shot_strong` episodes whose notes were saved. v1.1 reads the final PDF revision. Re-grading with v1.1 changed exactly those 4 episodes (false → true); v1 grades were reproduced identically from the archived end states before the change. No episode was rerun.
3. **Oracle audit.** All 48 oracles were checked against the end states of all 720 episodes of the first run. 46 were sound on every observed end state; 2 were the v1 bug above; 7 have a documented failure mode that was never observed. One wording ambiguity: a sentence in `obsidian_append_welcome` ends with a full stop that the oracle requires; `S_shot_strong` omitted it in 3 of 3 episodes, and 8 of the other 15 episodes typed it. It was kept as pre-registered; if the stop were optional, `S_shot_strong` would gain 3 episodes (about +2 points).
4. **Harness fault.** When memory was tight, the per-episode MCP server sometimes failed to load the detector and OCR, and the agent started with zero tools. Seven such episodes (2 in `T_ours`, 5 in `H_ours`) were marked as harness errors and rerun; the original rows are kept. No error rows remain.
5. **Tool lockdown.** The agent is started with no built-in tools, a strict MCP configuration, an allow-list of the six tools, a disallow-list for every built-in tool, no slash commands, no settings sources, no session persistence, and its own system prompt. A probe with a "permissions test" task (shell, file read and write, web fetch, subagent) passed for all 7 conditions: only the six tools were present, no foreign tool ran, and no file was written.
6. **Hybrid conditions ran later.** `H_*` ran after `T_*` and `S_*` on the same frozen tasks, oracles, flags and machine; comparisons are paired by task, but `S_shot` was not rerun alongside them.
7. **Fixed dates.** Calendar tasks assume the run takes place in the week 2026-11-08 to 2026-11-14; positive scripts and oracles use real dates.
8. **Timing.** Timings were measured with 3 episodes in parallel on one CPU-bound machine. OmniParser ran on a GPU; the detector and OCR ran on CPU.
9. **Not tested.** A frontier model reading our tree (optional in the design) and a text-only small local model as the consumer were not run.

## Results

**Table main.** Seven conditions, 48 tasks × 3 reps = 144 episodes per condition. Success is the mean over tasks; 95 % interval is a task bootstrap.

| Condition | What the agent sees | Success (95 % CI) | v1 oracle | Mean steps | Observation tokens / step | $ / episode | $ / success | Wall s / episode (median) |
|---|---|---|---|---|---|---|---|---|
| S_shot | screenshot 1280×720 | **86 % [78, 94]** | 86 % | 11.8 | 1,246 | 0.0049 | 0.0057 | 24 (18) |
| S_shot_strong | screenshot, **Sonnet 5.5** | 85 % [75, 94] | 82 % | 9.5 | 1,172 | 0.0611 | 0.0721 | 20 (16) |
| H_atspi | screenshot + AT-SPI tree | 84 % [74, 92] | 84 % | 11.5 | 2,787 | 0.0095 | 0.0113 | 30 (20) |
| H_ours | screenshot + our tree | 81 % [70, 90] | 81 % | 11.2 | 3,217 | 0.0118 | 0.0146 | 45 (35) |
| T_ours | our tree (text only) | 57 % [44, 69] | 57 % | 13.4 | 2,039 | 0.0083 | 0.0146 | 42 (39) |
| T_atspi | AT-SPI tree (text only) | 52 % [39, 65] | 52 % | 10.8 | 2,147 | 0.0069 | 0.0133 | 24 (18) |
| T_omni | OmniParser v2 tree (text only) | 44 % [31, 56] | 44 % | 14.1 | 1,415 | 0.0074 | 0.0170 | 51 (51) |

"v1 oracle" = the same episodes graded with the frozen v1 oracles; v1.1 changes only 4 `S_shot_strong` episodes (see protocol note 2). Observation tokens per step = least-squares fit of per-call context growth on tree characters, images and assistant characters (R² 0.976–0.999). Total spend for the 1,008 graded episodes: $15.84 API-equivalent, 9.4 agent-hours.

**Table paired.** Paired differences, A − B, in percentage points, task bootstrap intervals.

| A − B | All 48 tasks | Poor tier (12 tasks) | Good tier (36 tasks) |
|---|---|---|---|
| T_ours − T_atspi | +4.9 [−9.7, +20.1] | **+52.8 [+25.0, +77.8]** | −11.1 [−25.9, +3.7] |
| T_ours − T_omni | **+13.2 [+2.1, +24.3]** | +13.9 [0.0, +27.8] | +13.0 [−0.9, +27.8] |
| T_ours − S_shot | **−29.2 [−41.7, −17.4]** | −19.4 [−41.7, 0.0] | **−32.4 [−47.2, −18.5]** |
| T_atspi − S_shot | **−34.0 [−45.8, −22.2]** | **−72.2 [−91.7, −50.0]** | **−21.3 [−33.3, −10.2]** |
| S_shot_strong − S_shot | −1.4 [−6.9, +4.2] | −11.1 [−25.0, 0.0] | +1.9 [−4.6, +8.3] |
| H_ours − S_shot | −5.6 [−13.2, +1.4] | −11.1 [−30.6, +2.8] | −3.7 [−11.1, +3.7] |
| H_atspi − S_shot | −2.1 [−7.6, +2.1] | −5.6 [−25.0, +8.3] | −0.9 [−4.6, +1.9] |
| H_ours − H_atspi | −3.5 [−9.7, +2.8] | −5.6 [−19.4, +5.6] | −2.8 [−10.2, +4.6] |
| H_ours − T_ours | **+23.6 [+13.9, +34.0]** | +8.3 [−5.6, +22.2] | **+28.7 [+17.6, +40.7]** |
| H_atspi − T_atspi | **+31.9 [+20.1, +43.1]** | **+66.7 [+41.7, +88.9]** | **+20.4 [+9.3, +32.4]** |

**Mechanism split (exploratory, not pre-registered).** `H_ours − S_shot` split by whether `T_ours` alone ever solved the task: on the 16 tasks where `T_ours` failed in all 3 reps, −20.8 [−37.5, −4.2] pts; on the other 32 tasks, +2.1 [−2.1, +7.3] pts.

**Table by_app.** Task-level success by app (6 tasks each) and by difficulty (16 / 24 / 8 tasks).

| Group | T_ours | T_atspi | T_omni | S_shot | S_shot_strong | H_ours | H_atspi |
|---|---|---|---|---|---|---|---|
| drawing (good) | 50 | 39 | 17 | 83 | 83 | 78 | 83 |
| gitg (good) | 50 | 67 | 33 | 89 | 94 | 61 | 78 |
| keepassxc (good) | 72 | 89 | 78 | 100 | 100 | 100 | 100 |
| lutris (good) | 89 | 67 | 56 | 89 | 100 | 100 | 89 |
| obsidian (good) | 44 | 89 | 50 | 83 | 83 | 89 | 89 |
| okular (good) | 44 | 67 | 39 | 100 | 94 | 94 | 100 |
| gnome-calendar (poor) | 33 | 0 | 33 | 61 | 44 | 44 | 44 |
| gnome-contacts (poor) | 72 | 0 | 44 | 83 | 78 | 78 | 89 |
| difficulty 1 (16 tasks) | 77 | 75 | 75 | 98 | 96 | 92 | 98 |
| difficulty 2 (24 tasks) | 56 | 49 | 38 | 89 | 86 | 88 | 83 |
| difficulty 3 (8 tasks) | 21 | 17 | 0 | 54 | 58 | 37 | 58 |

**Table cost.** Tokens, cost and time measurements.

| Quantity | Value |
|---|---|
| Tree text, tokens per character (fit) | 0.58–0.62 |
| One 1280×720 screenshot, tokens (Haiku fit / Sonnet fit) | 1,154 / 1,224 |
| Our tree, average per step | 3,460 characters ≈ 2,040 tokens (1.6× one screenshot) |
| Model latency per step | 0.8–1.4 s |
| Observation time: screenshot / AT-SPI / our tree / OmniParser (GPU) | 0.08 s / 0.33 s / 0.45 s / 1.6 s |
| Median time to first tool call: `T_ours` and `H_ours` / other conditions | 21.2 s / 9.2 s |
| Total API-equivalent spend, 1,008 graded episodes | $15.84 |
| Agent time | 9.4 hours |

The detector and OCR load inside each episode's MCP server, which accounts for the roughly 12 s longer time to first tool call in `T_ours` and `H_ours`.

Device note: the source report labels the 0.45 s for our tree as CPU. When we later re-ran the released code on 30 archived observations, the GPU path (fp16 detector, CUDA OCR) reproduced the archived trees exactly (30/30) and the CPU path did not (see `docs/tree_format.md`), so the archived trees, and probably this timing, came from the GPU path.

**Table failures.** Failure causes in a sample of up to 8 failed episodes per condition (40 episodes in total, drawn with a fixed random seed). Each failure has one main cause, taken from the trajectory (screens, observation text, actions). Counts are episodes.

| Condition | Missing element | Wrong or empty name | Bad coordinates | Agent reasoning | Task ambiguity | Harness / oracle |
|---|---|---|---|---|---|---|
| T_ours | 0 | 3 | 1 | 4 | 0 | 0 |
| T_atspi | 4 (whole tree empty) | 2 | 0 | 2 | 0 | 0 |
| T_omni | 2 | 2 | 1 | 3 | 0 | 0 |
| S_shot | — | — | 0 | 8 | 0 | 0 |
| S_shot_strong | — | — | 0 | 6 | 0 | 2 (oracle bug, fixed in v1.1) |

Reading the failure table: in `T_ours` the element is rarely missing; it is more often named wrongly (OCR of an icon glyph, for example a stage button read as a CJK character, or a date-edit button read as "0"). In the screenshot conditions, failures are mostly reasoning errors (wrong field, early `done`, loops).
