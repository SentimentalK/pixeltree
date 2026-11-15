# R5 — Four model families as readers of screenshot, tree, and hybrid observations

## Source and protocol

- **Experiment:** R5 asks whether other model families rank the same three observation types (screenshot only, our tree only, screenshot plus our tree) in the same order as Claude. Readers: GLM 5.3 Flash, DeepSeek V4.1 Flash, LongCat 2.0 (text-only input, so only the tree conditions apply), and Claude Haiku 5.5 run through the same shell as a calibration.
- **Date:** 2026-11-13 (27 tasks); 2026-11-14 (remaining 21 tasks).
- **Status: complete.** 48 tasks, one run per model and condition. On 2026-11-13 the first 27 tasks were run (the first 24 of a stratified order, 3 per app, plus the 3 remaining gnome-calendar tasks, whose oracle only works until 2026-11-14); the other 21 followed on 2026-11-14.
- **Reading rule:** for the 48-task tables, a difference whose 95 % bootstrap interval (over tasks) includes 0 is reported as a direction only. The 27-task sections below used the earlier rule (differences under about 15 points not read as findings) and are kept as they were.
- **Do not compare absolute numbers across models or across shells.** Each model is compared only with itself across conditions. Claude Haiku 5.5 through this shell versus Claude Haiku 5.5 through the `claude -p` shell of R1 measures the shell, not a model difference. Wall-clock time and tokens are comparable only within one model.
- **Shell:** `omp` 18.16.0 with provider `opencode-go`, print mode with JSON output and no saved session; each episode runs in a fresh neutral working directory that contains only the MCP configuration.
- **Models and thinking level:** `glm-5.3-flash` (low), `deepseek-v4.1-flash` (low), `longcat-2.0` (low), `claude-haiku-5-5` (low). Each is the lowest reasoning level above off / minimal that the shell lists. Haiku used 0 reasoning tokens.
- **Conditions:** as in R1 (`S_shot`, `T_ours`, `H_ours`; LongCat: `T_ours` and `T_atspi`). The system prompt is the R1 text verbatim. `S_shot` and `H_ours` received the coordinate sentence added in R4. Trees are the R1 `T_ours` / `H_ours` trees (not the cleaned R2 version), produced by the same resident perception service.
- **Tools:** the six R1 tools; their schemas were checked to be identical to R1's. 20-call limit and the same step archive.
- **Tasks and grading:** R1's frozen tasks and the oracle v1.1 (the task oracle reads the app's saved state after the app closes; no model or human judge). The order is the stratified order used in R4: each app's six tasks shuffled with seed 0, one task per app per block, block order shuffled, the conditions of a task adjacent with a rotating start.
- **Per-episode cap:** 10 minutes of wall-clock time (R1 used 15). A timeout counts as a failure and stays in the denominator. LongCat had 12 timeouts in `T_ours` and 3 in `T_atspi` over 48 tasks (8 and 2 in the 27-task scope).
- **Denominators:** the final tables have 0 invalid episodes and 0 harness errors, so every episode run is counted. Each cell has 48 tasks (earlier sections: 24 in scope A, 27 in scope B), one run per task.
- **Success:** oracle v1.1 passed.
- **Tool-call lockdown:** all four models passed the lockdown probe (same tests as R1); no model attempted a tool outside the six in the formal episodes.
- **Image input:** the OpenAI-compatible providers (GLM, DeepSeek, LongCat) cannot carry images inside a tool message, so the shell adds a user message with the image after the tool result. Claude Haiku receives the image inside the tool result. Images were 1280×720 in every request.
- **Shell defect and fix (affects Haiku most):** the shell sends all tool calls of one assistant message to the MCP server at once and the server executed them in arbitrary order. In the first pass, Haiku through this shell scored 42 / 33 / 46 % on the first 24 tasks, against 85 / 51 / 79 % in R1. The fix runs the calls one at a time in the written order (order gate). Episodes that contained a multi-call message in the first pass were rerun. The episodes that were not affected by the race are kept as they were. The rule for "affected" depends only on the transcript, not on success.
- **Sample size:** 48 tasks per model and condition, one run each (the earlier sections: 24 or 27).

## Results, all 48 tasks (2026-11-14)

The remaining 21 tasks were run on 2026-11-14 under the same protocol, with the order gate in place from the start (no reruns needed; an order probe passed for every model first). All 528 episodes: 0 invalid, 0 quota errors, 0 harness errors. Intervals are 95 % percentile intervals from a bootstrap over tasks (2,000 resamples, seed 0). A difference whose interval includes 0 is reported as a direction only.

**Table all48.** All 48 tasks, success as count, percentage and 95 % interval.

| Model (shell) | S_shot | T_ours | H_ours | T_atspi |
|---|---|---|---|---|
| GLM 5.3 Flash | 34/48 (71 %; 56–83) | 34/48 (71 %; 58–83) | 41/48 (85 %; 75–94) | – |
| DeepSeek V4.1 Flash | 34/48 (71 %; 58–83) | 37/48 (77 %; 65–88) | 39/48 (81 %; 69–92) | – |
| LongCat 2.0 (no image input) | – | 33/48 (69 %; 54–81); 12 timeouts | – | 29/48 (60 %; 46–75); 3 timeouts |
| Claude Haiku 5.5 (this shell, calibration) | 39/48 (81 %; 71–92) | 27/48 (56 %; 44–71) | 40/48 (83 %; 73–92) | – |
| Claude Haiku 5.5 (R1 `claude -p` shell), 48 tasks, mean of 3 reps | 86 % | 57 % | 81 % | – |

**Table paired48.** Paired differences between conditions over the 48 tasks, with the 27-task reading for comparison.

| Model | Pair | All 48 tasks: win / loss / tie, mean difference (95 % interval), points | Scope B (27): win / loss / tie (mean) | Reading |
|---|---|---|---|---|
| GLM | T_ours − S_shot | 6 / 6 / 36, 0 (−12 to +15) | 5 / 4 / 18 (+4) | tie |
| GLM | H_ours − S_shot | 9 / 2 / 37, +15 (+2 to +27) | 9 / 2 / 16 (+26) | holds, smaller |
| GLM | H_ours − T_ours | 10 / 3 / 35, +15 (0 to +27) | 8 / 2 / 17 (+22) | lower bound at 0: direction |
| DeepSeek | T_ours − S_shot | 8 / 5 / 35, +6 (−8 to +21) | 6 / 3 / 18 (+11) | weaker: direction only |
| DeepSeek | H_ours − S_shot | 6 / 1 / 41, +10 (0 to +21) | 3 / 1 / 23 (+7) | lower bound at 0: direction |
| DeepSeek | H_ours − T_ours | 5 / 3 / 40, +4 (−8 to +15) | 2 / 3 / 22 (−4) | no difference |
| LongCat | T_ours − T_atspi | 10 / 6 / 32, +8 (−8 to +25) | 7 / 3 / 17 (+15) | weaker: direction only |
| Claude Haiku 5.5 | T_ours − S_shot | 0 / 12 / 36, −25 (−38 to −12) | 0 / 6 / 21 (−22) | holds, stronger |
| Claude Haiku 5.5 | H_ours − S_shot | 2 / 1 / 45, +2 (−4 to +8) | 1 / 1 / 25 (0) | no difference |
| Claude Haiku 5.5 | H_ours − T_ours | 13 / 0 / 35, +27 (+15 to +40) | 6 / 0 / 21 (+22) | holds |

**Table calibration48.** Claude Haiku 5.5 through this shell (in order) against the R1 shell, 48 tasks. All three intervals include 0.

| Condition | Haiku, this shell, 48 tasks | Haiku, R1 shell, same 48 tasks (3 reps) | Difference (95 % interval), points |
|---|---|---|---|
| S_shot | 81 % | 86 % | −5 (−13 to +3) |
| T_ours | 56 % | 57 % | −1 (−10 to +10) |
| H_ours | 83 % | 81 % | +3 (−2 to +8) |

**Table new21.** The 21 tasks added on 2026-11-14 alone.

| Model | S_shot | T_ours | H_ours | T_atspi |
|---|---|---|---|---|
| GLM | 17/21 | 16/21 | 17/21 | – |
| DeepSeek | 15/21 | 15/21 | 18/21 | – |
| LongCat | – | 14/21 | – | 14/21 |
| Claude Haiku 5.5 | 18/21 | 12/21 | 19/21 | – |

**Table steps48.** Means over valid episodes, 48 tasks; compare only within one model.

| Model | Condition | Steps | Model calls | Input / cache-read / output (reasoning) tokens | Cost (USD, shell estimate) | Wall mean / median (s) |
|---|---|---|---|---|---|---|
| GLM | S_shot | 11.4 | 20.4 | 62,020 / 142,048 / 977 (385) | 0.014 | 47 / 22 |
| GLM | T_ours | 11.9 | 14.7 | 30,922 / 247,744 / 1,329 (930) | 0.013 | 45 / 28 |
| GLM | H_ours | 10.9 | 12.4 | 133,296 / 116,435 / 950 (611) | 0.024 | 48 / 32 |
| DeepSeek | S_shot | 12.0 | 12.9 | 33,100 / 36,293 / 3,146 (2,361) | 0.007 | 77 / 46 |
| DeepSeek | T_ours | 11.8 | 12.8 | 26,804 / 204,498 / 4,262 (3,430) | 0.007 | 88 / 59 |
| DeepSeek | H_ours | 10.7 | 11.9 | 91,740 / 127,909 / 2,907 (2,169) | 0.016 | 87 / 47 |
| LongCat | T_ours | 12.1 | 13.2 | 38,969 / 259,640 / 11,298 (10,598) | 0.027 | 262 / 190 |
| LongCat | T_atspi | 14.8 | 16.2 | 33,666 / 249,267 / 6,339 (5,594) | 0.019 | 164 / 113 |
| Claude Haiku 5.5 | S_shot | 11.9 | 6.4 | 15 / 19,677 / 1,054 (0) | 0.003 | 19 / 15 |
| Claude Haiku 5.5 | T_ours | 14.0 | 7.5 | 17 / 102,416 / 1,836 (0) | 0.006 | 28 / 26 |
| Claude Haiku 5.5 | H_ours | 11.5 | 6.7 | 15 / 46,318 / 1,229 (0) | 0.012 | 24 / 19 |

What changed from the 27-task reading:

- **Stronger:** for Claude Haiku 5.5, our tree alone is worse than the screenshot (−25, interval −38 to −12) and the hybrid equals the screenshot (+2, −4 to 8), the same ranking as R1, now through a second shell.
- **Holds but smaller:** GLM gains from the hybrid over the screenshot: +15 (2 to 27), against +26 on 27 tasks; on the 21 new tasks both conditions scored 17/21.
- **Weaker, direction only:** DeepSeek tree versus screenshot +6 (−8 to 21; +11 on 27 tasks); LongCat our tree versus the AT-SPI list +8 (−8 to 25; +15 on 27 tasks). LongCat's gain comes entirely from the two GTK4 apps whose AT-SPI list is empty (gnome-contacts 6/6 vs 0/6, gnome-calendar 3/6 vs 0/6); on the other six apps the AT-SPI list is ahead, 29/36 vs 24/36.
- LongCat timed out in 12 `T_ours` and 3 `T_atspi` episodes (10-minute cap), counted as failures.

The sections below are the 27-task reading of 2026-11-13, kept unchanged.

## Results, 27 tasks (2026-11-13)

**Table scope_a.** Scope A, first 24 tasks, success as count and percentage.

| Model (shell) | S_shot | T_ours | H_ours | T_atspi |
|---|---|---|---|---|
| GLM 5.3 Flash | 17/24 (71 %) | 16/24 (67 %) | 22/24 (92 %) | – |
| DeepSeek V4.1 Flash | 17/24 (71 %) | 20/24 (83 %) | 19/24 (79 %) | – |
| LongCat 2.0 (no image input) | – | 18/24 (75 %) | – | 15/24 (62 %) |
| Claude Haiku 5.5 (this shell, calibration) | 20/24 (83 %) | 14/24 (58 %) | 20/24 (83 %) | – |
| *Claude Haiku 5.5 (R1 `claude -p` shell), same 24 tasks, mean of 3 reps* | *85 %* | *51 %* | *79 %* | – |

**Table scope_b.** Scope B, 27 tasks (scope A plus 3 gnome-calendar tasks).

| Model (shell) | S_shot | T_ours | H_ours | T_atspi |
|---|---|---|---|---|
| GLM 5.3 Flash | 17/27 (63 %) | 18/27 (67 %) | 24/27 (89 %) | – |
| DeepSeek V4.1 Flash | 19/27 (70 %) | 22/27 (81 %) | 21/27 (78 %) | – |
| LongCat 2.0 (no image input) | – | 19/27 (70 %) | – | 15/27 (56 %) |
| Claude Haiku 5.5 (this shell) | 21/27 (78 %) | 15/27 (56 %) | 21/27 (78 %) | – |
| *Claude Haiku 5.5 (R1 shell), same 27 tasks* | *83 %* | *49 %* | *75 %* | – |

**Table calendar3.** The three extra gnome-calendar tasks (counts out of 3).

| Model (shell) | S_shot | T_ours | H_ours | T_atspi |
|---|---|---|---|---|
| GLM 5.3 Flash | 0/3 | 2/3 | 2/3 | – |
| DeepSeek V4.1 Flash | 2/3 | 2/3 | 2/3 | – |
| LongCat 2.0 | – | 1/3 (2 timeouts) | – | 0/3 |
| Claude Haiku 5.5 (this shell) | 1/3 | 1/3 | 1/3 | – |

Reading within each model (scope A, then scope B; paired over tasks, win / loss / tie):

- **Tree versus screenshot (`T_ours` vs `S_shot`):** DeepSeek 5 / 2 / 17, then 6 / 3 / 18. GLM 3 / 4 / 17, then 5 / 4 / 18. Haiku 0 / 6 / 18, then 0 / 6 / 21 (the same direction as R1).
- **Screenshot plus tree (`H_ours` vs `S_shot`):** GLM 7 / 2 / 15, then 9 / 2 / 16. For DeepSeek and Haiku the hybrid is no better than the best single source.
- **Text-only model:** LongCat does better with our tree than with the system accessibility tree: 6 / 3 / 15, then 7 / 3 / 17. `T_atspi` scores 0/3 on gnome-contacts and 0/6 on gnome-calendar.
- **Shell calibration:** Haiku through this shell differs from Haiku in R1 by −1 / +7 / +4 points on scope A and −5 / +6 / +3 on scope B (`S_shot` / `T_ours` / `H_ours`), once the order fix is applied. Before the fix the figures were 42 / 33 / 46 %.

## Shell fix and reruns

**Table rerun.** Outcomes of the rerun episodes, before and after the order fix. "ok → fail" is the count of episodes that succeeded before and failed after.

| Model | Episodes rerun | OK before | OK after | ok→ok | fail→ok | ok→fail | fail→fail |
|---|---|---|---|---|---|---|---|
| DeepSeek | 11 | 4 | 5 | 2 | 3 | 2 | 4 |
| LongCat | 3 | 2 | 1 | 1 | 0 | 1 | 1 |
| Claude Haiku 5.5 (all) | 72 | 29 | 54 | 28 | 26 | 1 | 17 |
| Claude Haiku 5.5, second rerun (episodes with a fallback in the first rerun) | 11 | 4 | 3 | – | – | – | – |

For DeepSeek and LongCat the fix changes the net count very little (+1 and −1), because these models rarely batch calls. For Haiku, which batches calls in almost every episode, the fix accounts for most of the change. For the DeepSeek and LongCat reruns, each rerun is a fresh draw; the original racing episodes are kept as evidence and are included in the analysis together with the reruns.

**Table calibration.** Claude Haiku 5.5 before and after the order fix (first 24 tasks), compared with the R1 shell.

| Condition | Haiku, this shell, racing (first pass) | Haiku, this shell, in order (after fix) | Haiku, R1 shell, same 24 tasks (3 reps) | In order − R1 |
|---|---|---|---|---|
| S_shot | 10/24 (42 %) | 20/24 (83 %) | 85 % | −1 pt |
| T_ours | 8/24 (33 %) | 14/24 (58 %) | 51 % | +7 pts |
| H_ours | 11/24 (46 %) | 20/24 (83 %) | 79 % | +4 pts |

With in-order execution, this shell reproduces R1's Haiku numbers and ranking (`S_shot` ≈ `H_ours` > `T_ours`) within a few points on these tasks. Without the fix the shell would have cost Haiku 25–45 points; that is a harness effect, not a property of the model or of the observation.

## Paired differences

**Table paired.** Paired differences by task: win / loss / tie, and mean difference in points in parentheses.

| Model | Pair | Scope A (24) | Scope B (27) |
|---|---|---|---|
| GLM | T_ours − S_shot | 3 / 4 / 17 (−4) | 5 / 4 / 18 (+4) |
| GLM | H_ours − S_shot | 7 / 2 / 15 (+21) | 9 / 2 / 16 (+26) |
| GLM | H_ours − T_ours | 7 / 1 / 16 (+25) | 8 / 2 / 17 (+22) |
| DeepSeek | T_ours − S_shot | 5 / 2 / 17 (+12) | 6 / 3 / 18 (+11) |
| DeepSeek | H_ours − S_shot | 2 / 0 / 22 (+8) | 3 / 1 / 23 (+7) |
| DeepSeek | H_ours − T_ours | 2 / 3 / 19 (−4) | 2 / 3 / 22 (−4) |
| LongCat | T_ours − T_atspi | 6 / 3 / 15 (+12) | 7 / 3 / 17 (+15) |
| Claude Haiku 5.5 | T_ours − S_shot | 0 / 6 / 18 (−25) | 0 / 6 / 21 (−22) |
| Claude Haiku 5.5 | H_ours − S_shot | 1 / 1 / 22 (0) | 1 / 1 / 25 (0) |
| Claude Haiku 5.5 | H_ours − T_ours | 6 / 0 / 18 (+25) | 6 / 0 / 21 (+22) |

## Steps, tokens and wall-clock time

**Table steps.** Means over valid episodes, scope A. Compare only within one model. Tokens are as reported by the provider through the shell; cost is the shell's own price estimate.

| Model | Condition | Steps | Model calls | Input / cache-read / output (reasoning) tokens | Cost $ | Wall mean / median s | Stop reasons |
|---|---|---|---|---|---|---|---|
| GLM | S_shot | 11.1 | 27.0* | 63,622 / 258,309 / 1,222 (365) | 0.018 | 55 / 26 | done 18, step_limit 5, fail 1 |
| GLM | T_ours | 12.0 | 15.9 | 31,441 / 301,059 / 1,384 (953) | 0.014 | 43 / 26 | done 15, step_limit 8, no_done 1 |
| GLM | H_ours | 10.4 | 11.6 | 126,928 / 92,797 / 707 (392) | 0.022 | 39 / 26 | done 22, step_limit 2 |
| DeepSeek | S_shot | 12.0 | 12.7 | 32,006 / 32,661 / 2,887 (2,107) | 0.007 | 71 / 44 | done 17, step_limit 6, no_done 1 |
| DeepSeek | T_ours | 11.9 | 13.1 | 27,225 / 212,453 / 4,463 (3,629) | 0.007 | 90 / 53 | done 21, step_limit 3 |
| DeepSeek | H_ours | 10.8 | 11.9 | 96,747 / 126,384 / 3,095 (2,348) | 0.017 | 89 / 50 | done 18, step_limit 4, fail 2 |
| LongCat | T_ours | 11.6 | 12.8 | 38,325 / 266,949 / 11,860 (11,148) | 0.027 | 263 / 200 | done 15, timeout 6, step_limit 3 |
| LongCat | T_atspi | 14.8 | 16.6 | 36,886 / 265,877 / 8,485 (7,680) | 0.023 | 195 / 123 | done 12, step_limit 8, timeout 2, fail 1 |
| Claude Haiku 5.5 | S_shot | 11.5 | 6.2 | 14 / 18,620 / 1,062 (0) | 0.003 | 18 / 17 | done 14, step_limit 6, no_done 3, fail 1 |
| Claude Haiku 5.5 | T_ours | 13.7 | 7.5 | 17 / 103,009 / 1,654 (0) | 0.005 | 26 / 23 | done 15, step_limit 8, fail 1 |
| Claude Haiku 5.5 | H_ours | 11.7 | 6.7 | 15 / 48,096 / 1,350 (0) | 0.011 | 24 / 18 | done 17, step_limit 5, no_done 2 |

\* GLM `S_shot` includes one episode that kept calling `done` after the step limit (369 model calls); the median for that row is 11. Claude Haiku makes fewer model calls than steps because it batches calls, as in R1. Its input is almost all cache reads.

## Click check (image conditions)

Method: each click is drawn on the screen the agent saw before it. A red mark is the executed pixel point; a blue mark is where a reading in 0–1000 normalized coordinates would land. The model's own words before the call are the caption. Twenty-four clicks per model, spread evenly over the `S_shot` and `H_ours` episodes.

**Table click.** Coordinate convention of the clicks.

| Model | Hit as pixels | Hit only under 0–1000 reading | Miss under both | Cannot judge (no stated target) |
|---|---|---|---|---|
| GLM | 16 | 0 | 3 | 5 |
| DeepSeek | 24 | 0 | 0 | 0 |
| Claude Haiku 5.5 | 19 | 0 | 3 | 2 |

None of the three mixes 0–1000 coordinates (the Gemini reader in R4 did). The Haiku sample comes from the racing first pass; click geometry does not depend on execution order. Of GLM's 8 non-hits, 3 missed under both readings and 5 could not be judged.

**Table h_list.** `H_ours` clicks whose coordinates come from the element list (click within 3 px of the centre of an element in the observation just before), scope A.

| Model | Clicks from the list |
|---|---|
| GLM | 116 / 150 (77 %) |
| DeepSeek | 128 / 158 (81 %) |
| Claude Haiku 5.5 (in-order runs) | 75 / 106 (71 %) |
